from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from sqlalchemy import text

from dataforge.db import async_session_maker


logger = logging.getLogger(__name__)


async def find_clients_near_limits() -> list[dict[str, object]]:
    query = text(
        """
        SELECT
            c.client_id,
            c.company_name,
            c.monthly_file_limit,
            c.monthly_token_limit,
            COALESCE(t.total_tokens, 0) AS total_tokens
        FROM clients c
        LEFT JOIN token_usage_monthly t
            ON t.client_id = c.client_id
            AND t.year_month = to_char(now(), 'YYYY-MM')
        WHERE c.status = 'active'
        AND (
            (c.monthly_token_limit IS NOT NULL AND COALESCE(t.total_tokens, 0) >= c.monthly_token_limit * 0.8)
        )
        """
    )

    async with async_session_maker() as db:
        result = await db.execute(query)
        return [dict(row._mapping) for row in result.fetchall()]


async def send_limit_warning_emails() -> None:
    clients = await find_clients_near_limits()

    for client in clients:
        logger.warning(
            "client_limit_warning_needed",
            extra={
                "client_id": client["client_id"],
                "company_name": client["company_name"],
                "total_tokens": int(client["total_tokens"] or 0),
                "monthly_token_limit": client["monthly_token_limit"],
            },
        )

    logger.info("limit_warning_scan_completed", extra={"client_count": len(clients)})


def main() -> None:
    asyncio.run(send_limit_warning_emails())


if __name__ == "__main__":
    main()
