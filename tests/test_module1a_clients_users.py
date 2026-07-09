from __future__ import annotations

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dataforge.models_extended import Client, User
from dataforge.repositories.clients import list_users_for_client
from dataforge.seed import SeedConfigurationError, seed_demo_client


pytestmark = pytest.mark.asyncio


async def test_duplicate_client_id_rejected(db_session: AsyncSession) -> None:
    client_a = Client(client_id="duplicate_client", company_name="Duplicate Client A", plan="starter", status="active")
    client_b = Client(client_id="duplicate_client", company_name="Duplicate Client B", plan="starter", status="active")

    db_session.add(client_a)
    await db_session.commit()

    db_session.add(client_b)

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


async def test_invalid_client_id_format_rejected(db_session: AsyncSession) -> None:
    db_session.add(
        Client(
            client_id="Bad-Client",
            company_name="Bad Client",
            plan="starter",
            status="active",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


async def test_invalid_user_role_rejected(db_session: AsyncSession) -> None:
    db_session.add(
        Client(
            client_id="invalid_role_client",
            company_name="Invalid Role Client",
            plan="starter",
            status="active",
        )
    )
    await db_session.flush()

    db_session.add(
        User(
            client_id="invalid_role_client",
            email="invalid-role@example.com",
            hashed_password="hashed-password",
            role="superuser",
            is_active=True,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


async def test_same_email_across_two_clients_rejected(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Client(client_id="email_client_a", company_name="Email Client A", plan="starter", status="active"),
            Client(client_id="email_client_b", company_name="Email Client B", plan="starter", status="active"),
        ]
    )
    await db_session.flush()

    db_session.add(
        User(
            client_id="email_client_a",
            email="shared@example.com",
            hashed_password="hashed-a",
            role="reviewer",
            is_active=True,
        )
    )
    await db_session.commit()

    db_session.add(
        User(
            client_id="email_client_b",
            email="shared@example.com",
            hashed_password="hashed-b",
            role="reviewer",
            is_active=True,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


async def test_cross_client_query_isolation_confirmed(db_session: AsyncSession) -> None:
    db_session.add_all([
        Client(client_id="client_a", company_name="Client A", plan="starter", status="active"),
        Client(client_id="client_b", company_name="Client B", plan="starter", status="active"),
    ])
    await db_session.flush()

    db_session.add_all([
        User(client_id="client_a", email="reviewer-a@example.com", hashed_password="hashed-a", role="reviewer", is_active=True),
        User(client_id="client_b", email="reviewer-b@example.com", hashed_password="hashed-b", role="reviewer", is_active=True),
    ])
    await db_session.commit()

    client_a_users = await list_users_for_client(db_session, "client_a")
    client_b_users = await list_users_for_client(db_session, "client_b")

    assert len(client_a_users) == 1
    assert client_a_users[0].email == "reviewer-a@example.com"
    assert len(client_b_users) == 1
    assert client_b_users[0].email == "reviewer-b@example.com"


async def test_cascade_delete_removes_client_users(db_session: AsyncSession) -> None:
    db_session.add(Client(client_id="cascade_client", company_name="Cascade Client", plan="starter", status="active"))
    await db_session.flush()

    db_session.add(User(client_id="cascade_client", email="owner@cascade.example.com", hashed_password="hashed-password", role="client_owner", is_active=True))
    await db_session.commit()

    await db_session.execute(delete(Client).where(Client.client_id == "cascade_client"))
    await db_session.commit()

    result = await db_session.execute(select(User).where(User.client_id == "cascade_client"))
    assert result.scalars().all() == []


async def test_seed_requires_explicit_demo_password(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATAFORGE_DEMO_OWNER_PASSWORD", raising=False)

    with pytest.raises(SeedConfigurationError):
        await seed_demo_client(db_session)


async def test_seed_runs_cleanly(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATAFORGE_DEMO_CLIENT_ID", "demo_client")
    monkeypatch.setenv("DATAFORGE_DEMO_COMPANY_NAME", "Demo Client")
    monkeypatch.setenv("DATAFORGE_DEMO_OWNER_EMAIL", "admin@demo.dataforge.io")
    monkeypatch.setenv("DATAFORGE_DEMO_OWNER_PASSWORD", "DataForge2026!")

    await seed_demo_client(db_session)
    await seed_demo_client(db_session)

    client_result = await db_session.execute(select(Client).where(Client.client_id == "demo_client"))
    client = client_result.scalar_one_or_none()

    assert client is not None
    assert client.company_name == "Demo Client"
    assert client.status == "active"

    user_result = await db_session.execute(select(User).where(User.email == "admin@demo.dataforge.io"))
    users = user_result.scalars().all()

    assert len(users) == 1
    assert users[0].client_id == "demo_client"
    assert users[0].role == "client_owner"
