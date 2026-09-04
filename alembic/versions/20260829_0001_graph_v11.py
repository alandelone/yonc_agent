"""Add the lossless v1.1 graph, operation, view-state, and split contracts.

Revision ID: 20260829_0001
Revises: None
Create Date: 2026-08-29
"""

from __future__ import annotations

from alembic import op

from graph_app.schema_v2 import upgrade_connection


revision = "20260829_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_connection(op.get_bind())


def downgrade() -> None:
    # This migration deliberately preserves legacy and v1.1 data.  Rolling back
    # is performed by restoring the timestamped pre-migration SQLite backup.
    pass
