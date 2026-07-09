from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dataforge.db import Base


ClientPlan = Literal["free", "starter", "pro", "enterprise"]
ClientStatus = Literal["onboarding", "active", "suspended"]
UserRole = Literal["admin", "client_owner", "reviewer", "viewer"]


class Client(Base):
    __tablename__ = "clients"

    __table_args__ = (
        CheckConstraint("client_id ~ '^[a-z][a-z0-9_]*$'", name="ck_clients_client_id_snake_case"),
        CheckConstraint("plan IN ('free', 'starter', 'pro', 'enterprise')", name="ck_clients_plan_valid"),
        CheckConstraint("status IN ('onboarding', 'active', 'suspended')", name="ck_clients_status_valid"),
        CheckConstraint("file_retention_days > 0", name="ck_clients_file_retention_positive"),
        CheckConstraint("monthly_file_limit IS NULL OR monthly_file_limit >= 0", name="ck_clients_monthly_file_limit_nonnegative"),
        CheckConstraint("monthly_token_limit IS NULL OR monthly_token_limit >= 0", name="ck_clients_monthly_token_limit_nonnegative"),
        UniqueConstraint("client_id", name="uq_clients_client_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    client_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(Text, nullable=False)

    plan: Mapped[str] = mapped_column(Text, nullable=False, server_default="starter")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="onboarding")

    stripe_customer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    config_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    file_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="90")

    monthly_file_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    users: Mapped[list["User"]] = relationship(
        "User",
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class User(Base):
    __tablename__ = "users"

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'client_owner', 'reviewer', 'viewer')", name="ck_users_role_valid"),
        UniqueConstraint("email", name="uq_users_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())

    client_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("clients.client_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    email: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    client: Mapped[Client] = relationship("Client", back_populates="users")
