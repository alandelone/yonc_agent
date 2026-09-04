"""FastAPI application for the local graph and its browser UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .database import Base, make_engine
from .api_v2 import register_v2_routes
from .legacy import import_legacy_state
from .models import CanvasPosition, FocusSession, GraphEdge, GraphNode, Operation, Proposal, ProposalItem, SyncConflict, utcnow
from .service import (
    create_edge, create_node, edge_to_dict, finish_focus_session, node_to_dict,
    pace_summary, progress_by_node, set_lifecycle, undo_operation,
)
from .schema_v2 import ensure_v2_schema


class NodePayload(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    kind: Literal["TASK", "ARTIFACT", "RESOURCE", "AGENT"] = "TASK"
    lifecycle: Literal["TODO", "DOING", "DONE", "CANCELLED", "SUPERSEDED"] = "TODO"
    status_reason: str | None = None
    parent_id: str | None = None
    notion_block_id: str | None = None
    wbs_level: int | None = Field(default=None, ge=1, le=4)
    origin: str = "human"
    is_proposed: bool = False
    tags: dict[str, Any] = Field(default_factory=dict)
    links: list[Any] = Field(default_factory=list)
    estimated_effort_hours: float | None = Field(default=None, ge=0)
    planned_start: str | None = None
    planned_end: str | None = None
    deadline: str | None = None


class NodeUpdatePayload(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    kind: Literal["TASK", "ARTIFACT", "RESOURCE", "AGENT"] | None = None
    status_reason: str | None = None
    parent_id: str | None = None
    wbs_level: int | None = Field(default=None, ge=1, le=4)
    tags: dict[str, Any] | None = None
    links: list[Any] | None = None
    estimated_effort_hours: float | None = Field(default=None, ge=0)
    planned_start: str | None = None
    planned_end: str | None = None
    deadline: str | None = None


class EdgePayload(BaseModel):
    source_id: str
    target_id: str
    relation: Literal["contains", "depends_on", "produces", "uses", "assigned_to", "supersedes"]
    required: bool = True
    is_proposed: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class LifecyclePayload(BaseModel):
    lifecycle: Literal["TODO", "DOING", "DONE", "CANCELLED", "SUPERSEDED"]
    reason: str | None = None
    actor: str = "user"


class PositionPayload(BaseModel):
    x: float = Field(ge=-100000, le=100000)
    y: float = Field(ge=-100000, le=100000)


class ProposalItemPayload(BaseModel):
    action: Literal["create_node", "create_edge", "set_lifecycle"]
    payload: dict[str, Any]


class ProposalPayload(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    source: str = "agent"
    items: list[ProposalItemPayload] = Field(min_length=1)


def create_app(database_path: str | Path | None = None) -> FastAPI:
    engine = make_engine(database_path)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ensure_v2_schema(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Yonc Project Graph", version="1.1.0", lifespan=lifespan)
    app.state.session_factory = session_factory

    def get_session():
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_node_or_404(session: Session, node_id: str) -> GraphNode:
        node = session.get(GraphNode, node_id)
        if not node:
            raise HTTPException(404, "Node not found")
        return node

    register_v2_routes(app, get_session)

    @app.get("/api/v1/health")
    def health(session: Session = Depends(get_session)):
        return {"ok": True, "nodes": len(list(session.scalars(select(GraphNode.id))))}

    @app.get("/api/v1/graph")
    def graph(include_proposed: bool = True, session: Session = Depends(get_session)):
        node_query = select(GraphNode)
        edge_query = select(GraphEdge)
        if not include_proposed:
            node_query = node_query.where(GraphNode.is_proposed.is_(False))
            edge_query = edge_query.where(GraphEdge.is_proposed.is_(False))
        progress = progress_by_node(session)
        positions = {position.node_id: {"x": position.x, "y": position.y} for position in session.scalars(select(CanvasPosition)).all()}
        serialized_nodes = []
        for node in session.scalars(node_query.order_by(GraphNode.created_at)).all():
            serialized = node_to_dict(node, progress.get(node.id))
            serialized["position"] = positions.get(node.id)
            serialized_nodes.append(serialized)
        return {
            "nodes": serialized_nodes,
            "edges": [edge_to_dict(edge) for edge in session.scalars(edge_query).all()],
            "pace": pace_summary(session),
        }

    @app.post("/api/v1/nodes", status_code=201)
    def add_node(payload: NodePayload, session: Session = Depends(get_session)):
        if payload.parent_id:
            get_node_or_404(session, payload.parent_id)
        try:
            node = create_node(session, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return node_to_dict(node)

    @app.patch("/api/v1/nodes/{node_id}")
    def patch_node(node_id: str, payload: NodeUpdatePayload, session: Session = Depends(get_session)):
        node = get_node_or_404(session, node_id)
        before = node_to_dict(node)
        values = payload.model_dump(exclude_unset=True)
        if "parent_id" in values:
            parent_id = values.pop("parent_id")
            if parent_id:
                get_node_or_404(session, parent_id)
            from .v2_service import reparent_node
            reparent_node(session, node, parent_id)
        for field, value in values.items():
            setattr(node, field, value)
        if values:
            from .service import _record
            _record(session, "update_node", {"node_id": node.id}, {"action": "restore_node", "node": before})
        return node_to_dict(node)

    @app.post("/api/v1/nodes/{node_id}/lifecycle")
    def update_lifecycle(node_id: str, payload: LifecyclePayload, session: Session = Depends(get_session)):
        node = get_node_or_404(session, node_id)
        try:
            set_lifecycle(session, node, payload.lifecycle, actor=payload.actor, reason=payload.reason)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return node_to_dict(node)

    @app.put("/api/v1/nodes/{node_id}/position")
    def update_position(node_id: str, payload: PositionPayload, session: Session = Depends(get_session)):
        get_node_or_404(session, node_id)
        position = session.get(CanvasPosition, node_id)
        if position is None:
            position = CanvasPosition(node_id=node_id, x=payload.x, y=payload.y)
            session.add(position)
        else:
            position.x, position.y = payload.x, payload.y
        return {"node_id": node_id, "x": payload.x, "y": payload.y}

    @app.post("/api/v1/edges", status_code=201)
    def add_edge(payload: EdgePayload, session: Session = Depends(get_session)):
        get_node_or_404(session, payload.source_id)
        get_node_or_404(session, payload.target_id)
        try:
            edge = create_edge(session, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return edge_to_dict(edge)

    @app.delete("/api/v1/edges/{edge_id}")
    def delete_edge(edge_id: str, session: Session = Depends(get_session)):
        edge = session.get(GraphEdge, edge_id)
        if not edge:
            raise HTTPException(404, "Edge not found")
        from .service import _record
        _record(session, "delete_edge", {"edge_id": edge.id}, {"action": "restore_edge", "edge": edge_to_dict(edge)})
        session.delete(edge)
        return {"deleted": edge_id}

    @app.post("/api/v1/focus/start/{node_id}", status_code=201)
    def start_focus(node_id: str, session: Session = Depends(get_session)):
        get_node_or_404(session, node_id)
        active = session.scalar(select(FocusSession).where(FocusSession.ended_at.is_(None)))
        if active:
            finish_focus_session(session, active)
        focus = FocusSession(node_id=node_id)
        session.add(focus)
        session.flush()
        return {"id": focus.id, "node_id": focus.node_id, "started_at": focus.started_at.isoformat()}

    @app.post("/api/v1/focus/stop")
    def stop_focus(session: Session = Depends(get_session)):
        active = session.scalar(select(FocusSession).where(FocusSession.ended_at.is_(None)))
        if not active:
            return {"stopped": False}
        finish_focus_session(session, active)
        return {"stopped": True, "node_id": active.node_id, "ended_at": active.ended_at.isoformat()}

    @app.get("/api/v1/focus")
    def focus_state(session: Session = Depends(get_session)):
        active = session.scalar(select(FocusSession).where(FocusSession.ended_at.is_(None)))
        if not active:
            return {"active": None}
        node = get_node_or_404(session, active.node_id)
        return {"active": {"id": active.id, "node": node_to_dict(node), "started_at": active.started_at.isoformat()}}

    @app.post("/api/v1/proposals", status_code=201)
    def submit_proposal(payload: ProposalPayload, session: Session = Depends(get_session)):
        proposal = Proposal(title=payload.title, source=payload.source)
        session.add(proposal)
        session.flush()
        for item in payload.items:
            session.add(ProposalItem(proposal_id=proposal.id, action=item.action, payload=item.payload))
        return {"id": proposal.id, "status": proposal.status}

    @app.get("/api/v1/proposals")
    def list_proposals(session: Session = Depends(get_session)):
        proposals = session.scalars(select(Proposal).order_by(Proposal.created_at.desc())).all()
        return [
            {"id": proposal.id, "title": proposal.title, "source": proposal.source, "status": proposal.status,
             "created_at": proposal.created_at.isoformat(),
             "items": [{"id": item.id, "action": item.action, "payload": item.payload, "accepted": item.accepted} for item in session.scalars(select(ProposalItem).where(ProposalItem.proposal_id == proposal.id)).all()]}
            for proposal in proposals
        ]

    @app.post("/api/v1/proposals/{proposal_id}/accept")
    def accept_proposal(proposal_id: str, session: Session = Depends(get_session)):
        proposal = session.get(Proposal, proposal_id)
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        if proposal.status != "PENDING":
            raise HTTPException(409, "Proposal has already been resolved")
        for item in session.scalars(select(ProposalItem).where(ProposalItem.proposal_id == proposal.id)).all():
            try:
                if item.action == "create_node":
                    create_node(session, {**item.payload, "is_proposed": False})
                elif item.action == "create_edge":
                    create_edge(session, item.payload)
                elif item.action == "set_lifecycle":
                    node = get_node_or_404(session, item.payload["node_id"])
                    set_lifecycle(session, node, item.payload["lifecycle"], actor="user", reason=item.payload.get("reason"))
                item.accepted = True
            except (ValueError, KeyError) as exc:
                raise HTTPException(422, f"Proposal item {item.id}: {exc}") from exc
        proposal.status, proposal.resolved_at = "ACCEPTED", utcnow()
        return {"id": proposal.id, "status": proposal.status}

    @app.post("/api/v1/proposals/{proposal_id}/reject")
    def reject_proposal(proposal_id: str, session: Session = Depends(get_session)):
        proposal = session.get(Proposal, proposal_id)
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        proposal.status, proposal.resolved_at = "REJECTED", utcnow()
        for item in session.scalars(select(ProposalItem).where(ProposalItem.proposal_id == proposal.id)).all():
            item.accepted = False
        return {"id": proposal.id, "status": proposal.status}

    @app.get("/api/v1/operations")
    def operations(session: Session = Depends(get_session)):
        return [{"id": operation.id, "type": operation.operation_type, "created_at": operation.created_at.isoformat(), "undone_at": operation.undone_at.isoformat() if operation.undone_at else None} for operation in session.scalars(select(Operation).order_by(Operation.created_at.desc()).limit(30)).all()]

    @app.post("/api/v1/operations/{operation_id}/undo")
    def undo(operation_id: str, session: Session = Depends(get_session)):
        operation = session.get(Operation, operation_id)
        if not operation:
            raise HTTPException(404, "Operation not found")
        try:
            if operation.batch_id:
                from .models import OperationBatch
                from .v2_service import undo_batch
                batch = session.get(OperationBatch, operation.batch_id)
                if batch:
                    undo_batch(session, batch)
                else:
                    undo_operation(session, operation)
            else:
                undo_operation(session, operation)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": operation.id, "undone": True}

    @app.get("/api/v1/conflicts")
    def conflicts(session: Session = Depends(get_session)):
        return [{"id": conflict.id, "node_id": conflict.node_id, "field": conflict.field_name, "local": conflict.local_value, "remote": conflict.remote_value, "status": conflict.status} for conflict in session.scalars(select(SyncConflict).where(SyncConflict.status == "OPEN")).all()]

    @app.post("/api/v1/import/legacy")
    def import_existing_state(session: Session = Depends(get_session)):
        return import_legacy_state(session)

    static_dir = Path(__file__).with_name("static")
    static_v2_dir = Path(__file__).with_name("static_v2")
    if (static_v2_dir / "assets").exists():
        app.mount("/v2/assets", StaticFiles(directory=static_v2_dir / "assets"), name="v2-assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static_v2_dir / "index.html" if (static_v2_dir / "index.html").exists() else static_dir / "index.html")

    @app.get("/v2", include_in_schema=False)
    @app.get("/v2/", include_in_schema=False)
    def v2_index():
        return FileResponse(static_v2_dir / "index.html")

    @app.get("/legacy", include_in_schema=False)
    def legacy_index():
        return FileResponse(static_dir / "index.html")

    return app
