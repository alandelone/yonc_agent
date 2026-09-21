"""Add Hermes proposal authorization and explicit removal metadata.

Revision ID: 20260921_0003
Revises: 20260909_0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "20260921_0003"
down_revision = "20260909_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "proposal_versions" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("proposal_versions")}
        if "suggested_removals" not in columns:
            op.add_column(
                "proposal_versions",
                sa.Column("suggested_removals", sa.JSON(), nullable=False, server_default="[]"),
            )
    if "commit_authorizations" not in inspector.get_table_names():
        op.create_table(
            "commit_authorizations",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("proposal_version", sa.Integer(), nullable=False),
            sa.Column("graph_version", sa.Integer(), nullable=False),
            sa.Column("actor", sa.String(length=100), nullable=False),
            sa.Column("scope", sa.String(length=50), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["split_sessions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_commit_authorizations_session_id", "commit_authorizations", ["session_id"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "commit_authorizations" in inspector.get_table_names():
        op.drop_index("ix_commit_authorizations_session_id", table_name="commit_authorizations")
        op.drop_table("commit_authorizations")
