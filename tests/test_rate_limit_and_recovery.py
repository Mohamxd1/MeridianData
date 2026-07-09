from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

pytest.importorskip("sqlalchemy")

from dataforge.db import AuditLogRow, DeadLetterJobRow, JobRow, RecordRow, SessionLocal, init_db, utc_now
from dataforge.pipeline.save import create_job, recover_stuck_processing_jobs, set_job_payload
from dataforge.rate_limit import _memory_counters, check_rate_limit


def _clear_tables() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(AuditLogRow).delete()
        db.query(DeadLetterJobRow).delete()
        db.query(RecordRow).delete()
        db.query(JobRow).delete()
        db.commit()


def test_per_client_rate_limit_blocks_after_limit(monkeypatch):
    _memory_counters.clear()
    monkeypatch.setenv("DATAFORGE_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("DATAFORGE_RATE_LIMIT_STORAGE", "memory")
    monkeypatch.setenv("DATAFORGE_RATE_LIMIT_WINDOW_SECONDS", "3600")
    monkeypatch.setenv("DATAFORGE_RATE_LIMIT_DEMO_CLIENT_API", "2")

    first = check_rate_limit("demo_client", bucket="api")
    second = check_rate_limit("demo_client", bucket="api")

    assert first is not None and first.remaining == 1
    assert second is not None and second.remaining == 0
    with pytest.raises(HTTPException) as exc:
        check_rate_limit("demo_client", bucket="api")
    assert exc.value.status_code == 429


def test_startup_recovery_fails_stuck_processing_job(monkeypatch):
    _clear_tables()
    monkeypatch.setenv("DATAFORGE_STARTUP_RECOVERY_STRATEGY", "fail")
    monkeypatch.setenv("DATAFORGE_STUCK_JOB_MINUTES", "0")

    job_id = create_job("demo_client")
    set_job_payload("demo_client", job_id, [{"storage_path": "fake.txt"}])
    with SessionLocal() as db:
        row = db.get(JobRow, job_id)
        row.status = "processing"
        row.updated_at = utc_now()
        db.commit()

    result = recover_stuck_processing_jobs(max_age_minutes=0, strategy="fail")

    assert result["count"] == 1
    with SessionLocal() as db:
        row = db.get(JobRow, job_id)
        assert row.status == "failed"
        assert db.query(DeadLetterJobRow).filter(DeadLetterJobRow.job_id == job_id).count() == 1


def test_startup_recovery_requeues_when_callback_present(monkeypatch):
    _clear_tables()
    monkeypatch.setenv("DATAFORGE_STARTUP_RECOVERY_STRATEGY", "requeue")
    monkeypatch.setenv("DATAFORGE_STUCK_JOB_MINUTES", "0")

    job_id = create_job("demo_client")
    payload = [{"storage_path": "fake.txt"}]
    set_job_payload("demo_client", job_id, payload)
    with SessionLocal() as db:
        row = db.get(JobRow, job_id)
        row.status = "processing"
        row.updated_at = utc_now()
        db.commit()

    calls = []

    def fake_requeue(client_id: str, received_job_id: str, received_payload: list[dict]):
        calls.append((client_id, received_job_id, received_payload))

    result = recover_stuck_processing_jobs(max_age_minutes=0, strategy="requeue", requeue_callback=fake_requeue)

    assert result["count"] == 1
    assert calls == [("demo_client", job_id, payload)]
    with SessionLocal() as db:
        row = db.get(JobRow, job_id)
        assert row.status == "queued"
