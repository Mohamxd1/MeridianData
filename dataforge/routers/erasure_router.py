from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dataforge.db import get_db
from dataforge.services.erasure import ClientErasureResult, ErasureError, erase_client_data


router = APIRouter(tags=["data-erasure"])


class TableDeletionResponse(BaseModel):
    table_name: str
    rows_deleted: int


class StorageDeletionResponse(BaseModel):
    storage_path: str
    deleted: bool
    error: str | None = None


class ClientErasureResponse(BaseModel):
    client_id: str
    dry_run: bool
    total_rows_deleted: int
    table_results: list[TableDeletionResponse]
    storage_results: list[StorageDeletionResponse]


def _to_response(result: ClientErasureResult) -> ClientErasureResponse:
    return ClientErasureResponse(
        client_id=result.client_id,
        dry_run=result.dry_run,
        total_rows_deleted=result.total_rows_deleted,
        table_results=[
            TableDeletionResponse(
                table_name=item.table_name,
                rows_deleted=item.rows_deleted,
            )
            for item in result.table_results
        ],
        storage_results=[
            StorageDeletionResponse(
                storage_path=item.storage_path,
                deleted=item.deleted,
                error=item.error,
            )
            for item in result.storage_results
        ],
    )


@router.delete(
    "/admin/clients/{client_id}/data",
    response_model=ClientErasureResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_client_data_admin(
    client_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    confirm: Annotated[
        str,
        Query(
            description='Must exactly equal: DELETE <client_id>. Example: "DELETE demo_client"',
        ),
    ],
    dry_run: bool = Query(default=True),
) -> ClientErasureResponse:
    expected_confirmation = f"DELETE {client_id}"

    if confirm != expected_confirmation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Confirmation mismatch. Pass confirm="{expected_confirmation}" to continue.',
        )

    try:
        result = await erase_client_data(
            db,
            client_id,
            dry_run=dry_run,
            include_client_row=True,
        )
    except ErasureError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return _to_response(result)
