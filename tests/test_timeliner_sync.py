from completion import DONE_PREFIX
import timeliner_sync
from timeliner_reader import TimelineEntry
from timeliner_state import build_scope_key


def test_calculate_progress():
    tasks = [
        {"type": "to_do", "tags": {"Task Theme with colour": "Maker Fitness"}, "checked": True},
        {"type": "to_do", "tags": {"Task Theme with colour": "Maker Fitness"}, "checked": False},
        {"type": "bullet", "tags": {"Task Theme with colour": "Study"}, "title": f"{DONE_PREFIX} Read book"},
        {"type": "heading_2", "tags": {"Task Theme with colour": "Hide"}},
    ]

    stats = timeliner_sync.calculate_progress_by_subtheme(tasks)
    assert stats["Maker Fitness"] == (1, 2)
    assert stats["Study"] == (1, 1)
    assert "Hide" not in stats

    assert timeliner_sync.get_percentage("Fitness", stats) == 50
    assert timeliner_sync.get_percentage("Study", stats) == 100
    assert timeliner_sync.get_percentage("Unknown", stats) == 0


def test_build_rich_text():
    entry = TimelineEntry(
        block_id="b1",
        project="Proj",
        subproject="Sub",
        colour_subtheme="Task",
        status_emoji="A",
        settle_date="2026-03-30",
        time_expected_h=4.5,
        percent=50,
        remaining_work_days=5,
        raw_text="",
        in_heading_scope=True,
    )

    rt = timeliner_sync.build_timeliner_rich_text(
        entry=entry,
        new_percent=100,
        new_status_emoji="B",
        existing_rt=[],
        theme_label="Theme",
    )

    assert rt[0]["text"]["content"] == "B"
    assert rt[0]["annotations"]["strikethrough"] is True
    assert any(chunk.get("type") == "mention" for chunk in rt)
    assert any("100%" in chunk.get("text", {}).get("content", "") for chunk in rt if chunk.get("type") == "text")


def _mock_requests_get(*args, **kwargs):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"type": "paragraph", "paragraph": {"rich_text": []}}

    return _Resp()


def test_sync_timeliner_uses_audit_only_and_state_heading_only(monkeypatch):
    inside = TimelineEntry(
        block_id="inside-block",
        project="Main",
        subproject="Sub",
        colour_subtheme="Inside",
        status_emoji="A",
        settle_date="2026-04-12",
        time_expected_h=1.0,
        percent=0,
        remaining_work_days=None,
        raw_text="",
        in_heading_scope=True,
    )
    outside = TimelineEntry(
        block_id="outside-block",
        project="",
        subproject="",
        colour_subtheme="Outside",
        status_emoji="A",
        settle_date="2026-04-11",
        time_expected_h=1.0,
        percent=0,
        remaining_work_days=None,
        raw_text="",
        in_heading_scope=False,
    )
    entries = [inside, outside]

    inside_scope = build_scope_key("Inside", project="Main", subproject="Sub")

    recorded = []
    ext_calls = []
    pushed_blocks = []
    saved_payload = {}

    monkeypatch.setattr(timeliner_sync, "fetch_and_parse_timeliner", lambda: entries)
    monkeypatch.setattr(timeliner_sync, "load_state", lambda *_: [])
    monkeypatch.setattr(
        timeliner_sync,
        "load_latest_audit_dates",
        lambda: ({inside_scope: "2026-04-10"}, {"Outside": "2026-04-09"}),
    )
    monkeypatch.setattr(timeliner_sync, "resolve_status_emoji", lambda *_: "A")
    monkeypatch.setattr(timeliner_sync, "build_timeliner_rich_text", lambda **_: [])
    monkeypatch.setattr(timeliner_sync, "update_block", lambda block_id, payload: pushed_blocks.append(block_id))
    monkeypatch.setattr("requests.get", _mock_requests_get)

    def _record(block_id, subtheme, old_date, new_date, project="", subproject=""):
        recorded.append((block_id, subtheme, old_date, new_date, project, subproject))
        return len(recorded)

    def _get_ext(subtheme, project="", subproject=""):
        ext_calls.append((subtheme, project, subproject))
        return 0

    def _save(state, priority_scope_order=None):
        saved_payload["state"] = dict(state)
        saved_payload["order"] = list(priority_scope_order or [])

    monkeypatch.setattr(timeliner_sync, "record_date_change", _record)
    monkeypatch.setattr(timeliner_sync, "get_extension_count", _get_ext)
    monkeypatch.setattr(timeliner_sync, "save_timeliner_state", _save)

    timeliner_sync.sync_timeliner()

    assert ("inside-block", "Inside", "2026-04-10", "2026-04-12", "Main", "Sub") in recorded
    assert ("outside-block", "Outside", "2026-04-09", "2026-04-11", "", "") in recorded
    assert len(recorded) == 2

    assert saved_payload["state"] == {inside_scope: "2026-04-12"}
    assert saved_payload["order"] == [inside_scope]

    assert ("Inside", "Main", "Sub") in ext_calls
    assert ("Outside", "", "") in ext_calls
    assert set(pushed_blocks) == {"inside-block", "outside-block"}


def test_sync_timeliner_first_observation_skips_audit(monkeypatch):
    inside = TimelineEntry(
        block_id="inside-first",
        project="Main",
        subproject="Sub",
        colour_subtheme="Inside",
        status_emoji="A",
        settle_date="2026-04-20",
        time_expected_h=1.0,
        percent=0,
        remaining_work_days=None,
        raw_text="",
        in_heading_scope=True,
    )
    outside = TimelineEntry(
        block_id="outside-first",
        project="",
        subproject="",
        colour_subtheme="Outside",
        status_emoji="A",
        settle_date="2026-04-21",
        time_expected_h=1.0,
        percent=0,
        remaining_work_days=None,
        raw_text="",
        in_heading_scope=False,
    )
    entries = [inside, outside]

    inside_scope = build_scope_key("Inside", project="Main", subproject="Sub")

    called = {"record": 0}
    saved_payload = {}

    monkeypatch.setattr(timeliner_sync, "fetch_and_parse_timeliner", lambda: entries)
    monkeypatch.setattr(timeliner_sync, "load_state", lambda *_: [])
    monkeypatch.setattr(timeliner_sync, "load_latest_audit_dates", lambda: ({}, {}))
    monkeypatch.setattr(timeliner_sync, "resolve_status_emoji", lambda *_: "A")
    monkeypatch.setattr(timeliner_sync, "get_extension_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(timeliner_sync, "build_timeliner_rich_text", lambda **_: [])
    monkeypatch.setattr(timeliner_sync, "update_block", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("requests.get", _mock_requests_get)

    def _record(*_args, **_kwargs):
        called["record"] += 1
        return called["record"]

    def _save(state, priority_scope_order=None):
        saved_payload["state"] = dict(state)
        saved_payload["order"] = list(priority_scope_order or [])

    monkeypatch.setattr(timeliner_sync, "record_date_change", _record)
    monkeypatch.setattr(timeliner_sync, "save_timeliner_state", _save)

    timeliner_sync.sync_timeliner()

    assert called["record"] == 0
    assert saved_payload["state"] == {inside_scope: "2026-04-20"}
    assert saved_payload["order"] == [inside_scope]
