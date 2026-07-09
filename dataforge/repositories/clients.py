from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dataforge.models_extended import Client, User


async def get_client_by_client_id(db: AsyncSession, client_id: str) -> Client | None:
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    return result.scalar_one_or_none()


async def list_users_for_client(db: AsyncSession, client_id: str) -> list[User]:
    result = await db.execute(
        select(User)
        .where(User.client_id == client_id)
        .order_by(User.created_at.desc())
    )
    return list(result.scalars().all())


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    normalized_email = email.strip().lower()
    result = await db.execute(select(User).where(User.email == normalized_email))
    return result.scalar_one_or_none()
