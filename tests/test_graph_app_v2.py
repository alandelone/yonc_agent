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


def test_agent_commit_requires_bound_single_use_user_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv("YONC_AGENT_COMMIT_TOKEN", "service-secret")
    app = create_app(tmp_path / "agent-authorization.sqlite3")
    with TestClient(app) as client:
        parent = client.post("/api/v2/nodes", json={"title": "Authorized project"}).json()["node"]
        split = client.post("/api/v2/split-sessions", json={
            "parent_node_id": parent["id"],
            "message": "Prepare source; Review result",
        }).json()
        version = split["current_proposal_version"]

        unauthorized = client.post(
            f"/api/v2/agent/split-sessions/{split['id']}/commit",
            json={"authorization_id": "forged"},
        )
        assert unauthorized.status_code == 401

        grant = client.post(
            f"/api/v2/split-sessions/{split['id']}/authorizations",
            json={"proposal_version": version},
        ).json()
        committed = client.post(
            f"/api/v2/agent/split-sessions/{split['id']}/commit",
            headers={"Authorization": "Bearer service-secret"},
            json={"authorization_id": grant["authorization_id"]},
        )
        assert committed.status_code == 200, committed.text

        replay = client.post(
            f"/api/v2/agent/split-sessions/{split['id']}/commit",
            headers={"Authorization": "Bearer service-secret"},
            json={"authorization_id": grant["authorization_id"]},
        )
        assert replay.status_code == 403


def test_split_message_with_structured_annotations(tmp_path):
    app = create_app(tmp_path / "annotations-split.sqlite3")
    with TestClient(app) as client:
        parent = create_node(client, "用户中心服务", work_type="DELIVERABLE")
        started = client.post("/api/v2/split-sessions", json={
            "parent_node_id": parent["id"], "message": "模块设计; 接口实现; 编写测试"
        })
        assert started.status_code == 201
        split = started.json()
        assert split["current_proposal_version"] == 1
        assert len(split["proposal"]["nodes"]) == 3
        assert split["proposal"]["nodes"][0]["title"] == "模块设计"
        assert split["proposal"]["nodes"][1]["title"] == "接口实现"
        assert split["proposal"]["nodes"][2]["title"] == "编写测试"

        # 针对 draft-2 发送划词拆分批注
        annotations = [
            {
                "target_temporary_id": "draft-2",
                "field": "title",
                "highlighted_text": "接口实现",
                "comment": "拆分为 用户接口 和 鉴权中间件",
            }
        ]
        revised = client.post(f"/api/v2/split-sessions/{split['id']}/messages", json={
            "content": "",
            "annotations": annotations,
        })
        assert revised.status_code == 200, revised.text
        proposal_v2 = revised.json()["proposal"]
        assert proposal_v2["version"] == 2
        # draft-1 保持不变，draft-2 拆成 2 个子行动，draft-3 顺延保持不变
        titles = [n["title"] for n in proposal_v2["nodes"]]
        assert titles == ["模块设计", "用户接口", "鉴权中间件", "编写测试"]

        # 查询会话详情，验证 annotations 已正确持久化
        session_detail = client.get(f"/api/v2/split-sessions/{split['id']}").json()
        user_msg = [m for m in session_detail["messages"] if m["role"] == "user"][-1]
        assert len(user_msg["annotations"]) == 1
        assert user_msg["annotations"][0]["target_temporary_id"] == "draft-2"
        assert user_msg["annotations"][0]["comment"] == "拆分为 用户接口 和 鉴权中间件"

        # 验证提交原子性
        graph_version = client.get("/api/v2/health").json()["graph_version"]
        commit_res = client.post(f"/api/v2/split-sessions/{split['id']}/commit", json={
            "expected_graph_version": graph_version,
            "proposal_version": 2,
        })
        assert commit_res.status_code == 200, commit_res.text
        committed_nodes = client.get("/api/v2/graph").json()["nodes"]
        # 1 个 parent + 4 个子任务 = 5 个正式节点
        assert len(committed_nodes) == 5
        committed_titles = {n["title"] for n in committed_nodes}
        assert {"用户中心服务", "模块设计", "用户接口", "鉴权中间件", "编写测试"}.issubset(committed_titles)


def test_discussion_message_does_not_create_a_new_proposal_version(tmp_path):
    app = create_app(tmp_path / "discussion.sqlite3")
    with TestClient(app) as client:
        parent = create_node(client, "Parent", work_type="DELIVERABLE")
        split = client.post("/api/v2/split-sessions", json={
            "parent_node_id": parent["id"],
            "message": "First; Second",
        }).json()
        version = split["current_proposal_version"]
        response = client.post(
            f"/api/v2/split-sessions/{split['id']}/messages",
            json={"content": "为什么建议这样安排？"},
        )
        assert response.status_code == 200
        assert response.json()["proposal"]["version"] == version
        restored = client.get("/api/v2/split-sessions", params={"state": "open"}).json()
        assert [item["id"] for item in restored] == [split["id"]]


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
        minimum_zoom = client.put(f"/api/v2/view-state/canvas?scope_node_id={goal['id']}&client_key=test", json={"zoom": 0.05}).json()
        assert minimum_zoom["zoom"] == 0.05
        persisted = client.get(f"/api/v2/view-state/canvas?scope_node_id={goal['id']}&client_key=test").json()
        assert persisted["vertical_layout"] == {task["id"]: 240}

        # Test remove from timeline (unschedule by sending null dates)
        unscheduled = client.put(f"/api/v2/nodes/{task['id']}/schedule", json={
            "planned_start": None, "planned_end": None
        })
        assert unscheduled.status_code == 200, unscheduled.text
        assert unscheduled.json()["planned_start"] is None
        assert unscheduled.json()["planned_end"] is None
        node_after = client.get("/api/v2/graph").json()["nodes"]
        task_in_graph = next(n for n in node_after if n["id"] == task["id"])
        assert task_in_graph["planned_start"] is None
        assert task_in_graph["planned_end"] is None


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


def test_yonc_config_is_seeded_editable_and_revision_guarded(tmp_path):
    with make_client(tmp_path) as client:
        seeded = client.get("/api/v2/settings/yonc-config")
        assert seeded.status_code == 200
        original = seeded.json()
        assert original["source"] == "yonc_config_cache"
        assert original["themes"]
        assert original["modes"]
        assert original["task_types"]

        payload = {
            "themes": [{"name": "Research", "sub_themes": ["Thesis", "Review"], "color": "#3366cc"}],
            "modes": [{"mode_name": "Focus", "level": 5, "description": "Deep work", "color": "#6d28d9"}],
            "task_types": [{"emoji": "🔬", "name": "Research", "description": "Evidence work", "tag": "research"}],
            "expected_revision": original["revision"],
        }
        saved = client.put("/api/v2/settings/yonc-config", json=payload)
        assert saved.status_code == 200
        assert saved.json()["source"] == "settings_ui"
        assert saved.json()["revision"] == original["revision"] + 1
        assert client.get("/api/v2/settings/yonc-config").json()["themes"] == payload["themes"]

        stale = client.put("/api/v2/settings/yonc-config", json=payload)
        assert stale.status_code == 409
        assert error_code(stale) == "CONFIG_VERSION_CONFLICT"

        duplicate = {**payload, "expected_revision": saved.json()["revision"], "themes": [payload["themes"][0], payload["themes"][0]]}
        rejected = client.put("/api/v2/settings/yonc-config", json=duplicate)
        assert rejected.status_code == 422
        assert error_code(rejected) == "CONFIG_DUPLICATE_NAME"


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


def test_split_sessions_list_and_mode_type_propagation(tmp_path):
    app = create_app(tmp_path / "split-tags.sqlite3")
    with TestClient(app) as client:
        parent = client.post("/api/v2/nodes", json={
            "title": "API Gateway Core",
            "node_kind": "WORK",
            "work_type": "DELIVERABLE",
            "tags": {"Modes": "💻Focus", "Task Type": "💻 Coding"},
        }).json()["node"]

        started = client.post("/api/v2/split-sessions", json={
            "parent_node_id": parent["id"],
            "message": "Gateway Router; JWT Middleware",
        }).json()
        assert started["state"] == "PENDING_USER_REVIEW"
        proposal = started["proposal"]
        assert len(proposal["nodes"]) >= 2
        for node in proposal["nodes"]:
            assert node["tags"].get("Modes") == "💻Focus"
            assert node["tags"].get("Task Type") == "💻 Coding"

        listed = client.get("/api/v2/split-sessions").json()
        assert len(listed) == 1
        assert listed[0]["id"] == started["id"]

        nodes = list(proposal["nodes"])
        nodes[0]["tags"]["Task Type"] = "⚙️ Architecture"
        updated = client.put(f"/api/v2/split-sessions/{started['id']}/proposal", json={"nodes": nodes}).json()
        assert updated["proposal"]["nodes"][0]["tags"]["Task Type"] == "⚙️ Architecture"

        graph_version = client.get("/api/v2/health").json()["graph_version"]
        commit_res = client.post(f"/api/v2/split-sessions/{started['id']}/commit", json={
            "expected_graph_version": graph_version,
            "proposal_version": updated["proposal"]["version"],
        })
        assert commit_res.status_code == 200

        graph_nodes = client.get("/api/v2/graph").json()["nodes"]
        child_arch = next(n for n in graph_nodes if n["id"] != parent["id"] and n["tags"].get("Task Type") == "⚙️ Architecture")
        assert child_arch["tags"]["Modes"] == "💻Focus"


def test_split_session_seeds_existing_children_and_supports_modify_add_delete(tmp_path):
    with make_client(tmp_path) as client:
        # 1. Create parent deliverable
        parent = client.post("/api/v2/nodes", json={
            "expected_graph_version": 1,
            "title": "笔记计算Deadline",
            "node_kind": "WORK",
            "work_type": "DELIVERABLE",
            "tags": {"Modes": ["💻Focus"], "Task Type": ["💻 Coding"]},
        }).json()["node"]

        # 2. Create two existing child action tasks
        c1 = client.post("/api/v2/nodes", json={
            "expected_graph_version": 2,
            "parent_id": parent["id"],
            "title": "list all task in draft",
            "node_kind": "WORK",
            "work_type": "ACTION",
            "start_cue": "Input ready",
            "done_when": "Done: Listed all draft tasks.",
            "estimated_effort_minutes": 30,
            "tags": {"Modes": ["💻Focus"], "Task Type": ["💻 Coding"]},
        }).json()["node"]

        c2 = client.post("/api/v2/nodes", json={
            "expected_graph_version": 3,
            "parent_id": parent["id"],
            "title": "配置 Task",
            "node_kind": "WORK",
            "work_type": "ACTION",
            "start_cue": "Config ready",
            "done_when": "Done: Tasks configured.",
            "estimated_effort_minutes": 45,
            "tags": {"Modes": ["💻Focus"], "Task Type": ["💻 Coding"]},
        }).json()["node"]

        # 3. Start split session with no user message -> should seed existing children
        started = client.post("/api/v2/split-sessions", json={
            "parent_node_id": parent["id"],
        }).json()
        assert started["state"] == "PENDING_USER_REVIEW"
        proposal = started["proposal"]
        assert proposal is not None
        assert len(proposal["nodes"]) == 2
        temp_ids = [n["temporary_id"] for n in proposal["nodes"]]
        assert c1["id"] in temp_ids
        assert c2["id"] in temp_ids

        # 4. Modify existing child 1, delete existing child 2, add new child 3
        mod_nodes = [
            {
                "temporary_id": c1["id"],
                "title": "list all task in draft (UPDATED)",
                "work_type": "ACTION",
                "start_cue": "Input ready",
                "done_when": "Done: Listed all draft tasks updated.",
                "estimated_effort_minutes": 50,
                "required": True,
                "tags": {"Modes": ["💻Focus"], "Task Type": ["💻 Coding"]},
            },
            {
                "temporary_id": "temp-new-child-3",
                "title": "实现 Deadline 计算 (NEW)",
                "work_type": "ACTION",
                "start_cue": "Code ready",
                "done_when": "Done: Calculated deadline.",
                "estimated_effort_minutes": 60,
                "required": True,
                "tags": {"Modes": ["💻Focus"], "Task Type": ["💻 Coding"]},
            },
        ]

        upd = client.put(
            f"/api/v2/split-sessions/{started['id']}/proposal",
            json={"nodes": mod_nodes, "suggested_removals": [c2["id"]]},
        ).json()
        assert len(upd["proposal"]["nodes"]) == 2

        # 5. Commit split
        gv = client.get("/api/v2/health").json()["graph_version"]
        commit_res = client.post(f"/api/v2/split-sessions/{started['id']}/commit", json={
            "expected_graph_version": gv,
            "proposal_version": upd["proposal"]["version"],
        })
        assert commit_res.status_code == 200, commit_res.text
        commit_data = commit_res.json()
        batch_id = commit_data["operation_batch"]["id"]

        # 6. Verify in graph
        graph_nodes = client.get("/api/v2/graph").json()["nodes"]
        # c1 updated
        c1_after = next(n for n in graph_nodes if n["id"] == c1["id"])
        assert c1_after["title"] == "list all task in draft (UPDATED)"
        assert c1_after["estimated_effort_minutes"] == 50
        # c2 is preserved for history, but explicitly detached and cancelled.
        c2_after = next(n for n in graph_nodes if n["id"] == c2["id"])
        assert c2_after["parent_id"] is None
        assert c2_after["status"] == "CANCELLED"
        # new node created under parent
        new_node = next(n for n in graph_nodes if n["title"] == "实现 Deadline 计算 (NEW)")
        assert new_node["parent_id"] == parent["id"]

        # 7. Test undo batch
        undo_res = client.post(f"/api/v2/operation-batches/{batch_id}/undo", json={
            "expected_graph_version": commit_data["graph_version"],
        })
        assert undo_res.status_code == 200, undo_res.text

        # Verify undo: c2 restored, c1 reverted, new node deleted
        graph_nodes_undone = client.get("/api/v2/graph").json()["nodes"]
        assert any(n["id"] == c2["id"] for n in graph_nodes_undone)
        c1_reverted = next(n for n in graph_nodes_undone if n["id"] == c1["id"])
        assert c1_reverted["title"] == "list all task in draft"
        assert not any(n["title"] == "实现 Deadline 计算 (NEW)" for n in graph_nodes_undone)


def test_split_auto_leveling_and_reparent_wbs(tmp_path):
    with make_client(tmp_path) as client:
        # Create L1 Goal
        goal = create_node(client, "L1 Master Project", work_type="GOAL")
        assert goal["wbs_level"] == 1

        # 1. Split L1 -> children should be DELIVERABLE (L2)
        split_l1 = client.post("/api/v2/split-sessions", json={
            "parent_node_id": goal["id"],
            "message": "Module Alpha; Module Beta",
        }).json()
        assert split_l1["state"] == "PENDING_USER_REVIEW"
        nodes_l1 = split_l1["proposal"]["nodes"]
        assert len(nodes_l1) == 2
        assert all(n["work_type"] == "DELIVERABLE" for n in nodes_l1)

        gv = client.get("/api/v2/health").json()["graph_version"]
        commit_l1 = client.post(f"/api/v2/split-sessions/{split_l1['id']}/commit", json={
            "expected_graph_version": gv,
            "proposal_version": split_l1["current_proposal_version"],
        }).json()
        assert "operation_batch" in commit_l1

        graph_after_l1 = client.get("/api/v2/graph").json()["nodes"]
        mod_alpha = next(n for n in graph_after_l1 if n["title"] == "Module Alpha")
        assert mod_alpha["work_type"] == "DELIVERABLE"
        assert mod_alpha["wbs_level"] == 2
        assert mod_alpha["parent_id"] == goal["id"]

        # 2. Split L2 Deliverable -> children should be WORK_PACKAGE (L3)
        split_l2 = client.post("/api/v2/split-sessions", json={
            "parent_node_id": mod_alpha["id"],
            "message": "Package 1; Package 2",
        }).json()
        nodes_l2 = split_l2["proposal"]["nodes"]
        assert len(nodes_l2) == 2
        assert all(n["work_type"] == "WORK_PACKAGE" for n in nodes_l2)

        gv = client.get("/api/v2/health").json()["graph_version"]
        client.post(f"/api/v2/split-sessions/{split_l2['id']}/commit", json={
            "expected_graph_version": gv,
            "proposal_version": split_l2["current_proposal_version"],
        })
        graph_after_l2 = client.get("/api/v2/graph").json()["nodes"]
        pkg1 = next(n for n in graph_after_l2 if n["title"] == "Package 1")
        assert pkg1["work_type"] == "WORK_PACKAGE"
        assert pkg1["wbs_level"] == 3

        # 3. Split L3 Work Package -> children should be ACTION (L4)
        split_l3 = client.post("/api/v2/split-sessions", json={
            "parent_node_id": pkg1["id"],
            "message": "Action A; Action B",
        }).json()
        nodes_l3 = split_l3["proposal"]["nodes"]
        assert all(n["work_type"] == "ACTION" for n in nodes_l3)

        # 4. Test Reparent & Auto-leveling for unclassified node
        unclass = create_node(client, "Inbox Idea", work_type="UNCLASSIFIED")
        assert unclass["work_type"] == "UNCLASSIFIED"
        assert unclass["wbs_level"] is None
        assert unclass["parent_id"] is None

        # Reparent to L1 Goal -> becomes L2 DELIVERABLE
        gv = client.get("/api/v2/health").json()["graph_version"]
        rep_to_l1 = client.post(f"/api/v2/nodes/{unclass['id']}/reparent", json={
            "parent_id": goal["id"],
            "expected_graph_version": gv,
        }).json()
        assert rep_to_l1["node"]["work_type"] == "DELIVERABLE"
        assert rep_to_l1["node"]["wbs_level"] == 2
        assert rep_to_l1["node"]["parent_id"] == goal["id"]
        batch_id = rep_to_l1["operation_batch_id"]

        # Undo reparent -> restores UNCLASSIFIED
        undo_res = client.post(f"/api/v2/operation-batches/{batch_id}/undo", json={
            "expected_graph_version": rep_to_l1["graph_version"],
        })
        assert undo_res.status_code == 200
        unclass_restored = client.get("/api/v2/graph").json()["nodes"]
        restored_node = next(n for n in unclass_restored if n["id"] == unclass["id"])
        assert restored_node["work_type"] == "UNCLASSIFIED"
        assert restored_node["wbs_level"] is None
        assert restored_node["parent_id"] is None

        # Reparent to L2 Deliverable -> becomes L3 WORK_PACKAGE
        gv = client.get("/api/v2/health").json()["graph_version"]
        rep_to_l2 = client.post(f"/api/v2/nodes/{unclass['id']}/reparent", json={
            "parent_id": mod_alpha["id"],
            "expected_graph_version": gv,
        }).json()
        assert rep_to_l2["node"]["work_type"] == "WORK_PACKAGE"
        assert rep_to_l2["node"]["wbs_level"] == 3

        # Set as L1 Top Project directly
        gv = client.get("/api/v2/health").json()["graph_version"]
        rep_to_top = client.post(f"/api/v2/nodes/{unclass['id']}/reparent", json={
            "parent_id": None,
            "work_type": "GOAL",
            "expected_graph_version": gv,
        }).json()
        assert rep_to_top["node"]["work_type"] == "GOAL"
        assert rep_to_top["node"]["wbs_level"] == 1
        assert rep_to_top["node"]["parent_id"] is None


def test_mark_cancel_cascade_and_undo(tmp_path):
    app = create_app(tmp_path / "cancel-cascade.sqlite3")
    with TestClient(app) as client:
        # Create parent L1
        parent = client.post("/api/v2/nodes", json={
            "title": "Main Project",
            "node_kind": "WORK",
            "work_type": "GOAL",
        }).json()["node"]

        # Create child L2
        child = client.post("/api/v2/nodes", json={
            "title": "Sub Deliverable",
            "node_kind": "WORK",
            "work_type": "DELIVERABLE",
            "parent_id": parent["id"],
        }).json()["node"]

        # 1. Attempt cancel without reason -> TERMINAL_REASON_REQUIRED
        gv = client.get("/api/v2/health").json()["graph_version"]
        fail_res = client.post(f"/api/v2/nodes/{parent['id']}/transition", json={
            "action": "cancel",
            "reason": "",
            "expected_graph_version": gv,
        })
        assert fail_res.status_code == 422
        assert error_code(fail_res) == "TERMINAL_REASON_REQUIRED"

        # 2. Cancel parent with reason -> cascades to child
        gv = client.get("/api/v2/health").json()["graph_version"]
        cancel_res = client.post(f"/api/v2/nodes/{parent['id']}/transition", json={
            "action": "cancel",
            "reason": "Market shifted",
            "expected_graph_version": gv,
        })
        assert cancel_res.status_code == 200
        batch_id = cancel_res.json()["operation_batch_id"]

        nodes = {n["id"]: n for n in client.get("/api/v2/graph").json()["nodes"]}
        assert nodes[parent["id"]]["status"] == "CANCELLED"
        assert nodes[parent["id"]]["stage"] == "CLOSED"
        assert nodes[parent["id"]]["status_reason"] == "Market shifted"
        assert nodes[child["id"]]["status"] == "CANCELLED"
        assert nodes[child["id"]]["stage"] == "CLOSED"
        assert nodes[child["id"]]["status_reason"] == "Market shifted"

        # 3. Undo batch -> restores parent and child
        gv = client.get("/api/v2/health").json()["graph_version"]
        undo_res = client.post(f"/api/v2/operation-batches/{batch_id}/undo", json={
            "expected_graph_version": gv,
        })
        assert undo_res.status_code == 200

        nodes = {n["id"]: n for n in client.get("/api/v2/graph").json()["nodes"]}
        assert nodes[parent["id"]]["status"] == "TODO"
        assert nodes[parent["id"]]["stage"] == "PLANNING"
        assert nodes[parent["id"]]["status_reason"] is None
        assert nodes[child["id"]]["status"] == "TODO"
        assert nodes[child["id"]]["stage"] == "PLANNING"
        assert nodes[child["id"]]["status_reason"] is None

        # 4. Cancel again, then reopen parent -> cascades reopen to child
        gv = client.get("/api/v2/health").json()["graph_version"]
        client.post(f"/api/v2/nodes/{parent['id']}/transition", json={
            "action": "cancel",
            "reason": "Cancelled again",
            "expected_graph_version": gv,
        })
        gv = client.get("/api/v2/health").json()["graph_version"]
        reopen_res = client.post(f"/api/v2/nodes/{parent['id']}/transition", json={
            "action": "reopen",
            "expected_graph_version": gv,
        })
        assert reopen_res.status_code == 200

        nodes = {n["id"]: n for n in client.get("/api/v2/graph").json()["nodes"]}
        assert nodes[parent["id"]]["status"] == "TODO"
        assert nodes[child["id"]]["status"] == "TODO"
