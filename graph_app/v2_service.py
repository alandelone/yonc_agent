"""v2 graph rules, derived projections, split sessions, and batch undo."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import (
    GraphEdge,
    GraphMeta,
    GraphNode,
    Operation,
    OperationBatch,
    ProposalVersion,
    ResourceReference,
    SplitMessage,
    SplitSession,
    StatusEvent,
    ViewState,
    new_id,
    utcnow,
)
from .split_adapter import get_split_adapter


NODE_KINDS = {"WORK", "ARTIFACT", "RESOURCE", "AGENT"}
WORK_TYPES = {"UNCLASSIFIED", "GOAL", "DELIVERABLE", "WORK_PACKAGE", "ACTION"}
STAGES = {"CAPTURED", "PLANNING", "READY", "EXECUTION", "REVIEW", "CLOSED"}
STATUSES = {"TODO", "DOING", "BLOCKED", "DONE", "CANCELLED", "SUPERSEDED"}
TERMINAL_STATUSES = {"DONE", "CANCELLED", "SUPERSEDED"}
RELATIONS = {
    "contains", "depends_on", "blocks", "related_to", "produces", "uses",
    "executed_by", "superseded_by", "assigned_to", "supersedes",
}
WBS_BY_WORK_TYPE = {"GOAL": 1, "DELIVERABLE": 2, "WORK_PACKAGE": 3, "ACTION": 4, "UNCLASSIFIED": None}
WORK_TYPE_BY_WBS = {value: key for key, value in WBS_BY_WORK_TYPE.items() if value is not None}


class V2Error(ValueError):
    def __init__(self, code: str, message_key: str, params: dict[str, Any] | None = None, *, status_code: int = 422):
        super().__init__(code)
        self.code = code
        self.message_key = message_key
        self.params = params or {}
        self.status_code = status_code

    def as_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message_key": self.message_key, "params": self.params}


def parse_date(value: str | None, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise V2Error("INVALID_DATE", "schedule.invalid_date", {"field": field, "value": value}) from exc


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def graph_meta(session: Session) -> GraphMeta:
    meta = session.get(GraphMeta, 1)
    if meta is None:
        meta = GraphMeta(id=1, graph_version=1, schema_version="1.1")
        session.add(meta)
        session.flush()
    return meta


def graph_version(session: Session) -> int:
    return graph_meta(session).graph_version


def require_graph_version(session: Session, expected: int | None) -> int:
    current = graph_version(session)
    if expected is not None and expected != current:
        raise V2Error(
            "GRAPH_VERSION_CONFLICT",
            "graph.version_conflict",
            {"expected": expected, "actual": current},
            status_code=409,
        )
    return current


def begin_batch(session: Session, source: str, *, actor_channel: str = "user_ui", expected_version: int | None = None) -> OperationBatch:
    before = require_graph_version(session, expected_version)
    meta = graph_meta(session)
    meta.graph_version = before + 1
    batch = OperationBatch(
        actor_channel=actor_channel,
        source=source,
        graph_version_before=before,
        graph_version_after=before + 1,
        summary={},
        inverse_operations=[],
    )
    session.add(batch)
    session.flush()
    return batch


def record_batch_operation(
    session: Session,
    batch: OperationBatch,
    operation_type: str,
    payload: dict[str, Any],
    inverse: dict[str, Any],
) -> Operation:
    count = len(batch.inverse_operations or [])
    operation = Operation(
        batch_id=batch.id,
        sequence=count,
        operation_type=operation_type,
        payload=payload,
        inverse_payload=inverse,
    )
    session.add(operation)
    batch.inverse_operations = [*(batch.inverse_operations or []), inverse]
    return operation


def _parent_edges(session: Session) -> list[GraphEdge]:
    return list(session.scalars(select(GraphEdge).where(GraphEdge.relation == "contains", GraphEdge.is_proposed.is_(False))).all())


def hierarchy_maps(session: Session) -> tuple[dict[str, str], dict[str, list[GraphEdge]]]:
    parents: dict[str, str] = {}
    children: dict[str, list[GraphEdge]] = defaultdict(list)
    for edge in _parent_edges(session):
        if edge.target_id in parents and parents[edge.target_id] != edge.source_id:
            raise V2Error("MULTIPLE_CONTAINS_PARENTS", "graph.multiple_parents", {"node_id": edge.target_id})
        parents[edge.target_id] = edge.source_id
        children[edge.source_id].append(edge)
    return parents, children


def _reachable(start: str, target: str, adjacency: dict[str, list[str]]) -> bool:
    stack = [start]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency.get(current, []))
    return False


def validate_edge(session: Session, source_id: str, target_id: str, relation: str, *, ignore_edge_id: str | None = None) -> None:
    relation = relation.lower()
    if relation not in RELATIONS:
        raise V2Error("INVALID_EDGE_RELATION", "graph.invalid_relation", {"relation": relation})
    if source_id == target_id:
        raise V2Error("SELF_EDGE", "graph.self_edge", {"node_id": source_id})
    if session.get(GraphNode, source_id) is None or session.get(GraphNode, target_id) is None:
        raise V2Error("NODE_NOT_FOUND", "graph.node_not_found", {"source_id": source_id, "target_id": target_id}, status_code=404)

    duplicate = session.scalar(
        select(GraphEdge).where(
            GraphEdge.source_id == source_id,
            GraphEdge.target_id == target_id,
            GraphEdge.relation == relation,
            GraphEdge.id != ignore_edge_id if ignore_edge_id else GraphEdge.id.is_not(None),
        )
    )
    if duplicate:
        raise V2Error("DUPLICATE_EDGE", "graph.duplicate_edge", {"edge_id": duplicate.id})

    relevant = list(session.scalars(select(GraphEdge).where(GraphEdge.relation == relation, GraphEdge.is_proposed.is_(False))).all())
    relevant = [edge for edge in relevant if edge.id != ignore_edge_id]
    if relation == "contains":
        incoming = [edge for edge in relevant if edge.target_id == target_id]
        if incoming:
            raise V2Error("MULTIPLE_CONTAINS_PARENTS", "graph.multiple_parents", {"node_id": target_id, "parent_id": incoming[0].source_id})
    if relation in {"contains", "depends_on", "blocks"}:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in relevant:
            adjacency[edge.source_id].append(edge.target_id)
        if _reachable(target_id, source_id, adjacency):
            raise V2Error("GRAPH_CYCLE", "graph.cycle", {"source_id": source_id, "target_id": target_id, "relation": relation})


def _legacy_kind(node_kind: str) -> str:
    return "TASK" if node_kind == "WORK" else node_kind


def _legacy_lifecycle(status: str, stage: str) -> str:
    if status in {"DONE", "CANCELLED", "SUPERSEDED"}:
        return status
    if status == "DOING" or stage == "EXECUTION":
        return "DOING"
    return "TODO"


def validate_node_payload(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    values = dict(payload)
    node_kind = str(values.get("node_kind", "WORK")).upper()
    work_type = str(values.get("work_type", "UNCLASSIFIED")).upper()
    stage = str(values.get("stage", "PLANNING")).upper()
    status = str(values.get("status", "TODO")).upper()
    if node_kind not in NODE_KINDS:
        raise V2Error("INVALID_NODE_KIND", "node.invalid_kind", {"node_kind": node_kind})
    if work_type not in WORK_TYPES or (node_kind != "WORK" and work_type != "UNCLASSIFIED"):
        raise V2Error("INVALID_WORK_TYPE", "node.invalid_work_type", {"work_type": work_type})
    if stage not in STAGES or status not in STATUSES:
        raise V2Error("INVALID_STATE", "node.invalid_state", {"stage": stage, "status": status})
    if status in TERMINAL_STATUSES and stage != "CLOSED":
        raise V2Error("TERMINAL_STAGE_REQUIRED", "node.terminal_requires_closed", {"status": status})
    if status in {"CANCELLED", "SUPERSEDED"} and not str(values.get("status_reason") or "").strip():
        raise V2Error("TERMINAL_REASON_REQUIRED", "node.terminal_reason_required", {"status": status})
    if status == "SUPERSEDED" and values.get("superseded_by") == values.get("id"):
        raise V2Error("INVALID_REPLACEMENT", "node.invalid_replacement", {})
    effort = values.get("estimated_effort_minutes")
    if effort is not None and int(effort) < 0:
        raise V2Error("INVALID_ESTIMATE", "node.invalid_estimate", {"estimated_effort_minutes": effort})
    for field in ("planned_start", "planned_end", "deadline"):
        parse_date(values.get(field), field)
    values.update(node_kind=node_kind, work_type=work_type, stage=stage, status=status)
    return values


def _node_snapshot(node: GraphNode) -> dict[str, Any]:
    fields = (
        "title", "node_kind", "work_type", "stage", "status", "status_reason", "closed_from_stage",
        "closed_from_status", "superseded_by", "description", "start_cue", "inputs", "done_when",
        "required", "tags", "estimated_effort_minutes", "estimate_source", "estimate_confidence",
        "planned_start", "planned_end", "deadline", "placement_source", "last_user_adjusted_at",
        "archived_at", "kind", "lifecycle", "wbs_level", "parent_id", "links", "legacy_metadata",
    )
    result = {field: getattr(node, field) for field in fields}
    if isinstance(result.get("last_user_adjusted_at"), datetime):
        result["last_user_adjusted_at"] = result["last_user_adjusted_at"].isoformat()
    if isinstance(result.get("archived_at"), datetime):
        result["archived_at"] = result["archived_at"].isoformat()
    return result


def create_node_v2(
    session: Session,
    payload: dict[str, Any],
    *,
    expected_version: int | None = None,
    actor_channel: str = "user_ui",
    batch: OperationBatch | None = None,
) -> tuple[GraphNode, OperationBatch]:
    values = validate_node_payload(payload)
    title = str(values.get("title") or "").strip()
    if not title:
        raise V2Error("TITLE_REQUIRED", "node.title_required", {})
    parent_id = values.pop("parent_id", None)
    if batch is None:
        batch = begin_batch(session, "create_node", actor_channel=actor_channel, expected_version=expected_version)
    elif expected_version is not None:
        require_graph_version(session, expected_version)

    node = GraphNode(
        id=values.get("id") or new_id(),
        title=title,
        node_kind=values["node_kind"],
        work_type=values["work_type"],
        stage=values["stage"],
        status=values["status"],
        status_reason=values.get("status_reason"),
        superseded_by=values.get("superseded_by"),
        description=values.get("description"),
        start_cue=values.get("start_cue"),
        inputs=values.get("inputs") or [],
        done_when=values.get("done_when"),
        required=bool(values.get("required", True)),
        tags=values.get("tags") or {},
        estimated_effort_minutes=values.get("estimated_effort_minutes"),
        estimated_effort_hours=(values.get("estimated_effort_minutes") / 60.0) if values.get("estimated_effort_minutes") is not None else None,
        estimate_source=values.get("estimate_source"),
        estimate_confidence=values.get("estimate_confidence"),
        planned_start=values.get("planned_start"),
        planned_end=values.get("planned_end"),
        deadline=values.get("deadline"),
        placement_source=values.get("placement_source"),
        notion_block_id=values.get("notion_block_id"),
        origin=values.get("origin", "human"),
        legacy_metadata=values.get("legacy_metadata") or {},
        kind=_legacy_kind(values["node_kind"]),
        lifecycle=_legacy_lifecycle(values["status"], values["stage"]),
        wbs_level=WBS_BY_WORK_TYPE[values["work_type"]],
        is_proposed=False,
    )
    session.add(node)
    session.flush()
    record_batch_operation(session, batch, "create_node", {"node_id": node.id}, {"action": "delete_node", "node_id": node.id})
    if parent_id:
        create_edge_v2(session, {"source_id": parent_id, "target_id": node.id, "relation": "contains", "required": values.get("required", True)}, batch=batch)
        node.parent_id = parent_id
    batch.summary = {**(batch.summary or {}), "created_nodes": [*(batch.summary or {}).get("created_nodes", []), node.id]}
    return node, batch


def create_edge_v2(
    session: Session,
    payload: dict[str, Any],
    *,
    expected_version: int | None = None,
    actor_channel: str = "user_ui",
    batch: OperationBatch | None = None,
) -> tuple[GraphEdge, OperationBatch]:
    source_id, target_id = str(payload["source_id"]), str(payload["target_id"])
    relation = str(payload["relation"]).lower()
    validate_edge(session, source_id, target_id, relation)
    if batch is None:
        batch = begin_batch(session, "create_edge", actor_channel=actor_channel, expected_version=expected_version)
    edge = GraphEdge(
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        required=bool(payload.get("required", True)),
        is_proposed=False,
        metadata_json=payload.get("metadata") or {},
    )
    session.add(edge)
    session.flush()
    record_batch_operation(session, batch, "create_edge", {"edge_id": edge.id}, {"action": "delete_edge", "edge_id": edge.id})
    if relation == "contains":
        child = session.get(GraphNode, target_id)
        if child:
            child.parent_id = source_id
    batch.summary = {**(batch.summary or {}), "created_edges": [*(batch.summary or {}).get("created_edges", []), edge.id]}
    return edge, batch


def reparent_node(session: Session, node: GraphNode, parent_id: str | None, *, expected_version: int | None = None) -> OperationBatch:
    parents, _ = hierarchy_maps(session)
    old_parent = parents.get(node.id)
    if parent_id == old_parent:
        raise V2Error("NO_CHANGE", "graph.no_change", {"node_id": node.id})
    if parent_id:
        validate_edge(session, parent_id, node.id, "contains", ignore_edge_id=session.scalar(select(GraphEdge.id).where(GraphEdge.target_id == node.id, GraphEdge.relation == "contains")))
        _validate_schedule_values(session, node, node.planned_start, node.planned_end, proposed_parent_id=parent_id)
    batch = begin_batch(session, "reparent_node", expected_version=expected_version)
    old_edge = session.scalar(select(GraphEdge).where(GraphEdge.target_id == node.id, GraphEdge.relation == "contains", GraphEdge.is_proposed.is_(False)))
    if old_edge:
        session.delete(old_edge)
        # The database enforces the canonical one-parent rule with a partial
        # unique index. Flush the removal before inserting the replacement so
        # SQLAlchemy cannot reorder both writes into a transient conflict.
        session.flush()
    new_edge_id = None
    if parent_id:
        new_edge = GraphEdge(source_id=parent_id, target_id=node.id, relation="contains", required=node.required, is_proposed=False, metadata_json={})
        session.add(new_edge)
        session.flush()
        new_edge_id = new_edge.id
    node.parent_id = parent_id
    record_batch_operation(
        session,
        batch,
        "reparent_node",
        {"node_id": node.id, "parent_id": parent_id, "edge_id": new_edge_id},
        {"action": "restore_parent", "node_id": node.id, "parent_id": old_parent},
    )
    batch.summary = {"reparented_node": node.id, "from": old_parent, "to": parent_id}
    return batch


def update_node_v2(session: Session, node: GraphNode, payload: dict[str, Any], *, expected_version: int | None = None) -> OperationBatch:
    disallowed = {"id", "parent_id", "status", "stage", "node_kind"}
    if disallowed.intersection(payload):
        raise V2Error("SPECIAL_ENDPOINT_REQUIRED", "node.special_endpoint_required", {"fields": sorted(disallowed.intersection(payload))})
    before = _node_snapshot(node)
    candidate = {**before, **payload}
    candidate["node_kind"] = node.node_kind
    candidate["stage"] = node.stage
    candidate["status"] = node.status
    values = validate_node_payload(candidate, partial=True)
    if "work_type" in payload:
        node.work_type = values["work_type"]
        node.wbs_level = WBS_BY_WORK_TYPE[node.work_type]
    for field in (
        "title", "description", "start_cue", "inputs", "done_when", "required", "tags",
        "estimated_effort_minutes", "estimate_source", "estimate_confidence", "deadline",
    ):
        if field in payload:
            setattr(node, field, values.get(field))
    if "estimated_effort_minutes" in payload:
        node.estimated_effort_hours = (node.estimated_effort_minutes / 60.0) if node.estimated_effort_minutes is not None else None
    batch = begin_batch(session, "update_node", expected_version=expected_version)
    record_batch_operation(session, batch, "update_node", {"node_id": node.id, "fields": list(payload)}, {"action": "restore_node", "node_id": node.id, "snapshot": before})
    batch.summary = {"updated_node": node.id, "fields": list(payload)}
    return batch


def transition_node(
    session: Session,
    node: GraphNode,
    action: str,
    *,
    reason: str | None = None,
    superseded_by: str | None = None,
    expected_version: int | None = None,
    actor_channel: str = "user_ui",
) -> OperationBatch:
    action = action.lower()
    before = {"stage": node.stage, "status": node.status, "reason": node.status_reason, "closed_from_stage": node.closed_from_stage, "closed_from_status": node.closed_from_status, "superseded_by": node.superseded_by}
    if action == "start":
        node.stage, node.status, node.status_reason = "EXECUTION", "DOING", None
    elif action == "block":
        node.status, node.status_reason = "BLOCKED", reason
    elif action == "unblock":
        node.status, node.status_reason = ("DOING" if node.stage == "EXECUTION" else "TODO"), None
    elif action == "submit_review":
        node.stage, node.status, node.status_reason = "REVIEW", "TODO", None
    elif action in {"done", "cancel", "supersede"}:
        if action == "done" and actor_channel != "user_ui":
            raise V2Error("USER_ONLY_DONE", "node.user_only_done", {}, status_code=403)
        target_status = {"done": "DONE", "cancel": "CANCELLED", "supersede": "SUPERSEDED"}[action]
        if target_status in {"CANCELLED", "SUPERSEDED"} and not str(reason or "").strip():
            raise V2Error("TERMINAL_REASON_REQUIRED", "node.terminal_reason_required", {"status": target_status})
        if superseded_by and session.get(GraphNode, superseded_by) is None:
            raise V2Error("REPLACEMENT_NOT_FOUND", "node.replacement_not_found", {"node_id": superseded_by}, status_code=404)
        node.closed_from_stage, node.closed_from_status = node.stage, node.status
        node.stage, node.status = "CLOSED", target_status
        node.status_reason = reason if target_status != "DONE" else None
        node.superseded_by = superseded_by if target_status == "SUPERSEDED" else None
    elif action in {"reopen", "undo_close"}:
        if node.status not in TERMINAL_STATUSES:
            raise V2Error("NOT_CLOSED", "node.not_closed", {"node_id": node.id})
        node.stage = node.closed_from_stage or "PLANNING"
        node.status = node.closed_from_status or "TODO"
        node.status_reason = None
        node.superseded_by = None
        node.closed_from_stage = None
        node.closed_from_status = None
    elif action == "capture":
        node.stage, node.status = "CAPTURED", "TODO"
    elif action == "ready":
        if node.work_type == "ACTION" and (not node.start_cue or not node.done_when):
            raise V2Error("ACTIONABILITY_FAILED", "split.actionability_failed", {"node_id": node.id})
        node.stage, node.status = "READY", "TODO"
    else:
        raise V2Error("INVALID_TRANSITION", "node.invalid_transition", {"action": action})

    node.lifecycle = _legacy_lifecycle(node.status, node.stage)
    batch = begin_batch(session, f"transition:{action}", actor_channel=actor_channel, expected_version=expected_version)
    session.add(StatusEvent(
        node_id=node.id,
        before=before["status"],
        after=node.status,
        stage_before=before["stage"],
        stage_after=node.stage,
        reason=reason,
        actor=actor_channel,
        batch_id=batch.id,
    ))
    record_batch_operation(session, batch, "transition", {"node_id": node.id, "action": action, "stage": node.stage, "status": node.status}, {"action": "restore_state", "node_id": node.id, **before})
    batch.summary = {"transitioned_node": node.id, "action": action, "stage": node.stage, "status": node.status}
    return batch


def _ancestor_ids(session: Session, node_id: str, proposed_parent_id: str | None = None) -> list[str]:
    parents, _ = hierarchy_maps(session)
    if proposed_parent_id is not None:
        parents[node_id] = proposed_parent_id
    result: list[str] = []
    current = parents.get(node_id)
    seen: set[str] = set()
    while current and current not in seen:
        result.append(current)
        seen.add(current)
        current = parents.get(current)
    return result


def _validate_schedule_values(
    session: Session,
    node: GraphNode,
    planned_start: str | None,
    planned_end: str | None,
    *,
    proposed_parent_id: str | None = None,
) -> list[dict[str, Any]]:
    start, end = parse_date(planned_start, "planned_start"), parse_date(planned_end, "planned_end")
    violations: list[dict[str, Any]] = []
    if start and end and end < start:
        violations.append({"code": "END_BEFORE_START", "message_key": "schedule.end_before_start", "params": {"node_id": node.id}})
    effective_end = end or start
    own_deadline = parse_date(node.deadline, "deadline")
    if effective_end and own_deadline and effective_end > own_deadline:
        violations.append({"code": "DEADLINE_CONFLICT", "message_key": "schedule.deadline_conflict", "params": {"node_id": node.id, "deadline": node.deadline}})
    for ancestor_id in _ancestor_ids(session, node.id, proposed_parent_id):
        ancestor = session.get(GraphNode, ancestor_id)
        deadline = parse_date(ancestor.deadline, "deadline") if ancestor else None
        if effective_end and deadline and effective_end > deadline:
            violations.append({"code": "ANCESTOR_DEADLINE_CONFLICT", "message_key": "schedule.ancestor_deadline_conflict", "params": {"node_id": node.id, "ancestor_id": ancestor_id, "deadline": ancestor.deadline}})
    dependencies = list(session.scalars(select(GraphEdge).where(GraphEdge.source_id == node.id, GraphEdge.relation == "depends_on", GraphEdge.is_proposed.is_(False))).all())
    for edge in dependencies:
        dependency = session.get(GraphNode, edge.target_id)
        dependency_end = parse_date(dependency.planned_end or dependency.planned_start, "planned_end") if dependency else None
        if start and dependency_end and start < dependency_end:
            violations.append({"code": "DEPENDENCY_ORDER_CONFLICT", "message_key": "schedule.dependency_conflict", "params": {"node_id": node.id, "blocking_node_id": edge.target_id, "blocking_end": dependency_end.isoformat()}})
    return violations


def preview_schedule(session: Session, node: GraphNode, planned_start: str | None, planned_end: str | None) -> dict[str, Any]:
    violations = _validate_schedule_values(session, node, planned_start, planned_end)
    return {"valid": not violations, "node_id": node.id, "planned_start": planned_start, "planned_end": planned_end, "violations": violations}


def apply_schedule(
    session: Session,
    node: GraphNode,
    planned_start: str | None,
    planned_end: str | None,
    *,
    expected_version: int | None = None,
    placement_source: str = "user",
) -> OperationBatch:
    preview = preview_schedule(session, node, planned_start, planned_end)
    if not preview["valid"]:
        first = preview["violations"][0]
        raise V2Error(first["code"], first["message_key"], first["params"])
    before = {"planned_start": node.planned_start, "planned_end": node.planned_end, "placement_source": node.placement_source, "last_user_adjusted_at": _iso(node.last_user_adjusted_at)}
    node.planned_start, node.planned_end = planned_start, planned_end
    node.placement_source = placement_source
    if placement_source == "user":
        node.last_user_adjusted_at = utcnow()
    batch = begin_batch(session, "schedule", expected_version=expected_version)
    record_batch_operation(session, batch, "schedule", {"node_id": node.id, "planned_start": planned_start, "planned_end": planned_end}, {"action": "restore_schedule", "node_id": node.id, **before})
    batch.summary = {"scheduled_node": node.id, "planned_start": planned_start, "planned_end": planned_end}
    return batch


def _required_actions_for(node_id: str, nodes: dict[str, GraphNode], children: dict[str, list[GraphEdge]]) -> list[GraphNode]:
    result: list[GraphNode] = []
    stack: list[tuple[str, bool]] = [(node_id, True)]
    seen: set[str] = set()
    while stack:
        current_id, path_required = stack.pop()
        if current_id in seen:
            continue
        seen.add(current_id)
        current = nodes.get(current_id)
        if current is None or current.status in {"CANCELLED", "SUPERSEDED"}:
            continue
        outgoing = [edge for edge in children.get(current_id, []) if edge.required]
        if current.work_type == "ACTION" and path_required and current.required:
            result.append(current)
            continue
        for edge in outgoing:
            stack.append((edge.target_id, path_required and edge.required))
    return result


def progress_projection(session: Session) -> dict[str, dict[str, Any]]:
    node_list = list(session.scalars(select(GraphNode).where(GraphNode.is_proposed.is_(False))).all())
    nodes = {node.id: node for node in node_list}
    _, children = hierarchy_maps(session)
    result: dict[str, dict[str, Any]] = {}
    for node in node_list:
        actions = _required_actions_for(node.id, nodes, children)
        if not actions:
            ratio = 1.0 if node.status == "DONE" else 0.0
            result[node.id] = {"completed": int(node.status == "DONE"), "total": 1, "ratio": ratio, "weight_minutes": 0, "completed_weight_minutes": 0}
            continue
        weights = [action.estimated_effort_minutes or (int(action.estimated_effort_hours * 60) if action.estimated_effort_hours else 60) for action in actions]
        completed_weight = sum(weight for action, weight in zip(actions, weights) if action.status == "DONE")
        total_weight = sum(weights)
        result[node.id] = {
            "completed": sum(action.status == "DONE" for action in actions),
            "total": len(actions),
            "ratio": completed_weight / total_weight if total_weight else 0.0,
            "weight_minutes": total_weight,
            "completed_weight_minutes": completed_weight,
        }
    return result


def _completed_week_starts(today: date | None = None) -> list[date]:
    current = today or date.today()
    current_monday = current - timedelta(days=current.weekday())
    return [current_monday - timedelta(weeks=offset) for offset in range(8, 0, -1)]


def pace_projection(session: Session, *, today: date | None = None) -> dict[str, Any]:
    weeks = _completed_week_starts(today)
    start, end = weeks[0], weeks[-1] + timedelta(days=6)
    events = list(session.scalars(select(StatusEvent).order_by(StatusEvent.created_at)).all())
    latest_done: dict[str, StatusEvent] = {}
    latest_event: dict[str, StatusEvent] = {}
    for event in events:
        latest_event[event.node_id] = event
        if event.after == "DONE":
            latest_done[event.node_id] = event
    buckets = {monday.isoformat(): 0.0 for monday in weeks}
    completion_count = 0
    distinct_weeks: set[str] = set()
    for node_id, event in latest_done.items():
        node = session.get(GraphNode, node_id)
        if not node or node.status != "DONE" or node.work_type != "ACTION" or latest_event.get(node_id) is not event:
            continue
        event_date = event.created_at.date()
        if not (start <= event_date <= end):
            continue
        monday = event_date - timedelta(days=event_date.weekday())
        key = monday.isoformat()
        effort_hours = (node.estimated_effort_minutes / 60.0) if node.estimated_effort_minutes is not None else (node.estimated_effort_hours or 1.0)
        buckets[key] += effort_hours
        completion_count += 1
        distinct_weeks.add(key)
    values = list(buckets.values())
    nonzero = [value for value in values if value > 0]
    # Empty weeks remain visible in the eight-week series but must not collapse
    # the observed delivery-rate distribution to zero.  Reliability is based on
    # at least three valid completions across two completed ISO weeks.
    reliable = completion_count >= 3 and len(distinct_weeks) >= 2 and bool(nonzero)
    if not reliable:
        return {"confidence": "low", "reliable": False, "code": "INSUFFICIENT_HISTORY", "weeks": buckets, "completion_count": completion_count, "distinct_weeks": len(distinct_weeks), "median_hours": None, "p25_hours": None, "p75_hours": None}
    ordered = sorted(nonzero)
    def percentile(fraction: float) -> float:
        index = (len(ordered) - 1) * fraction
        low, high = math.floor(index), math.ceil(index)
        return ordered[low] if low == high else ordered[low] + (ordered[high] - ordered[low]) * (index - low)
    return {
        "confidence": "medium" if completion_count < 8 else "high",
        "reliable": True,
        "weeks": buckets,
        "completion_count": completion_count,
        "distinct_weeks": len(distinct_weeks),
        "median_hours": statistics.median(nonzero),
        "p25_hours": percentile(0.25),
        "p75_hours": percentile(0.75),
    }


def forecast_for_scope(session: Session, node_id: str, progress: dict[str, dict[str, Any]] | None = None, pace: dict[str, Any] | None = None, *, today: date | None = None) -> dict[str, Any]:
    node = session.get(GraphNode, node_id)
    if node is None:
        raise V2Error("NODE_NOT_FOUND", "graph.node_not_found", {"node_id": node_id}, status_code=404)
    progress = progress or progress_projection(session)
    pace = pace or pace_projection(session, today=today)
    summary = progress[node_id]
    remaining_hours = max(0.0, (summary["weight_minutes"] - summary["completed_weight_minutes"]) / 60.0)
    base = today or date.today()
    if remaining_hours == 0:
        finish = base.isoformat()
        return {"node_id": node_id, "confidence": "high", "remaining_effort_hours": 0, "finish_range": {"earliest": finish, "likely": finish, "latest": finish}, "deadline": node.deadline, "gap_days": (parse_date(node.deadline, "deadline") - base).days if node.deadline else None}
    if not pace.get("reliable"):
        return {"node_id": node_id, "confidence": "low", "code": "INSUFFICIENT_HISTORY", "remaining_effort_hours": remaining_hours, "finish_range": None, "deadline": node.deadline, "gap_days": None}
    slow = max(float(pace["p25_hours"]), 0.01)
    typical = max(float(pace["median_hours"]), 0.01)
    fast = max(float(pace["p75_hours"]), 0.01)
    finish_range = {
        "earliest": (base + timedelta(days=math.ceil(remaining_hours / fast * 7))).isoformat(),
        "likely": (base + timedelta(days=math.ceil(remaining_hours / typical * 7))).isoformat(),
        "latest": (base + timedelta(days=math.ceil(remaining_hours / slow * 7))).isoformat(),
    }
    deadline = parse_date(node.deadline, "deadline")
    gap = (deadline - date.fromisoformat(finish_range["likely"])).days if deadline else None
    return {"node_id": node_id, "confidence": pace["confidence"], "remaining_effort_hours": remaining_hours, "finish_range": finish_range, "deadline": node.deadline, "gap_days": gap}


def pressure_for_node(session: Session, node: GraphNode, forecast: dict[str, Any]) -> dict[str, Any]:
    factors: list[dict[str, Any]] = []
    score = 0.0
    today = date.today()
    deadline = parse_date(node.deadline, "deadline")
    if deadline:
        slack = (deadline - today).days
        if slack < 0:
            score += 0.55
            factors.append({"factor": "overdue", "days": abs(slack)})
        elif slack <= 14:
            score += 0.2 * (1 - slack / 15)
            factors.append({"factor": "deadline_slack", "days": slack})
    if forecast.get("finish_range") and deadline:
        latest = date.fromisoformat(forecast["finish_range"]["latest"])
        if latest > deadline:
            score += min(0.35, (latest - deadline).days / 30)
            factors.append({"factor": "forecast_after_deadline", "days": (latest - deadline).days})
    elif forecast.get("code") == "INSUFFICIENT_HISTORY" and forecast.get("remaining_effort_hours", 0) > 0:
        score += 0.1
        factors.append({"factor": "low_forecast_confidence"})
    dependencies = list(session.scalars(select(GraphEdge).where(GraphEdge.source_id == node.id, GraphEdge.relation == "depends_on")).all())
    blocked = [edge.target_id for edge in dependencies if (session.get(GraphNode, edge.target_id) and session.get(GraphNode, edge.target_id).status != "DONE")]
    if blocked:
        score += min(0.3, 0.1 * len(blocked))
        factors.append({"factor": "open_dependencies", "node_ids": blocked})
    score = round(min(1.0, score), 3)
    level = "high" if score >= 0.66 else "medium" if score >= 0.33 else "low"
    return {"score": score, "level": level, "factors": factors}


def graph_health(session: Session) -> dict[str, Any]:
    nodes = {node.id: node for node in session.scalars(select(GraphNode).where(GraphNode.is_proposed.is_(False))).all()}
    edges = list(session.scalars(select(GraphEdge).where(GraphEdge.is_proposed.is_(False))).all())
    warnings: list[dict[str, Any]] = []
    incoming: dict[str, list[str]] = defaultdict(list)
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.relation == "contains":
            incoming[edge.target_id].append(edge.source_id)
            adjacency[edge.source_id].append(edge.target_id)
    for node_id, parents in incoming.items():
        if len(parents) > 1:
            warnings.append({"code": "MULTIPLE_CONTAINS_PARENTS", "node_id": node_id, "parent_ids": parents})
    for node in nodes.values():
        if node.work_type == "ACTION" and node.status not in TERMINAL_STATUSES and (not node.start_cue or not node.done_when):
            warnings.append({"code": "ACTIONABILITY_INCOMPLETE", "node_id": node.id})
        if node.planned_end:
            violations = _validate_schedule_values(session, node, node.planned_start, node.planned_end)
            warnings.extend({**item, "node_id": node.id} for item in violations)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> str | None:
        if node_id in visiting:
            return node_id
        if node_id in visited:
            return None
        visiting.add(node_id)
        for child_id in adjacency.get(node_id, []):
            cycle_node = visit(child_id)
            if cycle_node:
                return cycle_node
        visiting.remove(node_id)
        visited.add(node_id)
        return None

    for node_id in nodes:
        cycle_node = visit(node_id)
        if cycle_node:
            warnings.append({"code": "CONTAINS_CYCLE", "node_id": cycle_node})
            break
    by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for warning in warnings:
        if warning.get("node_id"):
            by_node[str(warning["node_id"])].append(warning)
    return {"ok": not warnings, "warning_count": len(warnings), "warnings": warnings, "by_node": by_node}


def serialize_edge(edge: GraphEdge) -> dict[str, Any]:
    return {"id": edge.id, "source_id": edge.source_id, "target_id": edge.target_id, "relation": edge.relation, "required": edge.required, "metadata": edge.metadata_json or {}}


def serialize_node(
    session: Session,
    node: GraphNode,
    *,
    parent_id: str | None = None,
    progress: dict[str, Any] | None = None,
    health: list[dict[str, Any]] | None = None,
    forecast: dict[str, Any] | None = None,
    pressure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if parent_id is None:
        parent_edge = session.scalar(select(GraphEdge).where(GraphEdge.target_id == node.id, GraphEdge.relation == "contains", GraphEdge.is_proposed.is_(False)))
        parent_id = parent_edge.source_id if parent_edge else None
    resource_count = len(list(session.scalars(select(ResourceReference.id).where(ResourceReference.node_id == node.id)).all()))
    return {
        "id": node.id,
        "title": node.title,
        "node_kind": node.node_kind,
        "work_type": node.work_type,
        "stage": node.stage,
        "status": node.status,
        "status_reason": node.status_reason,
        "parent_id": parent_id,
        "wbs_level": WBS_BY_WORK_TYPE.get(node.work_type),
        "description": node.description,
        "start_cue": node.start_cue,
        "inputs": node.inputs or [],
        "done_when": node.done_when,
        "required": node.required,
        "tags": node.tags or {},
        "estimated_effort_minutes": node.estimated_effort_minutes,
        "estimate_source": node.estimate_source,
        "estimate_confidence": node.estimate_confidence,
        "planned_start": node.planned_start,
        "planned_end": node.planned_end,
        "deadline": node.deadline,
        "placement_source": node.placement_source,
        "notion_block_id": node.notion_block_id,
        "resource_count": resource_count,
        "archived": node.archived_at is not None,
        "created_at": _iso(node.created_at),
        "updated_at": _iso(node.updated_at),
        "progress": progress,
        "health": health or [],
        "forecast": forecast,
        "pressure": pressure,
    }


def graph_projection(session: Session, scope_node_id: str | None = None) -> dict[str, Any]:
    node_list = list(session.scalars(select(GraphNode).where(GraphNode.is_proposed.is_(False), GraphNode.archived_at.is_(None)).order_by(GraphNode.created_at)).all())
    edges = list(session.scalars(select(GraphEdge).where(GraphEdge.is_proposed.is_(False))).all())
    parents, children = hierarchy_maps(session)
    if scope_node_id:
        allowed: set[str] = set()
        stack = [scope_node_id]
        while stack:
            current = stack.pop()
            if current in allowed:
                continue
            allowed.add(current)
            stack.extend(edge.target_id for edge in children.get(current, []))
        node_list = [node for node in node_list if node.id in allowed]
        edges = [edge for edge in edges if edge.source_id in allowed and edge.target_id in allowed]
    progress = progress_projection(session)
    pace = pace_projection(session)
    health = graph_health(session)
    serialized = []
    for node in node_list:
        forecast = forecast_for_scope(session, node.id, progress, pace)
        serialized.append(serialize_node(session, node, parent_id=parents.get(node.id), progress=progress.get(node.id), health=health["by_node"].get(node.id, []), forecast=forecast, pressure=pressure_for_node(session, node, forecast)))
    return {"graph_version": graph_version(session), "schema_version": "1.1", "scope_node_id": scope_node_id, "nodes": serialized, "edges": [serialize_edge(edge) for edge in edges], "pace": pace, "health": {key: value for key, value in health.items() if key != "by_node"}}


def timeline_projection(session: Session, start: str | None = None, end: str | None = None, scope_node_id: str | None = None) -> dict[str, Any]:
    start_date = parse_date(start, "start") or (date.today() - timedelta(days=date.today().weekday()))
    end_date = parse_date(end, "end") or (start_date + timedelta(weeks=12) - timedelta(days=1))
    if end_date < start_date or (end_date - start_date).days > 5000:
        raise V2Error("INVALID_RANGE", "timeline.invalid_range", {"start": start_date.isoformat(), "end": end_date.isoformat()})
    graph = graph_projection(session, scope_node_id)
    scheduled = [node for node in graph["nodes"] if node["planned_start"]]
    placements: list[dict[str, Any]] = []
    allocations: dict[str, list[str]] = defaultdict(list)
    deadlines: dict[str, list[str]] = defaultdict(list)
    for node in scheduled:
        node_start = parse_date(node["planned_start"], "planned_start")
        node_end = parse_date(node["planned_end"] or node["planned_start"], "planned_end")
        if not node_start or not node_end or node_end < start_date or node_start > end_date:
            continue
        placements.append({"node_id": node["id"], "title": node["title"], "start": node_start.isoformat(), "end": node_end.isoformat(), "work_type": node["work_type"], "status": node["status"]})
        cursor = max(node_start, start_date)
        while cursor <= min(node_end, end_date):
            allocations[cursor.isoformat()].append(node["id"])
            cursor += timedelta(days=1)
    for node in graph["nodes"]:
        if node["deadline"] and start_date <= date.fromisoformat(node["deadline"]) <= end_date:
            deadlines[node["deadline"]].append(node["id"])
    cells = []
    warnings = []
    cursor = start_date
    while cursor <= end_date:
        ids = allocations.get(cursor.isoformat(), [])
        if len(ids) > 2:
            warnings.append({"code": "CAPACITY_OVERLAP", "date": cursor.isoformat(), "count": len(ids), "node_ids": ids})
        iso_calendar = cursor.isocalendar()
        cells.append({"date": cursor.isoformat(), "iso_year": iso_calendar.year, "iso_week": iso_calendar.week, "month": cursor.strftime("%b"), "weekday": cursor.strftime("%a"), "allocations": ids, "overlap_count": len(ids), "overflow_count": max(0, len(ids) - 2), "today": cursor == date.today(), "deadline_node_ids": deadlines.get(cursor.isoformat(), [])})
        cursor += timedelta(days=1)
    return {"graph_version": graph["graph_version"], "start": start_date.isoformat(), "end": end_date.isoformat(), "cells": cells, "placements": placements, "forecasts": [{"node_id": node["id"], **(node["forecast"] or {})} for node in graph["nodes"] if node["work_type"] in {"GOAL", "DELIVERABLE"}], "warnings": warnings, "pace": graph["pace"]}


def suggest_schedule_range(session: Session, node: GraphNode, planned_start: str) -> dict[str, Any]:
    start_date = parse_date(planned_start, "planned_start")
    if start_date is None:
        raise V2Error("START_REQUIRED", "schedule.start_required", {})
    progress = progress_projection(session)
    pace = pace_projection(session)
    forecast = forecast_for_scope(session, node.id, progress, pace, today=start_date)
    if forecast.get("finish_range"):
        end_date = date.fromisoformat(forecast["finish_range"]["likely"])
    else:
        remaining_hours = float(forecast.get("remaining_effort_hours") or ((node.estimated_effort_minutes or 60) / 60.0))
        end_date = start_date + timedelta(days=max(0, min(27, math.ceil(remaining_hours / 2.0) - 1)))
    return {"planned_start": start_date.isoformat(), "planned_end": end_date.isoformat(), "forecast": forecast}


def get_view_state(session: Session, view: str, scope_node_id: str | None, client_key: str = "default") -> ViewState:
    view = view.lower()
    if view not in {"canvas", "timeline"}:
        raise V2Error("INVALID_VIEW", "view.invalid", {"view": view})
    state = session.scalar(select(ViewState).where(ViewState.view == view, ViewState.scope_node_id == scope_node_id, ViewState.client_key == client_key))
    if state is None:
        state = ViewState(view=view, scope_node_id=scope_node_id, client_key=client_key)
        session.add(state)
        session.flush()
    return state


def serialize_view_state(state: ViewState) -> dict[str, Any]:
    return {"view": state.view, "scope_node_id": state.scope_node_id, "client_key": state.client_key, "expanded_node_ids": state.expanded_node_ids or [], "selected_node_id": state.selected_node_id, "filters": state.filters or {}, "zoom": state.zoom, "pan": {"x": state.pan_x, "y": state.pan_y}, "vertical_layout": state.vertical_layout or {}, "updated_at": _iso(state.updated_at)}


def update_view_state(session: Session, state: ViewState, payload: dict[str, Any]) -> ViewState:
    if "expanded_node_ids" in payload:
        state.expanded_node_ids = list(dict.fromkeys(payload["expanded_node_ids"] or []))
    if "selected_node_id" in payload:
        state.selected_node_id = payload["selected_node_id"]
    if "filters" in payload:
        state.filters = payload["filters"] or {}
    if "zoom" in payload:
        state.zoom = min(4.0, max(0.2, float(payload["zoom"])))
    if "pan" in payload:
        state.pan_x = float((payload["pan"] or {}).get("x", state.pan_x))
        state.pan_y = float((payload["pan"] or {}).get("y", state.pan_y))
    if "vertical_layout" in payload:
        state.vertical_layout = payload["vertical_layout"] or {}
    state.updated_at = utcnow()
    return state


def add_resource_reference(session: Session, node: GraphNode, payload: dict[str, Any], *, expected_version: int | None = None) -> tuple[ResourceReference, OperationBatch]:
    uri = str(payload.get("uri") or "").strip()
    if ":" not in uri:
        raise V2Error("INVALID_RESOURCE_URI", "resource.invalid_uri", {"uri": uri})
    batch = begin_batch(session, "add_resource", expected_version=expected_version)
    resource = ResourceReference(node_id=node.id, uri=uri, label=str(payload.get("label") or uri)[:500], role=str(payload.get("role") or "reference"), resource_type=str(payload.get("resource_type") or "link"), metadata_json=payload.get("metadata") or {})
    session.add(resource)
    session.flush()
    record_batch_operation(session, batch, "add_resource", {"resource_id": resource.id, "node_id": node.id}, {"action": "delete_resource", "resource_id": resource.id})
    batch.summary = {"resource_id": resource.id, "node_id": node.id}
    return resource, batch


def serialize_resource(resource: ResourceReference) -> dict[str, Any]:
    return {"id": resource.id, "node_id": resource.node_id, "uri": resource.uri, "label": resource.label, "role": resource.role, "resource_type": resource.resource_type, "metadata": resource.metadata_json or {}, "created_at": _iso(resource.created_at)}


def _split_context(session: Session, parent: GraphNode) -> dict[str, Any]:
    graph = graph_projection(session, parent.id)
    return {"parent": next(node for node in graph["nodes"] if node["id"] == parent.id), "children": [node for node in graph["nodes"] if node["parent_id"] == parent.id], "edges": graph["edges"], "graph_version": graph["graph_version"]}


def start_split_session(session: Session, parent: GraphNode, user_message: str | None = None) -> SplitSession:
    context = _split_context(session, parent)
    item = SplitSession(parent_node_id=parent.id, state="OPEN", context_graph_version=graph_version(session), context_snapshot=context, current_proposal_version=0)
    session.add(item)
    session.flush()
    session.add(SplitMessage(session_id=item.id, role="system", content="拆分会话已开始。提案在你明确提交前不会写入项目图。"))
    if user_message:
        add_split_message(session, item, user_message)
    return item


def add_split_message(session: Session, split: SplitSession, content: str) -> ProposalVersion:
    if split.state in {"COMMITTED", "DISCARDED"}:
        raise V2Error("SPLIT_SESSION_CLOSED", "split.session_closed", {"session_id": split.id}, status_code=409)
    content = str(content).strip()
    if not content:
        raise V2Error("MESSAGE_REQUIRED", "split.message_required", {})
    session.add(SplitMessage(session_id=split.id, role="user", content=content))
    previous = session.scalar(select(ProposalVersion).where(ProposalVersion.session_id == split.id).order_by(ProposalVersion.version.desc()))
    previous_payload = {"nodes": previous.proposed_nodes, "edges": previous.proposed_edges} if previous else None
    draft = get_split_adapter().propose(split.context_snapshot, content, previous_payload)
    version = split.current_proposal_version + 1
    proposal = ProposalVersion(session_id=split.id, version=version, rationale=draft.rationale, proposed_nodes=draft.nodes, proposed_edges=draft.edges, actionability_results=draft.actionability_results, warnings=draft.warnings)
    session.add(proposal)
    split.current_proposal_version = version
    split.state = "PENDING_USER_REVIEW"
    split.updated_at = utcnow()
    session.add(SplitMessage(session_id=split.id, role="assistant", content=draft.rationale))
    session.flush()
    return proposal


def current_proposal(session: Session, split: SplitSession) -> ProposalVersion | None:
    if not split.current_proposal_version:
        return None
    return session.scalar(select(ProposalVersion).where(ProposalVersion.session_id == split.id, ProposalVersion.version == split.current_proposal_version))


def validate_split_proposal(session: Session, split: SplitSession, proposal: ProposalVersion | None = None) -> dict[str, Any]:
    proposal = proposal or current_proposal(session, split)
    if proposal is None:
        return {"valid": False, "errors": [{"code": "PROPOSAL_REQUIRED", "message_key": "split.proposal_required", "params": {}}], "warnings": []}
    errors: list[dict[str, Any]] = []
    temporary_ids: set[str] = set()
    for node in proposal.proposed_nodes or []:
        temp_id = str(node.get("temporary_id") or "")
        if not temp_id or temp_id in temporary_ids:
            errors.append({"code": "DUPLICATE_TEMP_ID", "message_key": "split.duplicate_temp_id", "params": {"temporary_id": temp_id}})
        temporary_ids.add(temp_id)
        try:
            validate_node_payload(node)
        except V2Error as exc:
            errors.append(exc.as_detail())
        if str(node.get("work_type", "")).upper() == "ACTION":
            missing = [field for field in ("start_cue", "done_when", "estimated_effort_minutes") if not node.get(field)]
            if missing:
                errors.append({"code": "ACTIONABILITY_FAILED", "message_key": "split.actionability_failed", "params": {"temporary_id": temp_id, "missing": missing}})
    for edge in proposal.proposed_edges or []:
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        if source != "parent" and source not in temporary_ids:
            errors.append({"code": "PROPOSED_EDGE_SOURCE_MISSING", "message_key": "split.edge_source_missing", "params": {"source": source}})
        if target not in temporary_ids:
            errors.append({"code": "PROPOSED_EDGE_TARGET_MISSING", "message_key": "split.edge_target_missing", "params": {"target": target}})
        if edge.get("relation") not in RELATIONS:
            errors.append({"code": "INVALID_EDGE_RELATION", "message_key": "graph.invalid_relation", "params": {"relation": edge.get("relation")}})
    contains_targets = [str(edge.get("target")) for edge in proposal.proposed_edges or [] if edge.get("relation") == "contains"]
    for temp_id in temporary_ids:
        if contains_targets.count(temp_id) != 1:
            errors.append({"code": "PROPOSED_PARENT_COUNT", "message_key": "split.parent_count", "params": {"temporary_id": temp_id, "count": contains_targets.count(temp_id)}})
    return {"valid": not errors, "errors": errors, "warnings": proposal.warnings or [], "proposal_version": proposal.version}


def commit_split(session: Session, split: SplitSession, *, expected_graph_version: int, proposal_version: int) -> OperationBatch:
    if split.state in {"COMMITTED", "DISCARDED"}:
        raise V2Error("SPLIT_SESSION_CLOSED", "split.session_closed", {"session_id": split.id}, status_code=409)
    require_graph_version(session, expected_graph_version)
    if proposal_version != split.current_proposal_version:
        raise V2Error("PROPOSAL_VERSION_CONFLICT", "split.proposal_version_conflict", {"expected": proposal_version, "actual": split.current_proposal_version}, status_code=409)
    proposal = current_proposal(session, split)
    validation = validate_split_proposal(session, split, proposal)
    if not validation["valid"]:
        raise V2Error("INVALID_PROPOSAL", "split.invalid_proposal", {"errors": validation["errors"]})
    batch = begin_batch(session, "split_commit", expected_version=expected_graph_version)
    record_batch_operation(
        session,
        batch,
        "commit_split_session",
        {"session_id": split.id, "proposal_version": proposal.version},
        {"action": "restore_split_session", "session_id": split.id, "state": split.state, "committed_batch_id": split.committed_batch_id},
    )
    temp_to_real: dict[str, str] = {}
    for draft in proposal.proposed_nodes:
        payload = dict(draft)
        temp_id = payload.pop("temporary_id")
        node, _ = create_node_v2(session, payload, batch=batch)
        temp_to_real[temp_id] = node.id
    for draft in proposal.proposed_edges:
        source = split.parent_node_id if draft["source"] == "parent" else temp_to_real[draft["source"]]
        target = temp_to_real[draft["target"]]
        create_edge_v2(session, {"source_id": source, "target_id": target, "relation": draft["relation"], "required": draft.get("required", True), "metadata": {"proposal_version": proposal.version}}, batch=batch)
    split.state = "COMMITTED"
    split.committed_batch_id = batch.id
    split.updated_at = utcnow()
    batch.summary = {**(batch.summary or {}), "split_session_id": split.id, "proposal_version": proposal.version, "temporary_id_map": temp_to_real}
    session.add(SplitMessage(session_id=split.id, role="system", content="拆分已提交，可在 Canvas 和 Timeline 中查看。"))
    return batch


def discard_split(session: Session, split: SplitSession) -> None:
    if split.state == "COMMITTED":
        raise V2Error("SPLIT_ALREADY_COMMITTED", "split.already_committed", {"session_id": split.id}, status_code=409)
    split.state = "DISCARDED"
    split.updated_at = utcnow()
    session.add(SplitMessage(session_id=split.id, role="system", content="已放弃当前拆分提案。未提交的内容不会写入项目图。"))


def serialize_proposal(proposal: ProposalVersion | None) -> dict[str, Any] | None:
    if proposal is None:
        return None
    return {"id": proposal.id, "version": proposal.version, "rationale": proposal.rationale, "nodes": proposal.proposed_nodes or [], "edges": proposal.proposed_edges or [], "actionability_results": proposal.actionability_results or [], "warnings": proposal.warnings or [], "created_at": _iso(proposal.created_at)}


def serialize_split_session(session: Session, split: SplitSession) -> dict[str, Any]:
    messages = list(session.scalars(select(SplitMessage).where(SplitMessage.session_id == split.id).order_by(SplitMessage.created_at)).all())
    proposal = current_proposal(session, split)
    return {"id": split.id, "parent_node_id": split.parent_node_id, "state": split.state, "context_graph_version": split.context_graph_version, "context": split.context_snapshot, "current_proposal_version": split.current_proposal_version, "proposal": serialize_proposal(proposal), "messages": [{"id": item.id, "role": item.role, "content": item.content, "created_at": _iso(item.created_at)} for item in messages], "committed_batch_id": split.committed_batch_id, "created_at": _iso(split.created_at), "updated_at": _iso(split.updated_at)}


def serialize_batch(batch: OperationBatch) -> dict[str, Any]:
    return {"id": batch.id, "actor_channel": batch.actor_channel, "source": batch.source, "graph_version_before": batch.graph_version_before, "graph_version_after": batch.graph_version_after, "summary": batch.summary or {}, "undone_at": _iso(batch.undone_at), "created_at": _iso(batch.created_at)}


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def undo_batch(session: Session, batch: OperationBatch, *, expected_version: int | None = None) -> OperationBatch:
    if batch.undone_at:
        raise V2Error("BATCH_ALREADY_UNDONE", "operation.already_undone", {"batch_id": batch.id}, status_code=409)
    current = require_graph_version(session, expected_version)
    for inverse in reversed(batch.inverse_operations or []):
        action = inverse.get("action")
        if action == "delete_edge":
            edge = session.get(GraphEdge, inverse["edge_id"])
            if edge:
                session.delete(edge)
        elif action == "delete_node":
            node_id = inverse["node_id"]
            session.execute(delete(GraphEdge).where((GraphEdge.source_id == node_id) | (GraphEdge.target_id == node_id)))
            node = session.get(GraphNode, node_id)
            if node:
                session.delete(node)
        elif action == "delete_resource":
            resource = session.get(ResourceReference, inverse["resource_id"])
            if resource:
                session.delete(resource)
        elif action == "restore_state":
            node = session.get(GraphNode, inverse["node_id"])
            if node:
                node.stage, node.status, node.status_reason = inverse["stage"], inverse["status"], inverse.get("reason")
                node.closed_from_stage, node.closed_from_status, node.superseded_by = inverse.get("closed_from_stage"), inverse.get("closed_from_status"), inverse.get("superseded_by")
                node.lifecycle = _legacy_lifecycle(node.status, node.stage)
        elif action == "restore_schedule":
            node = session.get(GraphNode, inverse["node_id"])
            if node:
                node.planned_start, node.planned_end, node.placement_source = inverse.get("planned_start"), inverse.get("planned_end"), inverse.get("placement_source")
                node.last_user_adjusted_at = _parse_optional_datetime(inverse.get("last_user_adjusted_at"))
        elif action == "restore_parent":
            node = session.get(GraphNode, inverse["node_id"])
            if node:
                existing = session.scalar(select(GraphEdge).where(GraphEdge.target_id == node.id, GraphEdge.relation == "contains"))
                if existing:
                    session.delete(existing)
                    session.flush()
                if inverse.get("parent_id"):
                    session.add(GraphEdge(source_id=inverse["parent_id"], target_id=node.id, relation="contains", required=node.required, is_proposed=False, metadata_json={}))
                node.parent_id = inverse.get("parent_id")
        elif action == "restore_node":
            node = session.get(GraphNode, inverse["node_id"])
            if node:
                for field, value in inverse["snapshot"].items():
                    if field in {"last_user_adjusted_at", "archived_at"}:
                        value = _parse_optional_datetime(value)
                    setattr(node, field, value)
        elif action == "restore_split_session":
            split = session.get(SplitSession, inverse["session_id"])
            if split:
                split.state = inverse.get("state") or "PENDING_USER_REVIEW"
                split.committed_batch_id = inverse.get("committed_batch_id")
                split.updated_at = utcnow()
                session.add(SplitMessage(session_id=split.id, role="system", content="已撤销拆分提交，提案仍可继续编辑。"))
        else:
            raise V2Error("BATCH_NOT_UNDOABLE", "operation.not_undoable", {"batch_id": batch.id, "action": action})
    batch.undone_at = utcnow()
    graph_meta(session).graph_version = current + 1
    operations = list(session.scalars(select(Operation).where(Operation.batch_id == batch.id)).all())
    for operation in operations:
        operation.undone_at = batch.undone_at
    return batch
