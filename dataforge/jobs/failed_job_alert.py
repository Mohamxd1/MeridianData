from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from dataforge.db import async_session_maker


logger = logging.getLogger(__name__)


async def count_recent_failures() -> dict[str, int]:
    query = text(
        """
        SELECT
            COALESCE(COUNT(*), 0) AS dead_letter_count
        FROM dead_letter_jobs
        WHERE created_at >= now() - interval '1 hour'
        """
    )

    async with async_session_maker() as db:
        result = await db.execute(query)
        row = result.one()
        return {"dead_letter_count": int(row.dead_letter_count or 0)}


async def alert_on_failed_jobs() -> None:
    counts = await count_recent_failures()

    if counts["dead_letter_count"] > 0:
        logger.error(
            "recent_dead_letter_jobs_detected",
            extra=counts,
        )
    else:
        logger.info("failed_job_alert_scan_clean", extra=counts)


def main() -> None:
    asyncio.run(alert_on_failed_jobs())


if __name__ == "__main__":
    main()
