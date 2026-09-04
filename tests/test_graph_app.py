from fastapi.testclient import TestClient

from graph_app.api import create_app


def make_client(tmp_path):
    return TestClient(create_app(tmp_path / "graph.sqlite3"))


def test_graph_lifecycle_progress_focus_and_undo(tmp_path):
    with make_client(tmp_path) as client:
        parent = client.post("/api/v1/nodes", json={"title": "Project", "wbs_level": 1}).json()
        child = client.post("/api/v1/nodes", json={"title": "Action", "parent_id": parent["id"], "estimated_effort_hours": 2}).json()
        response = client.post(f"/api/v1/nodes/{child['id']}/lifecycle", json={"lifecycle": "DONE", "actor": "user"})
        assert response.status_code == 200
        graph = client.get("/api/v1/graph").json()
        parent_graph = next(node for node in graph["nodes"] if node["id"] == parent["id"])
        assert parent_graph["progress"]["ratio"] == 1
        assert parent_graph["progress"]["closure_suggested"] is True

        started = client.post(f"/api/v1/focus/start/{child['id']}")
        assert started.status_code == 201
        assert client.post("/api/v1/focus/stop").json()["stopped"] is True

        operations = client.get("/api/v1/operations").json()
        create_child = next(item for item in operations if item["type"] == "create_node")
        assert client.post(f"/api/v1/operations/{create_child['id']}/undo").status_code == 200
        assert len(client.get("/api/v1/graph").json()["nodes"]) == 1


def test_agent_proposal_cannot_silently_complete_work(tmp_path):
    with make_client(tmp_path) as client:
        task = client.post("/api/v1/nodes", json={"title": "A task"}).json()
        denied = client.post(f"/api/v1/nodes/{task['id']}/lifecycle", json={"lifecycle": "DONE", "actor": "agent"})
        assert denied.status_code == 422
        proposal = client.post("/api/v1/proposals", json={
            "title": "Propose a child", "items": [{"action": "create_node", "payload": {"title": "Suggested task", "is_proposed": True}}]
        })
        assert proposal.status_code == 201
        assert len(client.get("/api/v1/graph").json()["nodes"]) == 1
        assert client.post(f"/api/v1/proposals/{proposal.json()['id']}/accept").status_code == 200
        assert len(client.get("/api/v1/graph").json()["nodes"]) == 2


def test_partial_node_update_does_not_reset_unmentioned_fields(tmp_path):
    with make_client(tmp_path) as client:
        node = client.post("/api/v1/nodes", json={"title": "Original", "deadline": "2026-12-01", "estimated_effort_hours": 3}).json()
        updated = client.patch(f"/api/v1/nodes/{node['id']}", json={"title": "Renamed"})
        assert updated.status_code == 200
        assert updated.json()["deadline"] == "2026-12-01"
        assert updated.json()["estimated_effort_hours"] == 3


def test_canvas_position_persists_in_graph_response(tmp_path):
    with make_client(tmp_path) as client:
        node = client.post("/api/v1/nodes", json={"title": "Move me"}).json()
        moved = client.put(f"/api/v1/nodes/{node['id']}/position", json={"x": 412.5, "y": -80})
        assert moved.status_code == 200
        graph_node = next(item for item in client.get("/api/v1/graph").json()["nodes"] if item["id"] == node["id"])
        assert graph_node["position"] == {"x": 412.5, "y": -80.0}
