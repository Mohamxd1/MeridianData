from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dataforge.db import async_session_maker
from dataforge.models_extended import Client, User
from dataforge.security.passwords import hash_password


class SeedConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class DemoSeedSettings:
    client_id: str
    company_name: str
    owner_email: str
    owner_password: str


def get_demo_seed_settings() -> DemoSeedSettings:
    owner_password = os.getenv("DATAFORGE_DEMO_OWNER_PASSWORD")

    if not owner_password:
        raise SeedConfigurationError(
            "DATAFORGE_DEMO_OWNER_PASSWORD must be set before running the demo seed. "
            "Do not rely on a hardcoded default password."
        )

    return DemoSeedSettings(
        client_id=os.getenv("DATAFORGE_DEMO_CLIENT_ID", "demo_client"),
        company_name=os.getenv("DATAFORGE_DEMO_COMPANY_NAME", "Demo Client"),
        owner_email=os.getenv("DATAFORGE_DEMO_OWNER_EMAIL", "admin@demo.dataforge.io").strip().lower(),
        owner_password=owner_password,
    )


async def seed_demo_client(db: AsyncSession) -> None:
    settings = get_demo_seed_settings()

    existing_client_result = await db.execute(
        select(Client).where(Client.client_id == settings.client_id)
    )
    existing_client = existing_client_result.scalar_one_or_none()

    if existing_client is None:
        db.add(
            Client(
                client_id=settings.client_id,
                company_name=settings.company_name,
                plan="starter",
                status="active",
                config_version=1,
                file_retention_days=90,
                monthly_file_limit=500,
                monthly_token_limit=500_000,
            )
        )
        await db.flush()

    existing_user_result = await db.execute(
        select(User).where(User.email == settings.owner_email)
    )
    existing_user = existing_user_result.scalar_one_or_none()

    if existing_user is None:
        db.add(
            User(
                client_id=settings.client_id,
                email=settings.owner_email,
                hashed_password=hash_password(settings.owner_password),
                role="client_owner",
                is_active=True,
            )
        )

    await db.commit()


async def main() -> None:
    settings = get_demo_seed_settings()
    async with async_session_maker() as db:
        await seed_demo_client(db)
    print(f"Seed complete: {settings.client_id} / {settings.owner_email}")


if __name__ == "__main__":
    asyncio.run(main())
