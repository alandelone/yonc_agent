"""HTTP contract for Yonc Project Graph API v2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .legacy import import_legacy_state, legacy_state_path
from .models import GraphNode, OperationBatch, ResourceReference, SplitSession
from .v2_service import (
    V2Error,
    add_resource_reference,
    add_split_message,
    apply_schedule,
    commit_split,
    create_edge_v2,
    create_node_v2,
    current_proposal,
    discard_split,
    get_view_state,
    graph_projection,
    graph_version,
    preview_schedule,
    reparent_node,
    serialize_batch,
    serialize_node,
    serialize_proposal,
    serialize_resource,
    serialize_split_session,
    serialize_view_state,
    start_split_session,
    suggest_schedule_range,
    timeline_projection,
    transition_node,
    undo_batch,
    update_node_v2,
    update_view_state,
    validate_split_proposal,
)


class V2NodeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    node_kind: Literal["WORK", "ARTIFACT", "RESOURCE", "AGENT"] = "WORK"
    work_type: Literal["UNCLASSIFIED", "GOAL", "DELIVERABLE", "WORK_PACKAGE", "ACTION"] = "UNCLASSIFIED"
    stage: Literal["CAPTURED", "PLANNING", "READY", "EXECUTION", "REVIEW", "CLOSED"] = "PLANNING"
    status: Literal["TODO", "DOING", "BLOCKED", "DONE", "CANCELLED", "SUPERSEDED"] = "TODO"
    status_reason: str | None = None
    parent_id: str | None = None
    description: str | None = None
    start_cue: str | None = None
    inputs: list[Any] = Field(default_factory=list)
    done_when: str | None = None
    required: bool = True
    tags: dict[str, Any] = Field(default_factory=dict)
    estimated_effort_minutes: int | None = Field(default=None, ge=0)
    estimate_source: str | None = None
    estimate_confidence: float | None = Field(default=None, ge=0, le=1)
    planned_start: str | None = None
    planned_end: str | None = None
    deadline: str | None = None
    placement_source: str | None = None
    notion_block_id: str | None = None
    origin: str = "human"
    expected_graph_version: int | None = None


class V2NodePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    work_type: Literal["UNCLASSIFIED", "GOAL", "DELIVERABLE", "WORK_PACKAGE", "ACTION"] | None = None
    description: str | None = None
    start_cue: str | None = None
    inputs: list[Any] | None = None
    done_when: str | None = None
    required: bool | None = None
    tags: dict[str, Any] | None = None
    estimated_effort_minutes: int | None = Field(default=None, ge=0)
    estimate_source: str | None = None
    estimate_confidence: float | None = Field(default=None, ge=0, le=1)
    deadline: str | None = None
    expected_graph_version: int | None = None


class V2EdgeCreate(BaseModel):
    source_id: str
    target_id: str
    relation: Literal["contains", "depends_on", "blocks", "related_to", "produces", "uses", "executed_by", "superseded_by"]
    required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    expected_graph_version: int | None = None


class ReparentPayload(BaseModel):
    parent_id: str | None
    expected_graph_version: int | None = None


class TransitionPayload(BaseModel):
    action: Literal["capture", "ready", "start", "block", "unblock", "submit_review", "done", "cancel", "supersede", "reopen", "undo_close"]
    reason: str | None = None
    superseded_by: str | None = None
    expected_graph_version: int | None = None


class SchedulePayload(BaseModel):
    planned_start: str | None = None
    planned_end: str | None = None
    preview: bool = False
    auto_span: bool = False
    placement_source: Literal["user", "forecast", "import"] = "user"
    expected_graph_version: int | None = None


class ViewStatePayload(BaseModel):
    expanded_node_ids: list[str] | None = None
    selected_node_id: str | None = None
    filters: dict[str, Any] | None = None
    zoom: float | None = None
    pan: dict[str, float] | None = None
    vertical_layout: dict[str, float] | None = None


class ResourcePayload(BaseModel):
    uri: str
    label: str | None = None
    role: str = "reference"
    resource_type: str = "link"
    metadata: dict[str, Any] = Field(default_factory=dict)
    expected_graph_version: int | None = None


class SplitStartPayload(BaseModel):
    parent_node_id: str
    message: str | None = None


class SplitMessagePayload(BaseModel):
    content: str = Field(min_length=1)


class SplitCommitPayload(BaseModel):
    expected_graph_version: int
    proposal_version: int


class UndoBatchPayload(BaseModel):
    expected_graph_version: int | None = None


class ImportPayload(BaseModel):
    source_path: str | None = None


def register_v2_routes(app: FastAPI, get_session) -> None:
    @app.exception_handler(V2Error)
    async def handle_v2_error(_request, exc: V2Error):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.as_detail()})

    def node_or_error(session: Session, node_id: str) -> GraphNode:
        node = session.get(GraphNode, node_id)
        if node is None or node.is_proposed:
            raise V2Error("NODE_NOT_FOUND", "graph.node_not_found", {"node_id": node_id}, status_code=404)
        return node

    def split_or_error(session: Session, split_id: str) -> SplitSession:
        split = session.get(SplitSession, split_id)
        if split is None:
            raise V2Error("SPLIT_SESSION_NOT_FOUND", "split.session_not_found", {"session_id": split_id}, status_code=404)
        return split

    @app.get("/api/v2/health")
    def health(session: Session = Depends(get_session)):
        return {"ok": True, "schema_version": "1.1", "graph_version": graph_version(session), "nodes": len(list(session.scalars(select(GraphNode.id)).all()))}

    @app.get("/api/v2/graph")
    def graph(scope_node_id: str | None = None, session: Session = Depends(get_session)):
        return graph_projection(session, scope_node_id)

    @app.get("/api/v2/nodes/{node_id}")
    def get_node(node_id: str, session: Session = Depends(get_session)):
        graph = graph_projection(session, node_id)
        return next(item for item in graph["nodes"] if item["id"] == node_id)

    @app.post("/api/v2/nodes", status_code=201)
    def create_node(payload: V2NodeCreate, session: Session = Depends(get_session)):
        values = payload.model_dump()
        expected = values.pop("expected_graph_version")
        node, batch = create_node_v2(session, values, expected_version=expected)
        return {"graph_version": batch.graph_version_after, "operation_batch_id": batch.id, "node": serialize_node(session, node, parent_id=values.get("parent_id"))}

    @app.patch("/api/v2/nodes/{node_id}")
    def patch_node(node_id: str, payload: V2NodePatch, session: Session = Depends(get_session)):
        node = node_or_error(session, node_id)
        values = payload.model_dump(exclude_unset=True)
        expected = values.pop("expected_graph_version", None)
        batch = update_node_v2(session, node, values, expected_version=expected)
        return {"graph_version": batch.graph_version_after, "operation_batch_id": batch.id, "node": serialize_node(session, node)}

    @app.post("/api/v2/edges", status_code=201)
    def create_edge(payload: V2EdgeCreate, session: Session = Depends(get_session)):
        values = payload.model_dump()
        expected = values.pop("expected_graph_version")
        edge, batch = create_edge_v2(session, values, expected_version=expected)
        from .v2_service import serialize_edge
        return {"graph_version": batch.graph_version_after, "operation_batch_id": batch.id, "edge": serialize_edge(edge)}

    @app.post("/api/v2/nodes/{node_id}/reparent")
    def reparent(node_id: str, payload: ReparentPayload, session: Session = Depends(get_session)):
        node = node_or_error(session, node_id)
        if payload.parent_id:
            node_or_error(session, payload.parent_id)
        batch = reparent_node(session, node, payload.parent_id, expected_version=payload.expected_graph_version)
        return {"graph_version": batch.graph_version_after, "operation_batch_id": batch.id, "node_id": node.id, "parent_id": payload.parent_id}

    @app.post("/api/v2/nodes/{node_id}/transition")
    def transition(node_id: str, payload: TransitionPayload, session: Session = Depends(get_session)):
        node = node_or_error(session, node_id)
        batch = transition_node(session, node, payload.action, reason=payload.reason, superseded_by=payload.superseded_by, expected_version=payload.expected_graph_version, actor_channel="user_ui")
        return {"graph_version": batch.graph_version_after, "operation_batch_id": batch.id, "node": serialize_node(session, node)}

    @app.post("/api/v2/agent/nodes/{node_id}/transition")
    def agent_transition(node_id: str, payload: TransitionPayload, session: Session = Depends(get_session)):
        node = node_or_error(session, node_id)
        batch = transition_node(session, node, payload.action, reason=payload.reason, superseded_by=payload.superseded_by, expected_version=payload.expected_graph_version, actor_channel="agent_api")
        return {"graph_version": batch.graph_version_after, "operation_batch_id": batch.id, "node": serialize_node(session, node)}

    @app.put("/api/v2/nodes/{node_id}/schedule")
    def schedule(node_id: str, payload: SchedulePayload, session: Session = Depends(get_session)):
        node = node_or_error(session, node_id)
        planned_start, planned_end = payload.planned_start, payload.planned_end
        generated = None
        if payload.auto_span and planned_start and not planned_end:
            generated = suggest_schedule_range(session, node, planned_start)
            planned_end = generated["planned_end"]
        if payload.preview:
            result = preview_schedule(session, node, planned_start, planned_end)
            result["generated"] = generated
            result["graph_version"] = graph_version(session)
            return result
        batch = apply_schedule(session, node, planned_start, planned_end, expected_version=payload.expected_graph_version, placement_source=payload.placement_source)
        return {"graph_version": batch.graph_version_after, "operation_batch_id": batch.id, "node_id": node.id, "planned_start": node.planned_start, "planned_end": node.planned_end, "generated": generated}

    @app.get("/api/v2/timeline")
    def timeline(start: str | None = None, end: str | None = None, scope_node_id: str | None = None, session: Session = Depends(get_session)):
        return timeline_projection(session, start, end, scope_node_id)

    @app.get("/api/v2/view-state/{view}")
    def read_view_state(view: str, scope_node_id: str | None = None, client_key: str = "default", session: Session = Depends(get_session)):
        return serialize_view_state(get_view_state(session, view, scope_node_id, client_key))

    @app.put("/api/v2/view-state/{view}")
    def write_view_state(view: str, payload: ViewStatePayload, scope_node_id: str | None = None, client_key: str = "default", session: Session = Depends(get_session)):
        state = get_view_state(session, view, scope_node_id, client_key)
        update_view_state(session, state, payload.model_dump(exclude_unset=True))
        return serialize_view_state(state)

    @app.get("/api/v2/nodes/{node_id}/resources")
    def list_resources(node_id: str, session: Session = Depends(get_session)):
        node_or_error(session, node_id)
        return [serialize_resource(item) for item in session.scalars(select(ResourceReference).where(ResourceReference.node_id == node_id).order_by(ResourceReference.created_at)).all()]

    @app.post("/api/v2/nodes/{node_id}/resources", status_code=201)
    def add_resource(node_id: str, payload: ResourcePayload, session: Session = Depends(get_session)):
        node = node_or_error(session, node_id)
        values = payload.model_dump()
        expected = values.pop("expected_graph_version")
        resource, batch = add_resource_reference(session, node, values, expected_version=expected)
        return {"graph_version": batch.graph_version_after, "operation_batch_id": batch.id, "resource": serialize_resource(resource)}

    @app.post("/api/v2/split-sessions", status_code=201)
    def start_split(payload: SplitStartPayload, session: Session = Depends(get_session)):
        split = start_split_session(session, node_or_error(session, payload.parent_node_id), payload.message)
        return serialize_split_session(session, split)

    @app.get("/api/v2/split-sessions/{split_id}")
    def get_split(split_id: str, session: Session = Depends(get_session)):
        return serialize_split_session(session, split_or_error(session, split_id))

    @app.get("/api/v2/split-sessions/{split_id}/proposal")
    def get_split_proposal(split_id: str, version: int | None = None, session: Session = Depends(get_session)):
        split = split_or_error(session, split_id)
        proposal = current_proposal(session, split)
        if version is not None:
            from .models import ProposalVersion
            proposal = session.scalar(select(ProposalVersion).where(ProposalVersion.session_id == split.id, ProposalVersion.version == version))
        return {"session_id": split.id, "proposal": serialize_proposal(proposal)}

    @app.post("/api/v2/split-sessions/{split_id}/messages")
    def split_message(split_id: str, payload: SplitMessagePayload, session: Session = Depends(get_session)):
        split = split_or_error(session, split_id)
        proposal = add_split_message(session, split, payload.content)
        return {"session_id": split.id, "state": split.state, "proposal": serialize_proposal(proposal)}

    @app.post("/api/v2/split-sessions/{split_id}/validate")
    def validate_split(split_id: str, session: Session = Depends(get_session)):
        split = split_or_error(session, split_id)
        return validate_split_proposal(session, split)

    @app.post("/api/v2/split-sessions/{split_id}/commit")
    def split_commit(split_id: str, payload: SplitCommitPayload, session: Session = Depends(get_session)):
        split = split_or_error(session, split_id)
        batch = commit_split(session, split, expected_graph_version=payload.expected_graph_version, proposal_version=payload.proposal_version)
        return {"session_id": split.id, "state": split.state, "operation_batch": serialize_batch(batch), "graph_version": batch.graph_version_after}

    @app.post("/api/v2/split-sessions/{split_id}/discard")
    def split_discard(split_id: str, session: Session = Depends(get_session)):
        split = split_or_error(session, split_id)
        discard_split(session, split)
        return {"session_id": split.id, "state": split.state}

    @app.get("/api/v2/operation-batches")
    def list_batches(limit: int = Query(default=50, ge=1, le=200), session: Session = Depends(get_session)):
        return [serialize_batch(batch) for batch in session.scalars(select(OperationBatch).order_by(OperationBatch.created_at.desc()).limit(limit)).all()]

    @app.post("/api/v2/operation-batches/{batch_id}/undo")
    def undo_operation_batch(batch_id: str, payload: UndoBatchPayload, session: Session = Depends(get_session)):
        batch = session.get(OperationBatch, batch_id)
        if batch is None:
            raise V2Error("BATCH_NOT_FOUND", "operation.batch_not_found", {"batch_id": batch_id}, status_code=404)
        undo_batch(session, batch, expected_version=payload.expected_graph_version)
        return {"operation_batch": serialize_batch(batch), "graph_version": graph_version(session)}

    def import_preview_payload(session: Session, source_path: str | None) -> dict[str, Any]:
        source = Path(source_path) if source_path else legacy_state_path()
        if not source.exists():
            raise V2Error("IMPORT_SOURCE_NOT_FOUND", "import.source_not_found", {"path": str(source)}, status_code=404)
        data = json.loads(source.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else []
        existing = set(session.scalars(select(GraphNode.notion_block_id).where(GraphNode.notion_block_id.is_not(None))).all())
        identifiers = [str(item.get("notion_block_id") or item.get("id") or "") for item in items]
        identifiers = [item for item in identifiers if item]
        return {"source": str(source.resolve()), "records": len(items), "identifiers": len(identifiers), "new": sum(item not in existing for item in identifiers), "existing": sum(item in existing for item in identifiers), "will_write_back_to_notion": False, "apply_required": True}

    @app.post("/api/v2/import/legacy/preview")
    def preview_import(payload: ImportPayload, session: Session = Depends(get_session)):
        return import_preview_payload(session, payload.source_path)

    @app.post("/api/v2/import/legacy/apply")
    def apply_import(payload: ImportPayload, session: Session = Depends(get_session)):
        preview = import_preview_payload(session, payload.source_path)
        result = import_legacy_state(session, payload.source_path)
        return {"preview": preview, "result": result, "will_write_back_to_notion": False}
