from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from dataforge.db import async_session_maker


logger = logging.getLogger(__name__)


async def reset_monthly_usage_counters() -> None:
    # Token usage rollups are month-keyed, so there may be no counter table to reset.
    # This job exists as a safe hook for future per-client monthly counters.
    async with async_session_maker() as db:
        await db.execute(text("SELECT 1"))
        await db.commit()

    logger.info("monthly_limit_reset_completed")


def main() -> None:
    asyncio.run(reset_monthly_usage_counters())


if __name__ == "__main__":
    main()
