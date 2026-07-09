from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("sqlalchemy")

from dataforge.db import AuditLogRow, DeadLetterJobRow, JobRow, RecordRow, SessionLocal, init_db
from dataforge.pipeline import extract as extract_module
from dataforge.pipeline.export import _export_airtable, _export_crm, _export_email
from dataforge.models import OutputDestination


def _clear_tables() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(AuditLogRow).delete()
        db.query(DeadLetterJobRow).delete()
        db.query(RecordRow).delete()
        db.query(JobRow).delete()
        db.commit()


@pytest.mark.asyncio
async def test_extraction_persists_token_usage_shape(monkeypatch):
    async def fake_call(system_prompt, document_text, model):
        return '{"tenant_name":"Amina Ali"}', {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
        }

    monkeypatch.setattr(extract_module, "_call_openai_json", fake_call)
    result = await extract_module.extract_fields(
        "Tenant Amina Ali submitted a request.",
        {"tenant_name": "string"},
        "Extract fields.",
    )

    assert result["tenant_name"] == "Amina Ali"
    assert result["_token_usage"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }


def test_email_export_stub_includes_html_table(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    destination = OutputDestination(type="email", config={"to": "ops@example.com"})
    result = _export_email(
        {"status": "approved", "tenant_name": "Amina Ali", "unit_number": "204"},
        destination,
    )

    assert result["exported"] is True
    outbox = Path(result["path"])
    payload = json.loads(outbox.read_text().strip())
    assert "<table" in payload["html"]
    assert "tenant_name" in payload["html"]
    assert "Amina Ali" in payload["html"]


def test_json_body_limit_blocks_large_export_payload(monkeypatch):
    _clear_tables()
    monkeypatch.setenv("DATAFORGE_DEV_MODE", "true")
    monkeypatch.setenv("DATAFORGE_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("DATAFORGE_MAX_JSON_BODY_BYTES", "25")

    from dataforge.main import app

    client = TestClient(app)
    response = client.post(
        "/clients/demo_client/export",
        json={"format": "x" * 100},
    )

    assert response.status_code == 413
    assert "JSON body too large" in response.json()["detail"]


def test_end_to_end_upload_pipeline_approve_export(monkeypatch, tmp_path):
    _clear_tables()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATAFORGE_DEV_MODE", "true")
    monkeypatch.setenv("DATAFORGE_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("DATAFORGE_QUEUE_MODE", "background")

    async def fake_extract_fields(text, schema, extraction_prompt, model="gpt-4o", provider="openai"):
        return {
            "tenant_name": "Amina Ali",
            "unit_number": "204",
            "property_address": "100 Main St",
            "request_type": "maintenance",
            "issue_description": "Sink leak",
            "urgency_level": "high",
            "contact_phone": "612-555-1010",
            "preferred_entry_date": None,
            "permission_to_enter": True,
            "_confidence": {"tenant_name": 0.99, "unit_number": 0.98},
            "_token_usage": {"input_tokens": 42, "output_tokens": 15, "total_tokens": 57},
        }

    monkeypatch.setattr("dataforge.processor.extract_fields", fake_extract_fields)

    from dataforge.main import app

    client = TestClient(app)
    upload_response = client.post(
        "/clients/demo_client/process-files",
        files={"files": ("maintenance_request.txt", b"Tenant Amina Ali reports sink leak in unit 204.", "text/plain")},
    )
    assert upload_response.status_code == 202

    records_response = client.get("/clients/demo_client/records")
    assert records_response.status_code == 200
    records = records_response.json()["records"]
    assert len(records) == 1
    record = records[0]
    record_id = record["id"]
    assert record["extraction_metrics"]["input_tokens"] == 42
    assert record["extraction_metrics"]["output_tokens"] == 15

    approve_response = client.patch(
        f"/clients/demo_client/records/{record_id}/approve",
        json={"reviewer_note": "Looks correct"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    export_response = client.post("/clients/demo_client/export", json={"format": "csv"})
    assert export_response.status_code == 200
    assert "exported_record_ids" in export_response.json()

    detail_response = client.get(f"/clients/demo_client/records/{record_id}")
    assert detail_response.status_code == 200
    audit_actions = [entry["action"] for entry in detail_response.json()["audit_log"]]
    assert "extraction_completed" in audit_actions
    assert "record_approved" in audit_actions



@pytest.mark.asyncio
async def test_anthropic_provider_requires_explicit_model():
    with pytest.raises(extract_module.ConfigurationError) as exc_info:
        await extract_module.extract_fields(
            "Tenant Amina Ali submitted a request.",
            {"tenant_name": "string"},
            "Extract fields.",
            model="gpt-4o",
            provider="anthropic",
        )

    assert "ai_model must be set" in str(exc_info.value)


def test_json_body_limit_path_matching_is_exact():
    from dataforge.main import _is_json_body_limited_path

    assert _is_json_body_limited_path("/clients/demo_client/export") is True
    assert _is_json_body_limited_path("/clients/demo_client/intake-webhook") is True
    assert _is_json_body_limited_path("/clients/demo_client/data-export") is False
    assert _is_json_body_limited_path("/clients/demo_client/export/history") is False
    assert _is_json_body_limited_path("/export") is False


def test_airtable_and_crm_stub_exports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    record = {"status": "approved", "tenant_name": "Amina Ali", "unit_number": "204"}

    airtable_destination = OutputDestination(
        type="airtable",
        config={"field_mapping": {"tenant_name": "Tenant Name", "unit_number": "Unit"}},
    )
    airtable_result = _export_airtable(record, airtable_destination)
    assert airtable_result["exported"] is True
    assert airtable_result["type"] == "airtable_stub"
    airtable_payload = json.loads(Path(airtable_result["path"]).read_text().strip())
    assert airtable_payload["fields"] == {"Tenant Name": "Amina Ali", "Unit": "204"}

    crm_destination = OutputDestination(
        type="crm",
        config={"object_type": "ticket", "field_mapping": {"tenant_name": "name"}},
    )
    crm_result = _export_crm(record, crm_destination)
    assert crm_result["exported"] is True
    assert crm_result["type"] == "crm_stub"
    crm_payload = json.loads(Path(crm_result["path"]).read_text().strip())
    assert crm_payload["object_type"] == "ticket"
    assert crm_payload["fields"] == {"name": "Amina Ali"}
