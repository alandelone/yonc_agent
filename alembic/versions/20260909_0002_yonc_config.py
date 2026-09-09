"""Store editable Yonc themes, modes, and task types in the graph database.

Revision ID: 20260909_0002
Revises: 20260829_0001
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "20260909_0002"
down_revision = "20260829_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "yonc_config" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "yonc_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("themes", sa.JSON(), nullable=False),
        sa.Column("modes", sa.JSON(), nullable=False),
        sa.Column("task_types", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    if "yonc_config" in inspect(op.get_bind()).get_table_names():
        op.drop_table("yonc_config")
