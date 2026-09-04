"""Persistence model for committed graph truth, drafts, and reversible operations.

The legacy v1 columns remain mapped during the compatibility window.  v2 callers
use ``node_kind``/``work_type`` and ``stage``/``status``; ``kind``, ``lifecycle``
and ``parent_id`` are retained only so the old API and imports keep working while
clients migrate.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class GraphNode(Base):
    __tablename__ = "graph_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="TASK", nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(20), default="TODO", nullable=False)
    node_kind: Mapped[str] = mapped_column(String(20), default="WORK", nullable=False)
    work_type: Mapped[str] = mapped_column(String(30), default="UNCLASSIFIED", nullable=False)
    stage: Mapped[str] = mapped_column(String(20), default="PLANNING", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="TODO", nullable=False)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_from_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    closed_from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    notion_block_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    wbs_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin: Mapped[str] = mapped_column(String(20), default="human", nullable=False)
    is_proposed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    links: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_cue: Mapped[str | None] = mapped_column(Text, nullable=True)
    inputs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    done_when: Mapped[str | None] = mapped_column(Text, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    estimated_effort_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_effort_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimate_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    estimate_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_work_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    planned_start: Mapped[str | None] = mapped_column(String(10), nullable=True)
    planned_end: Mapped[str | None] = mapped_column(String(10), nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(10), nullable=True)
    placement_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_user_adjusted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    legacy_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    remote_baseline: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (UniqueConstraint("source_id", "target_id", "relation", name="uq_graph_edge"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("graph_nodes.id"), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(36), ForeignKey("graph_nodes.id"), nullable=False, index=True)
    relation: Mapped[str] = mapped_column(String(30), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_proposed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class FocusSession(Base):
    __tablename__ = "focus_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    node_id: Mapped[str] = mapped_column(String(36), ForeignKey("graph_nodes.id"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="web", nullable=False)


class CanvasPosition(Base):
    __tablename__ = "canvas_positions"

    node_id: Mapped[str] = mapped_column(String(36), ForeignKey("graph_nodes.id"), primary_key=True)
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class StatusEvent(Base):
    __tablename__ = "status_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    node_id: Mapped[str] = mapped_column(String(36), ForeignKey("graph_nodes.id"), nullable=False, index=True)
    before: Mapped[str | None] = mapped_column(String(20), nullable=True)
    after: Mapped[str] = mapped_column(String(20), nullable=False)
    stage_before: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stage_after: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(30), default="user", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(String(60), default="agent", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProposalItem(Base):
    __tablename__ = "proposal_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    proposal_id: Mapped[str] = mapped_column(String(36), ForeignKey("proposals.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Operation(Base):
    __tablename__ = "operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    operation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("operation_batches.id"), nullable=True, index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    inverse_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SyncConflict(Base):
    __tablename__ = "sync_conflicts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    node_id: Mapped[str] = mapped_column(String(36), ForeignKey("graph_nodes.id"), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(50), nullable=False)
    local_value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    remote_value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class GraphMeta(Base):
    __tablename__ = "graph_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    graph_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), default="1.1", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class OperationBatch(Base):
    __tablename__ = "operation_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_channel: Mapped[str] = mapped_column(String(30), default="user_ui", nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    graph_version_before: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_version_after: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    inverse_operations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ResourceReference(Base):
    __tablename__ = "resource_references"
    __table_args__ = (UniqueConstraint("node_id", "uri", "role", name="uq_node_resource_role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    node_id: Mapped[str] = mapped_column(String(36), ForeignKey("graph_nodes.id"), nullable=False, index=True)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="reference", nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), default="link", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ViewState(Base):
    __tablename__ = "view_states"
    __table_args__ = (UniqueConstraint("view", "scope_node_id", "client_key", name="uq_view_scope_client"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    view: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    client_key: Mapped[str] = mapped_column(String(100), default="default", nullable=False)
    expanded_node_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    selected_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    filters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    zoom: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    pan_x: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    pan_y: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    vertical_layout: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class SplitSession(Base):
    __tablename__ = "split_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    parent_node_id: Mapped[str] = mapped_column(String(36), ForeignKey("graph_nodes.id"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(30), default="OPEN", nullable=False)
    context_graph_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    current_proposal_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    committed_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class SplitMessage(Base):
    __tablename__ = "split_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("split_sessions.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProposalVersion(Base):
    __tablename__ = "proposal_versions"
    __table_args__ = (UniqueConstraint("session_id", "version", name="uq_split_proposal_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("split_sessions.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    proposed_nodes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    proposed_edges: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    actionability_results: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    warnings: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
