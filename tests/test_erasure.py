from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dataforge.services.erasure import erase_client_data


pytestmark = pytest.mark.asyncio


async def _create_minimal_tables(db: AsyncSession) -> None:
    await db.execute(text("CREATE TABLE IF NOT EXISTS clients (client_id TEXT PRIMARY KEY)"))
    await db.execute(text("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, client_id TEXT NOT NULL)"))
    await db.execute(text("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, client_id TEXT NOT NULL)"))
    await db.execute(text("CREATE TABLE IF NOT EXISTS audit_log (id TEXT PRIMARY KEY, client_id TEXT NOT NULL)"))
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS file_storage_metadata (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                deleted_at TIMESTAMPTZ
            )
            """
        )
    )
    await db.commit()


async def test_erase_client_data_dry_run_does_not_delete(db_session: AsyncSession) -> None:
    await _create_minimal_tables(db_session)

    await db_session.execute(text("INSERT INTO clients (client_id) VALUES ('client_a')"))
    await db_session.execute(text("INSERT INTO records (id, client_id) VALUES ('r1', 'client_a')"))
    await db_session.execute(text("INSERT INTO jobs (id, client_id) VALUES ('j1', 'client_a')"))
    await db_session.execute(text("INSERT INTO audit_log (id, client_id) VALUES ('a1', 'client_a')"))
    await db_session.commit()

    result = await erase_client_data(db_session, "client_a", dry_run=True)

    assert result.dry_run is True
    assert result.total_rows_deleted >= 4

    remaining = await db_session.execute(text("SELECT COUNT(*) FROM records WHERE client_id='client_a'"))
    assert remaining.scalar() == 1


async def test_erase_client_data_deletes_only_target_client(db_session: AsyncSession) -> None:
    await _create_minimal_tables(db_session)

    await db_session.execute(text("INSERT INTO clients (client_id) VALUES ('client_a'), ('client_b')"))
    await db_session.execute(text("INSERT INTO records (id, client_id) VALUES ('ra', 'client_a'), ('rb', 'client_b')"))
    await db_session.execute(text("INSERT INTO jobs (id, client_id) VALUES ('ja', 'client_a'), ('jb', 'client_b')"))
    await db_session.commit()

    result = await erase_client_data(db_session, "client_a", dry_run=False)

    assert result.dry_run is False
    assert result.total_rows_deleted >= 3

    a_records = await db_session.execute(text("SELECT COUNT(*) FROM records WHERE client_id='client_a'"))
    b_records = await db_session.execute(text("SELECT COUNT(*) FROM records WHERE client_id='client_b'"))

    assert a_records.scalar() == 0
    assert b_records.scalar() == 1


async def test_erase_client_data_calls_storage_deleter(db_session: AsyncSession) -> None:
    await _create_minimal_tables(db_session)

    await db_session.execute(text("INSERT INTO clients (client_id) VALUES ('client_a')"))
    await db_session.execute(
        text(
            """
            INSERT INTO file_storage_metadata (id, client_id, storage_path)
            VALUES ('f1', 'client_a', 'client_a/2026/05/job/file.txt')
            """
        )
    )
    await db_session.commit()

    deleted_paths: list[str] = []

    async def fake_delete_storage_object(storage_path: str) -> bool:
        deleted_paths.append(storage_path)
        return True

    result = await erase_client_data(
        db_session,
        "client_a",
        dry_run=False,
        delete_storage_object=fake_delete_storage_object,
    )

    assert deleted_paths == ["client_a/2026/05/job/file.txt"]
    assert len(result.storage_results) == 1
    assert result.storage_results[0].deleted is True
