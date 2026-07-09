from __future__ import annotations

import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from dataforge.db import async_session_maker
from dataforge.models_extended import Client


TEST_CLIENT_IDS = [
    "duplicate_client",
    "invalid_role_client",
    "email_client_a",
    "email_client_b",
    "client_a",
    "client_b",
    "cascade_client",
    "demo_client",
]


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with async_session_maker() as session:
        await _cleanup_test_rows(session)
        try:
            yield session
        finally:
            await session.rollback()
            await _cleanup_test_rows(session)


async def _cleanup_test_rows(session: AsyncSession) -> None:
    await session.rollback()
    await session.execute(delete(Client).where(Client.client_id.in_(TEST_CLIENT_IDS)))
    await session.commit()
