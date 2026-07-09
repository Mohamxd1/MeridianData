from __future__ import annotations

import asyncio
from typing import Any

from dataforge.db import init_db
from dataforge.processor import process_job


def process_job_sync(client_id: str, job_id: str, file_objs: list[dict[str, Any]]) -> None:
    init_db()
    asyncio.run(process_job(client_id, job_id, file_objs))
