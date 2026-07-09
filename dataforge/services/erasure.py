from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


class ErasureError(RuntimeError):
    pass


@dataclass(frozen=True)
class TableDeletionResult:
    table_name: str
    rows_deleted: int


@dataclass(frozen=True)
class StorageDeletionResult:
    storage_path: str
    deleted: bool
    error: str | None = None


@dataclass(frozen=True)
class ClientErasureResult:
    client_id: str
    dry_run: bool
    table_results: list[TableDeletionResult] = field(default_factory=list)
    storage_results: list[StorageDeletionResult] = field(default_factory=list)

    @property
    def total_rows_deleted(self) -> int:
        return sum(item.rows_deleted for item in self.table_results)


async def _table_exists(db: AsyncSession, table_name: str) -> bool:
    result = await db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = :table_name
            )
            """
        ),
        {"table_name": table_name},
    )
    return bool(result.scalar())


async def _delete_by_client_id(
    db: AsyncSession,
    table_name: str,
    client_id: str,
    dry_run: bool,
) -> TableDeletionResult:
    if not await _table_exists(db, table_name):
        return TableDeletionResult(table_name=table_name, rows_deleted=0)

    if dry_run:
        result = await db.execute(
            text(f"SELECT COUNT(*) FROM {table_name} WHERE client_id = :client_id"),
            {"client_id": client_id},
        )
        return TableDeletionResult(table_name=table_name, rows_deleted=int(result.scalar() or 0))

    result = await db.execute(
        text(f"DELETE FROM {table_name} WHERE client_id = :client_id"),
        {"client_id": client_id},
    )
    return TableDeletionResult(table_name=table_name, rows_deleted=int(result.rowcount or 0))


async def _delete_refresh_tokens_for_client(
    db: AsyncSession,
    client_id: str,
    dry_run: bool,
) -> TableDeletionResult:
    if not await _table_exists(db, "refresh_tokens"):
        return TableDeletionResult(table_name="refresh_tokens", rows_deleted=0)

    if not await _table_exists(db, "users"):
        return TableDeletionResult(table_name="refresh_tokens", rows_deleted=0)

    if dry_run:
        result = await db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM refresh_tokens
                WHERE user_id IN (
                    SELECT id
                    FROM users
                    WHERE client_id = :client_id
                )
                """
            ),
            {"client_id": client_id},
        )
        return TableDeletionResult(table_name="refresh_tokens", rows_deleted=int(result.scalar() or 0))

    result = await db.execute(
        text(
            """
            DELETE FROM refresh_tokens
            WHERE user_id IN (
                SELECT id
                FROM users
                WHERE client_id = :client_id
            )
            """
        ),
        {"client_id": client_id},
    )
    return TableDeletionResult(table_name="refresh_tokens", rows_deleted=int(result.rowcount or 0))


async def _list_storage_paths(db: AsyncSession, client_id: str) -> list[str]:
    if not await _table_exists(db, "file_storage_metadata"):
        return []

    result = await db.execute(
        text(
            """
            SELECT storage_path
            FROM file_storage_metadata
            WHERE client_id = :client_id
            AND deleted_at IS NULL
            AND storage_path IS NOT NULL
            """
        ),
        {"client_id": client_id},
    )
    return [str(row[0]) for row in result.fetchall()]


async def erase_client_data(
    db: AsyncSession,
    client_id: str,
    *,
    dry_run: bool = False,
    include_client_row: bool = True,
    delete_storage_object: Callable[[str], Awaitable[bool]] | None = None,
) -> ClientErasureResult:
    if not client_id:
        raise ErasureError("client_id is required for erasure.")

    storage_results: list[StorageDeletionResult] = []
    storage_paths = await _list_storage_paths(db, client_id)

    if not dry_run and delete_storage_object is not None:
        for storage_path in storage_paths:
            try:
                deleted = await delete_storage_object(storage_path)
                storage_results.append(StorageDeletionResult(storage_path=storage_path, deleted=deleted))
            except Exception as exc:  # defensive: external storage failure should stop DB erasure
                logger.exception(
                    "storage_deletion_failed",
                    extra={"client_id": client_id, "storage_path": storage_path},
                )
                raise ErasureError(f"Failed to delete storage object {storage_path}: {exc}") from exc
    else:
        storage_results = [
            StorageDeletionResult(storage_path=path, deleted=False if dry_run else True)
            for path in storage_paths
        ]

    # Delete child tables before parent tables. All table names are hardcoded to avoid SQL injection.
    ordered_client_scoped_tables = [
        "audit_log",
        "file_storage_metadata",
        "dead_letter_jobs",
        "jobs",
        "records",
        "token_usage_monthly",
        "api_keys",
    ]

    table_results: list[TableDeletionResult] = []

    table_results.append(await _delete_refresh_tokens_for_client(db, client_id, dry_run))

    for table_name in ordered_client_scoped_tables:
        table_results.append(await _delete_by_client_id(db, table_name, client_id, dry_run))

    table_results.append(await _delete_by_client_id(db, "users", client_id, dry_run))

    if include_client_row:
        table_results.append(await _delete_by_client_id(db, "clients", client_id, dry_run))

    if not dry_run:
        await db.commit()
    else:
        await db.rollback()

    logger.warning(
        "client_data_erasure_completed",
        extra={
            "client_id": client_id,
            "dry_run": dry_run,
            "total_rows_deleted": sum(item.rows_deleted for item in table_results),
            "storage_objects_seen": len(storage_paths),
        },
    )

    return ClientErasureResult(
        client_id=client_id,
        dry_run=dry_run,
        table_results=table_results,
        storage_results=storage_results,
    )
