"""Business rules for the graph; API and future CLI clients share this module."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import FocusSession, GraphEdge, GraphNode, Operation, StatusEvent, utcnow

VALID_KINDS = {"TASK", "ARTIFACT", "RESOURCE", "AGENT"}
VALID_LIFECYCLES = {"TODO", "DOING", "DONE", "CANCELLED", "SUPERSEDED"}
VALID_RELATIONS = {"contains", "depends_on", "produces", "uses", "assigned_to", "supersedes"}


def node_to_dict(node: GraphNode, progress: dict[str, Any] | None = None) -> dict[str, Any]:
    data = {
        "id": node.id, "title": node.title, "kind": node.kind, "lifecycle": node.lifecycle,
        "status_reason": node.status_reason, "parent_id": node.parent_id,
        "notion_block_id": node.notion_block_id, "wbs_level": node.wbs_level,
        "origin": node.origin, "is_proposed": node.is_proposed, "tags": node.tags or {},
        "links": node.links or [], "estimated_effort_hours": node.estimated_effort_hours,
        "observed_work_seconds": node.observed_work_seconds, "planned_start": node.planned_start,
        "planned_end": node.planned_end, "deadline": node.deadline,
        "created_at": node.created_at.isoformat(), "updated_at": node.updated_at.isoformat(),
    }
    if progress is not None:
        data["progress"] = progress
    return data


def edge_to_dict(edge: GraphEdge) -> dict[str, Any]:
    return {
        "id": edge.id, "source_id": edge.source_id, "target_id": edge.target_id,
        "relation": edge.relation, "required": edge.required, "is_proposed": edge.is_proposed,
        "metadata": edge.metadata_json or {},
    }


def _record(session: Session, operation_type: str, payload: dict, inverse_payload: dict) -> Operation:
    # Compatibility writes still participate in v2 graph-version history so a
    # v1 client cannot silently invalidate optimistic concurrency for v2.
    from .v2_service import begin_batch, record_batch_operation
    batch = begin_batch(session, f"v1:{operation_type}", actor_channel="legacy_v1")
    batch.summary = {"legacy_v1_operation": operation_type}
    return record_batch_operation(session, batch, operation_type, payload, inverse_payload)


def create_node(session: Session, payload: dict[str, Any], *, record: bool = True) -> GraphNode:
    kind = str(payload.get("kind", "TASK")).upper()
    lifecycle = str(payload.get("lifecycle", "TODO")).upper()
    if kind not in VALID_KINDS or lifecycle not in VALID_LIFECYCLES:
        raise ValueError("Invalid node kind or lifecycle")
    if lifecycle in {"CANCELLED", "SUPERSEDED"} and not str(payload.get("status_reason") or "").strip():
        raise ValueError("Cancelled or superseded nodes require a reason")
    wbs_level = payload.get("wbs_level")
    node_kind = "WORK" if kind == "TASK" else kind
    work_type = {1: "GOAL", 2: "DELIVERABLE", 3: "WORK_PACKAGE", 4: "ACTION"}.get(wbs_level, "UNCLASSIFIED")
    stage = "CLOSED" if lifecycle in {"DONE", "CANCELLED", "SUPERSEDED"} else "EXECUTION" if lifecycle == "DOING" else "PLANNING"
    estimated_hours = payload.get("estimated_effort_hours")
    node = GraphNode(
        title=str(payload["title"]).strip(), kind=kind, lifecycle=lifecycle,
        node_kind=node_kind, work_type=work_type, stage=stage, status=lifecycle,
        status_reason=payload.get("status_reason"), parent_id=payload.get("parent_id"),
        notion_block_id=payload.get("notion_block_id"), wbs_level=wbs_level,
        origin=payload.get("origin", "human"), is_proposed=bool(payload.get("is_proposed", False)),
        tags=payload.get("tags") or {}, links=payload.get("links") or [],
        estimated_effort_hours=estimated_hours,
        estimated_effort_minutes=round(float(estimated_hours) * 60) if estimated_hours is not None else None,
        estimate_source="import" if payload.get("origin") in {"notion", "legacy"} else None,
        planned_start=payload.get("planned_start"), planned_end=payload.get("planned_end"),
        deadline=payload.get("deadline"), remote_baseline=payload.get("remote_baseline") or {},
        legacy_metadata={"kind": kind, "lifecycle": lifecycle, "wbs_level": wbs_level, "links": payload.get("links") or []},
    )
    session.add(node)
    session.flush()
    if node.parent_id:
        create_edge(session, {"source_id": node.parent_id, "target_id": node.id, "relation": "contains"}, record=False)
    if record:
        _record(session, "create_node", {"node_id": node.id}, {"action": "delete_node", "node_id": node.id})
    return node


def create_edge(session: Session, payload: dict[str, Any], *, record: bool = True) -> GraphEdge:
    relation = str(payload["relation"]).lower()
    if relation not in VALID_RELATIONS:
        raise ValueError("Invalid edge relation")
    if payload["source_id"] == payload["target_id"]:
        raise ValueError("An edge cannot point to itself")
    existing = session.scalar(select(GraphEdge).where(
        GraphEdge.source_id == payload["source_id"], GraphEdge.target_id == payload["target_id"], GraphEdge.relation == relation
    ))
    if existing:
        return existing
    from .v2_service import validate_edge
    validate_edge(session, payload["source_id"], payload["target_id"], relation)
    edge = GraphEdge(
        source_id=payload["source_id"], target_id=payload["target_id"], relation=relation,
        required=bool(payload.get("required", True)), is_proposed=bool(payload.get("is_proposed", False)),
        metadata_json=payload.get("metadata") or {},
    )
    session.add(edge)
    if record:
        session.flush()
        _record(session, "create_edge", {"edge_id": edge.id}, {"action": "delete_edge", "edge_id": edge.id})
    return edge


def set_lifecycle(session: Session, node: GraphNode, lifecycle: str, *, actor: str = "user", reason: str | None = None) -> None:
    lifecycle = lifecycle.upper()
    if lifecycle not in VALID_LIFECYCLES:
        raise ValueError("Invalid lifecycle")
    if lifecycle == "DONE" and actor != "user":
        raise ValueError("Only a user may mark a node DONE")
    if lifecycle in {"CANCELLED", "SUPERSEDED"} and not str(reason or "").strip():
        raise ValueError("Cancelled or superseded nodes require a reason")
    before, before_reason = node.lifecycle, node.status_reason
    stage_before = node.stage
    if lifecycle in {"DONE", "CANCELLED", "SUPERSEDED"}:
        node.closed_from_stage, node.closed_from_status = node.stage, node.status
        node.stage = "CLOSED"
    elif lifecycle == "DOING":
        node.stage = "EXECUTION"
    elif node.stage == "CLOSED":
        node.stage = node.closed_from_stage or "PLANNING"
    node.status = lifecycle
    node.lifecycle, node.status_reason = lifecycle, reason if lifecycle in {"CANCELLED", "SUPERSEDED"} else None
    session.add(StatusEvent(node_id=node.id, before=before, after=lifecycle, stage_before=stage_before, stage_after=node.stage, reason=reason, actor=actor))
    _record(session, "set_lifecycle", {"node_id": node.id, "after": lifecycle}, {"action": "set_lifecycle", "node_id": node.id, "lifecycle": before, "reason": before_reason})


def finish_focus_session(session: Session, active: FocusSession) -> FocusSession:
    active.ended_at = utcnow()
    # SQLite returns naive datetimes even for timezone-aware columns.  Treat its
    # stored timestamps as UTC so focus duration remains stable across backends.
    started_at = active.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    seconds = max(0, int((active.ended_at - started_at).total_seconds()))
    node = session.get(GraphNode, active.node_id)
    if node:
        node.observed_work_seconds += seconds
    return active


def progress_by_node(session: Session) -> dict[str, dict[str, Any]]:
    nodes = list(session.scalars(select(GraphNode)).all())
    edges = list(session.scalars(select(GraphEdge).where(GraphEdge.relation == "contains", GraphEdge.is_proposed.is_(False))).all())
    children: dict[str, list[GraphEdge]] = defaultdict(list)
    for edge in edges:
        children[edge.source_id].append(edge)
    result: dict[str, dict[str, Any]] = {}
    for node in nodes:
        required = [session.get(GraphNode, e.target_id) for e in children.get(node.id, []) if e.required]
        required = [n for n in required if n is not None and n.lifecycle not in {"CANCELLED", "SUPERSEDED"}]
        if not required:
            result[node.id] = {"completed": 1 if node.lifecycle == "DONE" else 0, "total": 1, "ratio": 1.0 if node.lifecycle == "DONE" else 0.0, "closure_suggested": False}
            continue
        weights = [child.estimated_effort_hours if child.estimated_effort_hours and child.estimated_effort_hours > 0 else 1.0 for child in required]
        done_weight = sum(weight for child, weight in zip(required, weights) if child.lifecycle == "DONE")
        total_weight = sum(weights)
        result[node.id] = {"completed": sum(child.lifecycle == "DONE" for child in required), "total": len(required), "ratio": done_weight / total_weight if total_weight else 0.0, "closure_suggested": all(child.lifecycle == "DONE" for child in required)}
    return result


def pace_summary(session: Session) -> dict[str, Any]:
    from .v2_service import pace_projection
    pace = pace_projection(session)
    return {
        "reliable": pace["reliable"],
        "weekly_effort": pace.get("median_hours"),
        "sample_weeks": pace.get("distinct_weeks", 0),
        "weeks": pace.get("weeks", {}),
        "message": "Based on the last eight completed ISO calendar weeks; observed focus time is informational only." if pace["reliable"] else "Complete at least three estimated Actions across two separate completed weeks to establish delivery pace.",
    }


def undo_operation(session: Session, operation: Operation) -> None:
    if operation.undone_at:
        raise ValueError("Operation has already been undone")
    inverse = operation.inverse_payload or {}
    action = inverse.get("action")
    if action == "delete_node":
        node = session.get(GraphNode, inverse["node_id"])
        if node:
            session.delete(node)
    elif action == "delete_edge":
        edge = session.get(GraphEdge, inverse["edge_id"])
        if edge:
            session.delete(edge)
    elif action == "set_lifecycle":
        node = session.get(GraphNode, inverse["node_id"])
        if node:
            node.lifecycle, node.status_reason = inverse["lifecycle"], inverse.get("reason")
    elif action == "restore_node":
        node_data = inverse["node"]
        node = session.get(GraphNode, node_data["id"])
        if not node:
            raise ValueError("Node no longer exists")
        for field in {"title", "kind", "status_reason", "parent_id", "wbs_level", "tags", "links", "estimated_effort_hours", "planned_start", "planned_end", "deadline"}:
            if field in node_data:
                setattr(node, field, node_data[field])
    elif action == "restore_edge":
        edge_data = inverse["edge"]
        edge = GraphEdge(
            id=edge_data["id"], source_id=edge_data["source_id"], target_id=edge_data["target_id"],
            relation=edge_data["relation"], required=edge_data["required"], is_proposed=edge_data["is_proposed"],
            metadata_json=edge_data.get("metadata") or {},
        )
        session.add(edge)
    else:
        raise ValueError("This operation cannot be undone")
    operation.undone_at = utcnow()
