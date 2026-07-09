from __future__ import annotations

import json
import re
import logging
import os
import uuid
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from dataforge.auth import verify_api_key
from dataforge.config import load_client_config, redact_config
from dataforge.db import init_db
from dataforge.logging_config import client_id_ctx, configure_logging, request_id_ctx
from dataforge.models import ProcessFileResponse
from dataforge.rate_limit import add_rate_limit_headers, check_rate_limit, enforce_api_rate_limit
from dataforge.pipeline.export import export_record
from dataforge.pipeline.intake import intake
from dataforge.pipeline.save import (
    add_audit_log,
    approved_unexported_records,
    create_job,
    get_job as load_job,
    get_record,
    list_audit_logs,
    list_records,
    mark_record_status,
    recover_stuck_processing_jobs,
    set_job_payload,
    set_record_status_if_allowed,
)
from dataforge.queue import enqueue_processing_job, requeue_recovered_job

configure_logging()
logger = logging.getLogger(__name__)
app = FastAPI(title="DataForge", version="0.4.2")


DEFAULT_MAX_JSON_BODY_BYTES = 1024 * 1024


def _max_json_body_bytes() -> int:
    return int(os.getenv("DATAFORGE_MAX_JSON_BODY_BYTES", str(DEFAULT_MAX_JSON_BODY_BYTES)))
JSON_LIMITED_PATH_RE = re.compile(r"^/clients/[^/]+/(export|intake-webhook)$")


def _is_json_body_limited_path(path: str) -> bool:
    return JSON_LIMITED_PATH_RE.fullmatch(path) is not None


def _cors_origins_from_env() -> list[str]:
    raw = os.getenv("DATAFORGE_CORS_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


class JSONBodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        is_limited_endpoint = request.method in {"POST", "PATCH", "PUT"} and _is_json_body_limited_path(request.url.path)
        if not is_limited_endpoint:
            return await call_next(request)

        content_type = request.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            return await call_next(request)

        max_json_body_bytes = _max_json_body_bytes()
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > max_json_body_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": f"JSON body too large. Max size is {max_json_body_bytes} bytes"},
            )

        body = await request.body()
        if len(body) > max_json_body_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": f"JSON body too large. Max size is {max_json_body_bytes} bytes"},
            )

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        limited_request = Request(request.scope, receive)
        limited_request.state.request_id = getattr(request.state, "request_id", None)
        limited_request.state.actor = getattr(request.state, "actor", None)
        return await call_next(limited_request)



class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        parts = request.url.path.strip("/").split("/")
        client_id = parts[1] if len(parts) >= 2 and parts[0] == "clients" else None
        token_1 = request_id_ctx.set(request_id)
        token_2 = client_id_ctx.set(client_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            add_rate_limit_headers(response, getattr(request.state, "rate_limit", None))
            return response
        finally:
            request_id_ctx.reset(token_1)
            client_id_ctx.reset(token_2)


cors_origins = _cors_origins_from_env()
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials="*" not in cors_origins,
        allow_methods=["GET", "POST", "PATCH", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
    )

app.add_middleware(RequestContextMiddleware)
app.add_middleware(JSONBodySizeLimitMiddleware)


@app.on_event("startup")
def startup() -> None:
    init_db()
    strategy = os.getenv("DATAFORGE_STARTUP_RECOVERY_STRATEGY", "fail").lower()
    queue_mode = os.getenv("DATAFORGE_QUEUE_MODE", "background").lower()
    callback = requeue_recovered_job if strategy == "requeue" and queue_mode == "rq" else None
    recovery = recover_stuck_processing_jobs(requeue_callback=callback)
    if recovery.get("count"):
        logger.warning("startup_recovered_stuck_jobs", extra={"recovery": recovery})


def _parse_record_row(row: dict[str, Any]) -> dict[str, Any]:
    row["extracted_fields"] = json.loads(row["extracted_fields"])
    row["validation_result"] = json.loads(row["validation_result"])
    row["extraction_metrics"] = json.loads(row["extraction_metrics"] or "{}")
    return row


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/clients/{client_id}/config", dependencies=[Depends(verify_api_key), Depends(enforce_api_rate_limit)])
def get_config(client_id: str) -> dict[str, Any]:
    return redact_config(load_client_config(client_id))


@app.post("/clients/{client_id}/process-files", response_model=ProcessFileResponse, status_code=202, dependencies=[Depends(verify_api_key), Depends(enforce_api_rate_limit)])
async def process_files(
    client_id: str,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
) -> ProcessFileResponse:
    load_client_config(client_id)
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    check_rate_limit(client_id, bucket="files", cost=len(files))

    job_id = create_job(client_id)
    file_objs = []
    for file in files:
        file_obj = await intake(file, client_id)
        file_objs.append(file_obj.model_dump(mode="json"))
        add_audit_log(client_id, "file_intake", job_id=job_id, actor="system", result=file_obj.model_dump(mode="json"))

    set_job_payload(client_id, job_id, file_objs)
    queue_mode = enqueue_processing_job(background_tasks, client_id, job_id, file_objs)
    add_audit_log(client_id, "job_enqueued", job_id=job_id, actor="system", result={"queue_mode": queue_mode})
    return ProcessFileResponse(job_id=job_id, message=f"Files queued for processing via {queue_mode}")


@app.get("/clients/{client_id}/jobs/{job_id}", dependencies=[Depends(verify_api_key), Depends(enforce_api_rate_limit)])
def get_job(client_id: str, job_id: str) -> dict[str, Any]:
    job = load_job(client_id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["audit_log"] = list_audit_logs(client_id, job_id=job_id)
    return job


@app.get("/clients/{client_id}/records", dependencies=[Depends(verify_api_key), Depends(enforce_api_rate_limit)])
def records(
    client_id: str,
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> dict[str, Any]:
    load_client_config(client_id)
    result = list_records(client_id, status, page, page_size)
    result["records"] = [_parse_record_row(row) for row in result["records"]]
    return result


@app.get("/clients/{client_id}/records/{record_id}", dependencies=[Depends(verify_api_key), Depends(enforce_api_rate_limit)])
def record_detail(client_id: str, record_id: str) -> dict[str, Any]:
    row = get_record(client_id, record_id)
    if not row:
        raise HTTPException(status_code=404, detail="Record not found")
    row = _parse_record_row(row)
    row["audit_log"] = list_audit_logs(client_id, record_id=record_id)
    return row


@app.patch("/clients/{client_id}/records/{record_id}/approve", dependencies=[Depends(verify_api_key), Depends(enforce_api_rate_limit)])
def approve_record(request: Request, client_id: str, record_id: str, body: dict[str, str] | None = None) -> dict[str, Any]:
    config = load_client_config(client_id)
    row = get_record(client_id, record_id)
    if not row:
        raise HTTPException(status_code=404, detail="Record not found")
    if row["status"] == "approved":
        raise HTTPException(status_code=409, detail="Record is already approved")
    if row["status"] == "rejected":
        raise HTTPException(status_code=409, detail="Rejected records cannot be approved")

    record = json.loads(row["extracted_fields"])
    record["status"] = "approved"
    export_result = export_record(record, config.output_destination)
    updated, conflict = set_record_status_if_allowed(
        client_id,
        record_id,
        "approved",
        actor=getattr(request.state, "actor", "unknown"),
        note=(body or {}).get("reviewer_note"),
        exported=bool(export_result.get("exported")),
        action="record_approved",
        result={"export": export_result},
    )
    if conflict:
        raise HTTPException(status_code=409, detail=conflict)
    if not updated:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"record_id": record_id, "status": "approved", "export": export_result, "reviewer_note": (body or {}).get("reviewer_note")}


@app.patch("/clients/{client_id}/records/{record_id}/reject", dependencies=[Depends(verify_api_key), Depends(enforce_api_rate_limit)])
def reject_record(request: Request, client_id: str, record_id: str, body: dict[str, str]) -> dict[str, Any]:
    load_client_config(client_id)
    reason = body.get("rejection_reason")
    if not reason:
        raise HTTPException(status_code=400, detail="rejection_reason is required")
    row = get_record(client_id, record_id)
    if not row:
        raise HTTPException(status_code=404, detail="Record not found")
    if row["status"] == "rejected":
        raise HTTPException(status_code=409, detail="Record is already rejected")
    if row["status"] == "approved":
        raise HTTPException(status_code=409, detail="Approved records cannot be rejected")
    updated, conflict = set_record_status_if_allowed(
        client_id,
        record_id,
        "rejected",
        actor=getattr(request.state, "actor", "unknown"),
        note=reason,
        action="record_rejected",
    )
    if conflict:
        raise HTTPException(status_code=409, detail=conflict)
    if not updated:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"record_id": record_id, "status": "rejected", "rejection_reason": reason}


@app.post("/clients/{client_id}/export", dependencies=[Depends(verify_api_key), Depends(enforce_api_rate_limit)])
def bulk_export(request: Request, client_id: str, body: dict[str, Any]) -> dict[str, Any]:
    config = load_client_config(client_id)
    rows = approved_unexported_records(client_id)
    exported: list[str] = []
    failed: list[dict[str, str]] = []
    for row in rows:
        try:
            record = json.loads(row["extracted_fields"])
            record["status"] = "approved"
            result = export_record(record, config.output_destination)
            if result.get("exported"):
                mark_record_status(client_id, row["id"], "approved", exported=True)
                add_audit_log(
                    client_id, "record_exported", record_id=row["id"], actor=getattr(request.state, "actor", "unknown"), result=result
                )
                exported.append(row["id"])
            else:
                failed.append({"record_id": row["id"], "error": result.get("reason", "not exported")})
        except Exception as exc:
            add_audit_log(
                client_id, "record_export_failed", record_id=row["id"], actor=getattr(request.state, "actor", "unknown"), note=str(exc)
            )
            failed.append({"record_id": row["id"], "error": str(exc)})
            continue
    return {"exported_record_ids": exported, "failed": failed, "count": len(exported), "requested_format": body.get("format")}


@app.post("/clients/{client_id}/intake-webhook", status_code=202, dependencies=[Depends(verify_api_key), Depends(enforce_api_rate_limit)])
def intake_webhook(client_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Lightweight webhook intake for email parsers/Zapier/Make.

    For attachments, use /process-files. This endpoint stores the inbound payload as an audit event
    so a worker can be added later to turn it into a normal document record.
    """
    load_client_config(client_id)
    job_id = create_job(client_id)
    add_audit_log(client_id, "webhook_intake_received", job_id=job_id, actor="webhook", result=payload)
    return {"job_id": job_id, "status": "queued", "message": "Webhook intake received"}
