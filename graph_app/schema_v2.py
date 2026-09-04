"""Idempotent compatibility upgrader for the v1.1 graph contract.

Alembic owns production migration history.  This small guard is also run at app
startup so an older local database cannot be opened through the expanded ORM
mapping before its additive columns exist.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import Engine, inspect, text

from .database import Base


NODE_COLUMNS = {
    "node_kind": "VARCHAR(20) NOT NULL DEFAULT 'WORK'",
    "work_type": "VARCHAR(30) NOT NULL DEFAULT 'UNCLASSIFIED'",
    "stage": "VARCHAR(20) NOT NULL DEFAULT 'PLANNING'",
    "status": "VARCHAR(20) NOT NULL DEFAULT 'TODO'",
    "closed_from_stage": "VARCHAR(20)",
    "closed_from_status": "VARCHAR(20)",
    "superseded_by": "VARCHAR(36)",
    "description": "TEXT",
    "start_cue": "TEXT",
    "inputs": "JSON NOT NULL DEFAULT '[]'",
    "done_when": "TEXT",
    "required": "BOOLEAN NOT NULL DEFAULT 1",
    "estimated_effort_minutes": "INTEGER",
    "estimate_source": "VARCHAR(30)",
    "estimate_confidence": "FLOAT",
    "placement_source": "VARCHAR(30)",
    "last_user_adjusted_at": "DATETIME",
    "archived_at": "DATETIME",
    "legacy_metadata": "JSON NOT NULL DEFAULT '{}'",
}

STATUS_EVENT_COLUMNS = {
    "stage_before": "VARCHAR(20)",
    "stage_after": "VARCHAR(20)",
    "reason": "TEXT",
    "batch_id": "VARCHAR(36)",
}

OPERATION_COLUMNS = {
    "batch_id": "VARCHAR(36)",
    "sequence": "INTEGER NOT NULL DEFAULT 0",
}


def _add_missing_columns(connection, table: str, definitions: dict[str, str]) -> set[str]:
    existing = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
    added: set[str] = set()
    for name, ddl in definitions.items():
        if name not in existing:
            connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            added.add(name)
    return added


def upgrade_connection(connection) -> None:
    """Apply the additive upgrade on an existing SQLAlchemy connection."""

    Base.metadata.create_all(connection)
    tables = set(inspect(connection).get_table_names())
    added_node_columns: set[str] = set()
    if "graph_nodes" in tables:
        added_node_columns = _add_missing_columns(connection, "graph_nodes", NODE_COLUMNS)
    if "status_events" in tables:
        _add_missing_columns(connection, "status_events", STATUS_EVENT_COLUMNS)
    if "operations" in tables:
        _add_missing_columns(connection, "operations", OPERATION_COLUMNS)

    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_committed_contains_parent "
        "ON graph_edges(target_id) WHERE relation = 'contains' AND is_proposed = 0"
    )
    if added_node_columns:
        connection.execute(text("""
            UPDATE graph_nodes
           SET node_kind = CASE UPPER(kind)
                 WHEN 'TASK' THEN 'WORK'
                 WHEN 'ARTIFACT' THEN 'ARTIFACT'
                 WHEN 'RESOURCE' THEN 'RESOURCE'
                 WHEN 'AGENT' THEN 'AGENT'
                 ELSE 'WORK' END,
               work_type = CASE wbs_level
                 WHEN 1 THEN 'GOAL'
                 WHEN 2 THEN 'DELIVERABLE'
                 WHEN 3 THEN 'WORK_PACKAGE'
                 WHEN 4 THEN 'ACTION'
                 ELSE 'UNCLASSIFIED' END,
               stage = CASE UPPER(lifecycle)
                 WHEN 'DONE' THEN 'CLOSED'
                 WHEN 'CANCELLED' THEN 'CLOSED'
                 WHEN 'SUPERSEDED' THEN 'CLOSED'
                 WHEN 'DOING' THEN 'EXECUTION'
                 ELSE 'PLANNING' END,
               status = CASE UPPER(lifecycle)
                 WHEN 'DONE' THEN 'DONE'
                 WHEN 'DOING' THEN 'DOING'
                 WHEN 'CANCELLED' THEN 'CANCELLED'
                 WHEN 'SUPERSEDED' THEN 'SUPERSEDED'
                 ELSE 'TODO' END,
               estimated_effort_minutes = CASE
                 WHEN estimated_effort_hours IS NULL THEN estimated_effort_minutes
                 ELSE CAST(ROUND(estimated_effort_hours * 60.0) AS INTEGER) END,
               legacy_metadata = CASE
                 WHEN legacy_metadata IS NULL OR legacy_metadata = '{}' THEN
                   json_object('kind', kind, 'lifecycle', lifecycle, 'parent_id', parent_id,
                               'wbs_level', wbs_level, 'links', json(links))
                 ELSE legacy_metadata END
        """))
    connection.execute(text("""
        INSERT OR IGNORE INTO graph_meta (id, graph_version, schema_version, updated_at)
        VALUES (1, 1, '1.1', CURRENT_TIMESTAMP)
    """))
    legacy_links = connection.execute(text("SELECT id, links FROM graph_nodes WHERE links IS NOT NULL AND links != '[]'"))
    for node_id, raw_links in legacy_links:
        try:
            links = json.loads(raw_links) if isinstance(raw_links, str) else raw_links
        except (TypeError, json.JSONDecodeError):
            continue
        for item in links if isinstance(links, list) else []:
            if isinstance(item, dict):
                raw_uri = str(item.get("url") or item.get("uri") or "").strip()
                label = str(item.get("text") or item.get("label") or raw_uri or "Legacy resource")
            else:
                raw_uri, label = str(item).strip(), str(item).strip()
            if not raw_uri:
                continue
            uri = f"notion://{raw_uri.lstrip('/')}" if raw_uri.startswith("/") else raw_uri
            resource_type = "notion" if uri.startswith("notion://") else "link"
            connection.execute(text("""
                INSERT OR IGNORE INTO resource_references
                    (id, node_id, uri, label, role, resource_type, metadata_json, created_at)
                VALUES
                    (:id, :node_id, :uri, :label, 'reference', :resource_type, :metadata, CURRENT_TIMESTAMP)
            """), {
                "id": str(uuid.uuid4()),
                "node_id": node_id,
                "uri": uri,
                "label": label[:500],
                "resource_type": resource_type,
                "metadata": json.dumps({"legacy": True, "raw": item}, ensure_ascii=False),
            })


def ensure_v2_schema(engine: Engine) -> None:
    """Bring an existing v1 SQLite file to the additive v1.1 schema safely."""

    with engine.begin() as connection:
        upgrade_connection(connection)


def schema_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            "nodes": int(connection.execute(text("SELECT COUNT(*) FROM graph_nodes")).scalar_one()),
            "edges": int(connection.execute(text("SELECT COUNT(*) FROM graph_edges")).scalar_one()),
        }
