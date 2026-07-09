from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import BackgroundTasks


def enqueue_rq_processing_job(client_id: str, job_id: str, file_objs: list[dict[str, Any]]) -> str:
    from redis import Redis
    from rq import Queue

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue = Queue("dataforge", connection=Redis.from_url(redis_url))
    queue.enqueue("dataforge.worker.process_job_sync", client_id, job_id, file_objs, job_timeout="30m")
    return "rq"


def enqueue_processing_job(
    background_tasks: BackgroundTasks,
    client_id: str,
    job_id: str,
    file_objs: list[dict[str, Any]],
) -> str:
    """Queue a processing job.

    Production: set DATAFORGE_QUEUE_MODE=rq and REDIS_URL.
    Local dev: defaults to FastAPI BackgroundTasks for easy `uvicorn` testing.
    """
    mode = os.getenv("DATAFORGE_QUEUE_MODE", "background").lower()
    if mode == "rq":
        return enqueue_rq_processing_job(client_id, job_id, file_objs)

    from dataforge.processor import process_job

    async def runner() -> None:
        await process_job(client_id, job_id, file_objs)

    background_tasks.add_task(lambda: asyncio.run(runner()))
    return "background"


def requeue_recovered_job(client_id: str, job_id: str, file_objs: list[dict[str, Any]]) -> None:
    """Startup recovery callback.

    Only RQ can be safely requeued at startup. BackgroundTasks needs an active
    request object, so recovered background-mode jobs should be marked failed by
    the recovery scanner instead of silently disappearing again.
    """
    mode = os.getenv("DATAFORGE_QUEUE_MODE", "background").lower()
    if mode != "rq":
        raise RuntimeError("Startup requeue requires DATAFORGE_QUEUE_MODE=rq")
    enqueue_rq_processing_job(client_id, job_id, file_objs)
