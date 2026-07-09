from __future__ import annotations

import json
import os
import uuid
from datetime import timedelta
from typing import Any, Callable

from dataforge.db import AuditLogRow, DeadLetterJobRow, JobRow, RecordRow, SessionLocal, init_db, utc_now
from dataforge.models import SavedRecord, ValidationResult


def save_record(
    record: dict[str, Any],
    client_id: str,
    raw_text: str = "",
    validation_result: ValidationResult | None = None,
    config_version: str | None = None,
    extraction_metrics: dict[str, Any] | None = None,
) -> SavedRecord:
    init_db()
    record_id = str(uuid.uuid4())
    created_at = utc_now()
    status = record.get("status", "pending_review")
    validation_result = validation_result or ValidationResult(status=status)

    with SessionLocal() as db:
        db.add(
            RecordRow(
                id=record_id,
                client_id=client_id,
                created_at=created_at,
                status=status,
                raw_text=raw_text,
                extracted_fields=json.dumps(record),
                validation_result=validation_result.model_dump_json(),
                exported=False,
                config_version=config_version,
                extraction_metrics=json.dumps(extraction_metrics or {}),
            )
        )
        db.add(AuditLogRow(
            id=str(uuid.uuid4()), client_id=client_id, record_id=record_id,
            action="record_created", actor="system", result_json=json.dumps({"status": status})
        ))
        db.commit()

    return SavedRecord(
        id=record_id,
        client_id=client_id,
        created_at=created_at,
        status=status,
        raw_text=raw_text,
        extracted_fields=record,
        validation_result=validation_result,
    )


def add_audit_log(
    client_id: str,
    action: str,
    record_id: str | None = None,
    job_id: str | None = None,
    actor: str | None = None,
    note: str | None = None,
    result: Any = None,
) -> str:
    init_db()
    audit_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(AuditLogRow(
            id=audit_id,
            client_id=client_id,
            record_id=record_id,
            job_id=job_id,
            action=action,
            actor=actor,
            note=note,
            result_json=json.dumps(result) if result is not None else None,
        ))
        db.commit()
    return audit_id


def list_audit_logs(client_id: str, record_id: str | None = None, job_id: str | None = None) -> list[dict[str, Any]]:
    init_db()
    with SessionLocal() as db:
        query = db.query(AuditLogRow).filter(AuditLogRow.client_id == client_id)
        if record_id:
            query = query.filter(AuditLogRow.record_id == record_id)
        if job_id:
            query = query.filter(AuditLogRow.job_id == job_id)
        rows = query.order_by(AuditLogRow.created_at.asc()).all()
        return [_audit_to_dict(row) for row in rows]


def get_record(client_id: str, record_id: str) -> dict[str, Any] | None:
    init_db()
    with SessionLocal() as db:
        row = db.get(RecordRow, record_id)
        if not row or row.client_id != client_id:
            return None
        return _record_to_dict(row)


def list_records(client_id: str, status: str | None = None, page: int = 1, page_size: int = 25) -> dict[str, Any]:
    init_db()
    with SessionLocal() as db:
        query = db.query(RecordRow).filter(RecordRow.client_id == client_id)
        if status:
            query = query.filter(RecordRow.status == status)
        total = query.count()
        rows = query.order_by(RecordRow.created_at.desc()).limit(page_size).offset((page - 1) * page_size).all()
        return {"records": [_record_to_dict(row) for row in rows], "total": total, "page": page}


def create_job(client_id: str) -> str:
    init_db()
    job_id = str(uuid.uuid4())
    now = utc_now()
    with SessionLocal() as db:
        db.add(JobRow(id=job_id, client_id=client_id, status="queued", created_at=now, updated_at=now))
        db.add(AuditLogRow(id=str(uuid.uuid4()), client_id=client_id, job_id=job_id, action="job_queued", actor="system"))
        db.commit()
    return job_id


def set_job_payload(client_id: str, job_id: str, payload: Any) -> bool:
    """Persist the processing payload so startup recovery can requeue stuck jobs."""
    init_db()
    with SessionLocal() as db:
        row = db.get(JobRow, job_id)
        if not row or row.client_id != client_id:
            return False
        row.payload_json = json.dumps(payload)
        row.updated_at = utc_now()
        db.add(AuditLogRow(
            id=str(uuid.uuid4()),
            client_id=client_id,
            job_id=job_id,
            action="job_payload_saved",
            actor="system",
            result_json=json.dumps({"payload_items": len(payload) if isinstance(payload, list) else 1}),
        ))
        db.commit()
        return True


def recover_stuck_processing_jobs(
    max_age_minutes: int | None = None,
    strategy: str | None = None,
    requeue_callback: Callable[[str, str, list[dict[str, Any]]], None] | None = None,
) -> dict[str, Any]:
    """Recover jobs left in processing after a server crash/restart.

    Strategy:
    - fail: mark stale jobs failed and move them to dead_letter_jobs.
    - requeue: if a persisted payload exists and a callback is provided, mark queued and
      re-enqueue it. Otherwise, fail safely.

    Env controls:
    DATAFORGE_STUCK_JOB_MINUTES=10
    DATAFORGE_STARTUP_RECOVERY_STRATEGY=fail|requeue
    """
    init_db()
    max_age = max_age_minutes if max_age_minutes is not None else int(os.getenv("DATAFORGE_STUCK_JOB_MINUTES", "10"))
    recovery_strategy = (strategy or os.getenv("DATAFORGE_STARTUP_RECOVERY_STRATEGY", "fail")).lower()
    cutoff = utc_now() - timedelta(minutes=max_age)
    recovered: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    jobs_to_requeue: list[tuple[str, str, list[dict[str, Any]]]] = []

    with SessionLocal() as db:
        rows = (
            db.query(JobRow)
            .filter(JobRow.status == "processing", JobRow.updated_at < cutoff)
            .all()
        )
        for row in rows:
            payload = json.loads(row.payload_json or "[]")
            can_requeue = recovery_strategy == "requeue" and isinstance(payload, list) and payload and requeue_callback is not None
            if can_requeue:
                row.status = "queued"
                row.updated_at = utc_now()
                row.error = "Recovered and requeued after startup scan"
                db.add(AuditLogRow(
                    id=str(uuid.uuid4()),
                    client_id=row.client_id,
                    job_id=row.id,
                    action="job_requeued_startup",
                    actor="system",
                    note=f"Job was stuck in processing for more than {max_age} minutes",
                ))
                jobs_to_requeue.append((row.client_id, row.id, payload))
                recovered.append({"job_id": row.id, "client_id": row.client_id, "action": "requeued"})
            else:
                error = f"Job marked failed by startup recovery after being stuck in processing for more than {max_age} minutes"
                row.status = "failed"
                row.updated_at = utc_now()
                row.error = error
                db.add(DeadLetterJobRow(
                    id=str(uuid.uuid4()),
                    client_id=row.client_id,
                    job_id=row.id,
                    error=error,
                    payload_json=row.payload_json,
                ))
                db.add(AuditLogRow(
                    id=str(uuid.uuid4()),
                    client_id=row.client_id,
                    job_id=row.id,
                    action="job_failed_startup_recovery",
                    actor="system",
                    note=error,
                ))
                failed.append({"job_id": row.id, "client_id": row.client_id})
        db.commit()

    # Enqueue after the DB transaction commits so the worker sees the queued state.
    for client_id, job_id, payload in jobs_to_requeue:
        requeue_callback(client_id, job_id, payload)

    return {"recovered": recovered, "failed": failed, "count": len(recovered) + len(failed)}


def update_job(client_id: str, job_id: str, status: str, result: Any = None, error: str | None = None, increment_attempts: bool = False) -> None:
    init_db()
    with SessionLocal() as db:
        row = db.get(JobRow, job_id)
        if not row or row.client_id != client_id:
            return
        row.status = status
        row.updated_at = utc_now()
        if increment_attempts:
            row.attempts += 1
        row.result = json.dumps(result) if result is not None else row.result
        row.error = error
        db.add(AuditLogRow(
            id=str(uuid.uuid4()), client_id=client_id, job_id=job_id, action=f"job_{status}", actor="system",
            result_json=json.dumps(result) if result is not None else None, note=error
        ))
        db.commit()


def move_job_to_dead_letter(client_id: str, job_id: str, error: str, payload: Any = None) -> None:
    init_db()
    with SessionLocal() as db:
        db.add(DeadLetterJobRow(
            id=str(uuid.uuid4()), client_id=client_id, job_id=job_id, error=error,
            payload_json=json.dumps(payload) if payload is not None else None,
        ))
        db.commit()


def get_job(client_id: str, job_id: str) -> dict[str, Any] | None:
    init_db()
    with SessionLocal() as db:
        row = db.get(JobRow, job_id)
        if not row or row.client_id != client_id:
            return None
        data = _job_to_dict(row)
        if data.get("result"):
            data["result"] = json.loads(data["result"])
        return data


def set_record_status_if_allowed(
    client_id: str,
    record_id: str,
    new_status: str,
    actor: str | None = None,
    note: str | None = None,
    exported: bool | None = None,
    action: str | None = None,
    result: Any = None,
) -> tuple[bool, str | None]:
    """Update status with idempotency/state guards.

    Returns (updated, conflict_reason). If the record does not exist, returns (False, None).
    """
    init_db()
    with SessionLocal() as db:
        row = db.get(RecordRow, record_id)
        if not row or row.client_id != client_id:
            return False, None
        if row.status == new_status:
            return False, f"record is already {new_status}"
        if row.status in {"approved", "rejected"} and new_status in {"approved", "rejected"}:
            return False, f"cannot change finalized record from {row.status} to {new_status}"
        row.status = new_status
        if exported is not None:
            row.exported = exported
        db.add(AuditLogRow(
            id=str(uuid.uuid4()), client_id=client_id, record_id=record_id,
            action=action or f"record_{new_status}", actor=actor, note=note,
            result_json=json.dumps(result) if result is not None else None,
        ))
        db.commit()
        return True, None


def mark_record_status(client_id: str, record_id: str, status: str, exported: bool | None = None) -> bool:
    init_db()
    with SessionLocal() as db:
        row = db.get(RecordRow, record_id)
        if not row or row.client_id != client_id:
            return False
        row.status = status
        if exported is not None:
            row.exported = exported
        db.commit()
        return True


def approved_unexported_records(client_id: str) -> list[dict[str, Any]]:
    init_db()
    with SessionLocal() as db:
        rows = db.query(RecordRow).filter(
            RecordRow.client_id == client_id, RecordRow.status == "approved", RecordRow.exported.is_(False)
        ).all()
        return [_record_to_dict(row) for row in rows]


def _record_to_dict(row: RecordRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "client_id": row.client_id,
        "created_at": row.created_at.isoformat(),
        "status": row.status,
        "raw_text": row.raw_text,
        "extracted_fields": row.extracted_fields,
        "validation_result": row.validation_result,
        "exported": row.exported,
        "config_version": row.config_version,
        "extraction_metrics": row.extraction_metrics,
    }


def _job_to_dict(row: JobRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "client_id": row.client_id,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "result": row.result,
        "error": row.error,
        "attempts": row.attempts,
        "has_payload": bool(row.payload_json),
    }


def _audit_to_dict(row: AuditLogRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "client_id": row.client_id,
        "record_id": row.record_id,
        "job_id": row.job_id,
        "action": row.action,
        "actor": row.actor,
        "note": row.note,
        "result": json.loads(row.result_json) if row.result_json else None,
        "created_at": row.created_at.isoformat(),
    }
