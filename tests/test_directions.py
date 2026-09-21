from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from graph_app.api import create_app


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "test-directions.sqlite3"))


def test_directions_crud_and_lane_allocation(tmp_path):
    with make_client(tmp_path) as client:
        # 1. Create first direction
        res1 = client.post(
            "/api/v2/directions",
            json={
                "title": "Focus Thesis Writing",
                "notes": "- Draft chapter 3\n- Complete intro",
                "color": "#38bdf8",
                "start_date": "2026-09-18",
                "end_date": "2026-09-25",
            },
        )
        assert res1.status_code == 200, res1.text
        data1 = res1.json()
        dir1 = data1["direction"]
        assert dir1["title"] == "Focus Thesis Writing"
        assert dir1["lane_index"] == 0
        batch1_id = data1["operation_batch"]["id"]

        # 2. Create overlapping direction -> should get lane_index 1
        res2 = client.post(
            "/api/v2/directions",
            json={
                "title": "Lab Experiment Run",
                "notes": "- Prepare samples",
                "color": "#a855f7",
                "start_date": "2026-09-20",
                "end_date": "2026-09-28",
            },
        )
        assert res2.status_code == 200, res2.text
        dir2 = res2.json()["direction"]
        assert dir2["lane_index"] == 1

        # 3. Create non-overlapping direction -> should reuse lane_index 0
        res3 = client.post(
            "/api/v2/directions",
            json={
                "title": "System Architecture Review",
                "notes": "- Review PRs",
                "color": "#10b981",
                "start_date": "2026-10-01",
                "end_date": "2026-10-07",
            },
        )
        assert res3.status_code == 200, res3.text
        dir3 = res3.json()["direction"]
        assert dir3["lane_index"] == 0

        # 4. List directions -> ordered by start_date
        list_res = client.get("/api/v2/directions")
        assert list_res.status_code == 200
        items = list_res.json()
        assert len(items) == 3
        assert [i["title"] for i in items] == [
            "Focus Thesis Writing",
            "Lab Experiment Run",
            "System Architecture Review",
        ]

        # 5. Update direction
        update_res = client.patch(
            f"/api/v2/directions/{dir1['id']}",
            json={
                "title": "Updated Focus Thesis",
                "notes": "- Updated bullet",
                "color": "#f59e0b",
                "offset_x": 42.5,
            },
        )
        assert update_res.status_code == 200
        updated_dir1 = update_res.json()["direction"]
        assert updated_dir1["title"] == "Updated Focus Thesis"
        assert updated_dir1["offset_x"] == 42.5
        assert updated_dir1["color"] == "#f59e0b"
        update_batch_id = update_res.json()["operation_batch"]["id"]

        # 6. Test Undo of update
        undo_update_res = client.post(f"/api/v2/operation-batches/{update_batch_id}/undo", json={})
        assert undo_update_res.status_code == 200
        reloaded = client.get("/api/v2/directions").json()
        reloaded_dir1 = next(i for i in reloaded if i["id"] == dir1["id"])
        assert reloaded_dir1["title"] == "Focus Thesis Writing"
        assert reloaded_dir1["color"] == "#38bdf8"

        # 7. Delete direction
        del_res = client.delete(f"/api/v2/directions/{dir2['id']}")
        assert del_res.status_code == 200
        del_batch_id = del_res.json()["operation_batch"]["id"]
        assert len(client.get("/api/v2/directions").json()) == 2

        # 8. Undo delete -> dir2 restored
        undo_del_res = client.post(f"/api/v2/operation-batches/{del_batch_id}/undo", json={})
        assert undo_del_res.status_code == 200
        assert len(client.get("/api/v2/directions").json()) == 3

        # 9. Undo create of dir1 -> dir1 deleted
        undo_create_res = client.post(f"/api/v2/operation-batches/{batch1_id}/undo", json={})
        assert undo_create_res.status_code == 200
        remaining_ids = [i["id"] for i in client.get("/api/v2/directions").json()]
        assert dir1["id"] not in remaining_ids
