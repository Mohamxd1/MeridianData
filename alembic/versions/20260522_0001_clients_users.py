from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260522_0001"
down_revision = None  # Replace with your current latest Alembic revision ID before running.
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False, server_default="starter"),
        sa.Column("status", sa.Text(), nullable=False, server_default="onboarding"),
        sa.Column("stripe_customer_id", sa.Text(), nullable=True),
        sa.Column("stripe_subscription_id", sa.Text(), nullable=True),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("file_retention_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("monthly_file_limit", sa.Integer(), nullable=True),
        sa.Column("monthly_token_limit", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("client_id ~ '^[a-z][a-z0-9_]*$'", name="ck_clients_client_id_snake_case"),
        sa.CheckConstraint("plan IN ('free', 'starter', 'pro', 'enterprise')", name="ck_clients_plan_valid"),
        sa.CheckConstraint("status IN ('onboarding', 'active', 'suspended')", name="ck_clients_status_valid"),
        sa.CheckConstraint("file_retention_days > 0", name="ck_clients_file_retention_positive"),
        sa.CheckConstraint("monthly_file_limit IS NULL OR monthly_file_limit >= 0", name="ck_clients_monthly_file_limit_nonnegative"),
        sa.CheckConstraint("monthly_token_limit IS NULL OR monthly_token_limit >= 0", name="ck_clients_monthly_token_limit_nonnegative"),
        sa.UniqueConstraint("client_id", name="uq_clients_client_id"),
    )

    op.create_index("ix_clients_client_id", "clients", ["client_id"])
    op.create_index("ix_clients_status", "clients", ["status"])
    op.create_index("ix_clients_plan", "clients", ["plan"])
    op.create_index("ix_clients_created_at", "clients", ["created_at"])

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["client_id"], ["clients.client_id"], name="fk_users_client_id_clients", ondelete="CASCADE"),
        sa.CheckConstraint("role IN ('admin', 'client_owner', 'reviewer', 'viewer')", name="ck_users_role_valid"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_index("ix_users_client_id", "users", ["client_id"])
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_client_id_role", "users", ["client_id", "role"])
    op.create_index("ix_users_client_id_is_active", "users", ["client_id", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_users_client_id_is_active", table_name="users")
    op.drop_index("ix_users_client_id_role", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_client_id", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_clients_created_at", table_name="clients")
    op.drop_index("ix_clients_plan", table_name="clients")
    op.drop_index("ix_clients_status", table_name="clients")
    op.drop_index("ix_clients_client_id", table_name="clients")
    op.drop_table("clients")
