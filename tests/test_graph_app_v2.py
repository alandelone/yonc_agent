from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from graph_app.api import create_app
from graph_app.database import Base, make_engine
from graph_app.models import GraphNode, ProposalVersion, StatusEvent
from graph_app.schema_v2 import ensure_v2_schema
from graph_app.v2_service import pace_projection


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "graph-v2.sqlite3"))


def create_node(client: TestClient, title: str, **values):
    response = client.post("/api/v2/nodes", json={"title": title, **values})
    assert response.status_code == 201, response.text
    return response.json()["node"]


def error_code(response) -> str:
    return response.json()["error"]["code"]


def test_contains_parent_cycle_reparent_and_version_conflict(tmp_path):
    with make_client(tmp_path) as client:
        first = create_node(client, "First goal", work_type="GOAL")
        second = create_node(client, "Second goal", work_type="GOAL")
        child = create_node(client, "Canonical child", work_type="WORK_PACKAGE", parent_id=first["id"])

        duplicate_parent = client.post("/api/v2/edges", json={
            "source_id": second["id"], "target_id": child["id"], "relation": "contains"
        })
        assert duplicate_parent.status_code == 422
        assert error_code(duplicate_parent) == "MULTIPLE_CONTAINS_PARENTS"

        version = client.get("/api/v2/health").json()["graph_version"]
        moved = client.post(f"/api/v2/nodes/{child['id']}/reparent", json={
            "parent_id": second["id"], "expected_graph_version": version
        })
        assert moved.status_code == 200
        assert moved.json()["parent_id"] == second["id"]

        stale = client.patch(f"/api/v2/nodes/{child['id']}", json={
            "title": "Stale edit", "expected_graph_version": version
        })
        assert stale.status_code == 409
        assert error_code(stale) == "GRAPH_VERSION_CONFLICT"

        current = client.get("/api/v2/health").json()["graph_version"]
        cycle = client.post(f"/api/v2/nodes/{second['id']}/reparent", json={
            "parent_id": child["id"], "expected_graph_version": current
        })
        assert cycle.status_code == 422
        assert error_code(cycle) == "GRAPH_CYCLE"


def test_stage_status_terminal_rules_user_only_done_and_reopen(tmp_path):
    with make_client(tmp_path) as client:
        action = create_node(
            client,
            "Executable action",
            work_type="ACTION",
            start_cue="Open the source file",
            done_when="Reviewed result exists",
        )
        started = client.post(f"/api/v2/nodes/{action['id']}/transition", json={"action": "start"})
        assert started.json()["node"]["stage"] == "EXECUTION"

        blocked = client.post(f"/api/v2/nodes/{action['id']}/transition", json={"action": "block", "reason": "Waiting"})
        assert blocked.json()["node"]["stage"] == "EXECUTION"
        assert blocked.json()["node"]["status"] == "BLOCKED"

        denied = client.post(f"/api/v2/agent/nodes/{action['id']}/transition", json={"action": "done"})
        assert denied.status_code == 403
        assert error_code(denied) == "USER_ONLY_DONE"

        missing_reason = client.post(f"/api/v2/nodes/{action['id']}/transition", json={"action": "cancel"})
        assert missing_reason.status_code == 422
        assert error_code(missing_reason) == "TERMINAL_REASON_REQUIRED"

        cancelled = client.post(f"/api/v2/nodes/{action['id']}/transition", json={"action": "cancel", "reason": "No longer required"})
        assert cancelled.json()["node"]["stage"] == "CLOSED"
        assert cancelled.json()["node"]["status"] == "CANCELLED"

        reopened = client.post(f"/api/v2/nodes/{action['id']}/transition", json={"action": "reopen"})
        assert reopened.json()["node"]["stage"] == "EXECUTION"
        assert reopened.json()["node"]["status"] == "BLOCKED"

        completed = client.post(f"/api/v2/nodes/{action['id']}/transition", json={"action": "done"})
        assert completed.json()["node"]["stage"] == "CLOSED"
        assert completed.json()["node"]["status"] == "DONE"


def test_recursive_effort_progress_excludes_optional_and_cancelled_work(tmp_path):
    with make_client(tmp_path) as client:
        goal = create_node(client, "Goal", work_type="GOAL")
        small = create_node(client, "Small required", work_type="ACTION", parent_id=goal["id"], estimated_effort_minutes=60)
        large = create_node(client, "Large required", work_type="ACTION", parent_id=goal["id"], estimated_effort_minutes=180)
        create_node(client, "Optional", work_type="ACTION", parent_id=goal["id"], estimated_effort_minutes=600, required=False)

        assert client.post(f"/api/v2/nodes/{small['id']}/transition", json={"action": "done"}).status_code == 200
        projected = client.get(f"/api/v2/nodes/{goal['id']}").json()
        assert projected["progress"]["ratio"] == pytest.approx(0.25)
        assert projected["progress"]["weight_minutes"] == 240

        assert client.post(f"/api/v2/nodes/{large['id']}/transition", json={"action": "cancel", "reason": "Removed from scope"}).status_code == 200
        projected = client.get(f"/api/v2/nodes/{goal['id']}").json()
        assert projected["progress"]["ratio"] == 1
        assert projected["progress"]["weight_minutes"] == 60


def test_split_versions_atomic_commit_and_complete_batch_undo(tmp_path):
    app = create_app(tmp_path / "split.sqlite3")
    with TestClient(app) as client:
        parent = create_node(client, "Release package", work_type="DELIVERABLE")
        started = client.post("/api/v2/split-sessions", json={
            "parent_node_id": parent["id"], "message": "Prepare source; Review package"
        })
        assert started.status_code == 201
        split = started.json()
        assert split["current_proposal_version"] == 1
        assert len(client.get("/api/v2/graph").json()["nodes"]) == 1

        revised = client.post(f"/api/v2/split-sessions/{split['id']}/messages", json={
            "content": "Prepare final source; Verify final package"
        }).json()
        assert revised["proposal"]["version"] == 2

        graph_version = client.get("/api/v2/health").json()["graph_version"]
        stale = client.post(f"/api/v2/split-sessions/{split['id']}/commit", json={
            "expected_graph_version": graph_version, "proposal_version": 1
        })
        assert stale.status_code == 409
        assert error_code(stale) == "PROPOSAL_VERSION_CONFLICT"
        assert len(client.get("/api/v2/graph").json()["nodes"]) == 1

        committed = client.post(f"/api/v2/split-sessions/{split['id']}/commit", json={
            "expected_graph_version": graph_version, "proposal_version": 2
        })
        assert committed.status_code == 200, committed.text
        body = committed.json()
        assert body["state"] == "COMMITTED"
        assert len(client.get("/api/v2/graph").json()["nodes"]) == 3

        undone = client.post(
            f"/api/v2/operation-batches/{body['operation_batch']['id']}/undo",
            json={"expected_graph_version": body["graph_version"]},
        )
        assert undone.status_code == 200, undone.text
        assert len(client.get("/api/v2/graph").json()["nodes"]) == 1
        assert client.get(f"/api/v2/split-sessions/{split['id']}").json()["state"] == "PENDING_USER_REVIEW"


def test_invalid_split_proposal_never_changes_committed_graph(tmp_path):
    app = create_app(tmp_path / "invalid-split.sqlite3")
    with TestClient(app) as client:
        parent = create_node(client, "Parent", work_type="GOAL")
        split = client.post("/api/v2/split-sessions", json={
            "parent_node_id": parent["id"], "message": "First; Second"
        }).json()
        with app.state.session_factory() as session:
            proposal = session.query(ProposalVersion).filter_by(session_id=split["id"], version=1).one()
            proposal.proposed_edges = []
            session.commit()
        version = client.get("/api/v2/health").json()["graph_version"]
        rejected = client.post(f"/api/v2/split-sessions/{split['id']}/commit", json={
            "expected_graph_version": version, "proposal_version": 1
        })
        assert rejected.status_code == 422
        assert error_code(rejected) == "INVALID_PROPOSAL"
        graph = client.get("/api/v2/graph").json()
        assert graph["graph_version"] == version
        assert [node["title"] for node in graph["nodes"]] == ["Parent"]


def test_schedule_constraints_auto_span_overlap_and_view_state(tmp_path):
    with make_client(tmp_path) as client:
        goal = create_node(client, "Dated goal", work_type="GOAL", deadline="2026-08-10")
        dependency = create_node(client, "Dependency", work_type="ACTION", parent_id=goal["id"], estimated_effort_minutes=60)
        task = create_node(client, "Scheduled task", work_type="ACTION", parent_id=goal["id"], estimated_effort_minutes=240)
        assert client.put(f"/api/v2/nodes/{dependency['id']}/schedule", json={"planned_start": "2026-08-05", "planned_end": "2026-08-07"}).status_code == 200
        assert client.post("/api/v2/edges", json={"source_id": task["id"], "target_id": dependency["id"], "relation": "depends_on"}).status_code == 201

        invalid_order = client.put(f"/api/v2/nodes/{task['id']}/schedule", json={
            "planned_start": "2026-08-06", "planned_end": "2026-08-09", "preview": True
        }).json()
        assert invalid_order["valid"] is False
        assert {item["code"] for item in invalid_order["violations"]} == {"DEPENDENCY_ORDER_CONFLICT"}

        after_deadline = client.put(f"/api/v2/nodes/{task['id']}/schedule", json={
            "planned_start": "2026-08-08", "planned_end": "2026-08-11", "preview": True
        }).json()
        assert after_deadline["valid"] is False
        assert "ANCESTOR_DEADLINE_CONFLICT" in {item["code"] for item in after_deadline["violations"]}

        auto = client.put(f"/api/v2/nodes/{task['id']}/schedule", json={
            "planned_start": "2026-08-08", "auto_span": True
        })
        assert auto.status_code == 200, auto.text
        assert auto.json()["planned_end"] == "2026-08-09"

        for title in ("Overlap B", "Overlap C"):
            node = create_node(client, title, work_type="ACTION", parent_id=goal["id"], estimated_effort_minutes=30)
            assert client.put(f"/api/v2/nodes/{node['id']}/schedule", json={"planned_start": "2026-08-08", "planned_end": "2026-08-09"}).status_code == 200
        timeline = client.get("/api/v2/timeline?start=2026-08-08&end=2026-08-09").json()
        assert all(cell["overlap_count"] == 3 and cell["overflow_count"] == 1 for cell in timeline["cells"])
        assert all(warning["code"] == "CAPACITY_OVERLAP" for warning in timeline["warnings"])

        multi_year = client.get("/api/v2/timeline?start=2023-01-02&end=2033-01-02")
        assert multi_year.status_code == 200
        assert len(multi_year.json()["cells"]) == 3654
        year_boundary = client.get("/api/v2/timeline?start=2024-12-30&end=2025-01-01").json()["cells"]
        assert {(cell["iso_year"], cell["iso_week"]) for cell in year_boundary} == {(2025, 1)}

        state = client.put(f"/api/v2/view-state/canvas?scope_node_id={goal['id']}&client_key=test", json={
            "expanded_node_ids": [goal["id"], goal["id"]],
            "selected_node_id": task["id"],
            "zoom": 9,
            "pan": {"x": 42, "y": -8},
            "vertical_layout": {task["id"]: 240},
        }).json()
        assert state["expanded_node_ids"] == [goal["id"]]
        assert state["zoom"] == 4
        assert state["pan"] == {"x": 42.0, "y": -8.0}
        persisted = client.get(f"/api/v2/view-state/canvas?scope_node_id={goal['id']}&client_key=test").json()
        assert persisted["vertical_layout"] == {task["id"]: 240}


def test_iso_week_pace_counts_each_current_done_transition_once(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'pace.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        completed = [
            GraphNode(title="A", work_type="ACTION", stage="CLOSED", status="DONE", estimated_effort_minutes=60),
            GraphNode(title="B", work_type="ACTION", stage="CLOSED", status="DONE", estimated_effort_minutes=120),
            GraphNode(title="C", work_type="ACTION", stage="CLOSED", status="DONE", estimated_effort_minutes=60),
        ]
        reopened = GraphNode(title="Reopened", work_type="ACTION", stage="EXECUTION", status="DOING", estimated_effort_minutes=600)
        session.add_all([*completed, reopened])
        session.flush()
        events = [
            StatusEvent(node_id=completed[0].id, after="DONE", created_at=datetime(2026, 8, 11, tzinfo=timezone.utc)),
            StatusEvent(node_id=completed[0].id, before="DONE", after="DONE", created_at=datetime(2026, 8, 12, tzinfo=timezone.utc)),
            StatusEvent(node_id=completed[1].id, after="DONE", created_at=datetime(2026, 8, 18, tzinfo=timezone.utc)),
            StatusEvent(node_id=completed[2].id, after="DONE", created_at=datetime(2026, 8, 19, tzinfo=timezone.utc)),
            StatusEvent(node_id=reopened.id, after="DONE", created_at=datetime(2026, 8, 18, tzinfo=timezone.utc)),
            StatusEvent(node_id=reopened.id, before="DONE", after="DOING", created_at=datetime(2026, 8, 20, tzinfo=timezone.utc)),
        ]
        session.add_all(events)
        session.commit()
        pace = pace_projection(session, today=date(2026, 8, 29))
        assert pace["reliable"] is True
        assert pace["completion_count"] == 3
        assert pace["distinct_weeks"] == 2
        assert pace["weeks"]["2026-08-10"] == 1
        assert pace["weeks"]["2026-08-17"] == 3
        assert pace["median_hours"] == 2


def test_legacy_import_is_idempotent_and_does_not_write_notion(tmp_path):
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps([
        {"id": "root", "title": "Imported root", "wbs_level": 1},
        {"id": "child", "title": "Imported child", "wbs_level": 4, "parent_id": "root"},
    ]), encoding="utf-8")
    with make_client(tmp_path) as client:
        preview = client.post("/api/v2/import/legacy/preview", json={"source_path": str(source)}).json()
        assert preview["new"] == 2
        assert preview["will_write_back_to_notion"] is False
        first = client.post("/api/v2/import/legacy/apply", json={"source_path": str(source)})
        second = client.post("/api/v2/import/legacy/apply", json={"source_path": str(source)})
        assert first.json()["result"] == {"created": 2, "updated": 0, "skipped": 0}
        assert second.json()["result"] == {"created": 0, "updated": 2, "skipped": 0}
        graph = client.get("/api/v2/graph").json()
        assert len(graph["nodes"]) == 2
        assert len([edge for edge in graph["edges"] if edge["relation"] == "contains"]) == 1


def test_real_551_node_backup_migrates_without_legacy_field_loss(tmp_path):
    backups = sorted((Path(__file__).parents[1] / "data" / "backups").glob("project_graph_pre_v11_*.sqlite3"))
    if not backups:
        pytest.skip("No pre-v1.1 project backup is available in this checkout")
    source = backups[-1]
    migrated = tmp_path / "real-project-copy.sqlite3"
    shutil.copy2(source, migrated)
    legacy_fields = [
        "id", "title", "kind", "lifecycle", "status_reason", "parent_id", "notion_block_id",
        "wbs_level", "origin", "is_proposed", "tags", "links", "estimated_effort_hours",
        "planned_start", "planned_end", "deadline", "remote_baseline",
    ]
    with sqlite3.connect(migrated) as connection:
        before_nodes = connection.execute(f"SELECT {','.join(legacy_fields)} FROM graph_nodes ORDER BY id").fetchall()
        before_edges = connection.execute("SELECT id,source_id,target_id,relation,required,is_proposed,metadata_json FROM graph_edges ORDER BY id").fetchall()
    assert len(before_nodes) == 551
    assert len(before_edges) == 495

    engine = make_engine(migrated)
    ensure_v2_schema(engine)
    with sqlite3.connect(migrated) as connection:
        after_nodes = connection.execute(f"SELECT {','.join(legacy_fields)} FROM graph_nodes ORDER BY id").fetchall()
        after_edges = connection.execute("SELECT id,source_id,target_id,relation,required,is_proposed,metadata_json FROM graph_edges ORDER BY id").fetchall()
        mapped = dict(connection.execute("SELECT work_type, COUNT(*) FROM graph_nodes GROUP BY work_type").fetchall())
        typed_resources = connection.execute("SELECT COUNT(*) FROM resource_references").fetchone()[0]
    engine.dispose()
    assert after_nodes == before_nodes
    assert after_edges == before_edges
    assert mapped == {"ACTION": 300, "DELIVERABLE": 31, "GOAL": 14, "UNCLASSIFIED": 85, "WORK_PACKAGE": 121}
    assert typed_resources == 2
