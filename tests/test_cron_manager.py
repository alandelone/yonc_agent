import cron_manager
from cron_manager import (
    _add_multiselect_set_values,
    _extract_multiselect_task_names,
    _increment_multiselect,
    _is_multiselect_counter_mode,
    _is_cron_done,
    is_cron_marked_done,
    mark_cron_done,
    post_cron,
)


def test_number_value_does_not_imply_cron_done():
    assert _is_cron_done("Focus Count", "number", 3) is False


def test_multiselect_value_does_not_imply_cron_done():
    assert _is_cron_done("Hydration", "multi_select", ["1 X Water"]) is False


def test_checkbox_and_rich_text_still_indicate_done():
    assert _is_cron_done("Checked", "checkbox", True) is True
    assert _is_cron_done("Response", "rich_text", "done") is True


def test_multiselect_options_accept_counter_and_plain_names():
    options = [
        {"name": "2 X 断水"},
        {"name": "深呼吸"},
        {"name": "  "},
    ]

    assert _extract_multiselect_task_names(options) == ["断水", "深呼吸"]


def test_multiselect_plain_current_tag_upgrades_without_duplicate():
    assert _increment_multiselect(["断水"], ["断水"]) == ["1 X 断水"]


def test_multiselect_counter_still_increments():
    assert _increment_multiselect(["1 X 断水"], ["断水"]) == ["2 X 断水"]


def test_multiselect_schema_counter_mode_detection():
    assert _is_multiselect_counter_mode([{"name": "1 X Water"}]) is True
    assert _is_multiselect_counter_mode([{"name": "Water"}, {"name": "Breath"}]) is False


def test_multiselect_set_mode_adds_plain_tags_without_counting():
    assert _add_multiselect_set_values(["Water"], ["Water", "Breath"]) == [
        "Water",
        "Breath",
    ]


def test_post_cron_multiselect_plain_schema_writes_set_values(monkeypatch):
    updated = {}

    monkeypatch.setattr(cron_manager, "_get_prop_type", lambda name: "multi_select")
    monkeypatch.setattr(
        cron_manager,
        "_get_schema",
        lambda: {"Habit": {"multi_select": {"options": [{"name": "Water"}]}}},
    )
    monkeypatch.setattr(cron_manager, "mark_cron_done", lambda name: None)
    monkeypatch.setattr("notion_db_utils.query_page_by_date", lambda db_id, day: {"id": "page"})
    monkeypatch.setattr("notion_db_utils.extract_all_properties", lambda page: {"Habit": []})
    monkeypatch.setattr(
        "notion_db_utils.build_property_payload",
        lambda name, prop_type, value: {name: {"multi_select": value}},
    )
    monkeypatch.setattr(
        "notion_db_utils.update_page_properties",
        lambda page_id, payload: updated.update(payload),
    )

    post_cron("Habit", value="Water")

    assert updated == {"Habit": {"multi_select": ["Water"]}}


def test_post_cron_multiselect_counter_schema_writes_counter_values(monkeypatch):
    updated = {}

    monkeypatch.setattr(cron_manager, "_get_prop_type", lambda name: "multi_select")
    monkeypatch.setattr(
        cron_manager,
        "_get_schema",
        lambda: {"Habit": {"multi_select": {"options": [{"name": "1 X Water"}]}}},
    )
    monkeypatch.setattr(cron_manager, "mark_cron_done", lambda name: None)
    monkeypatch.setattr("notion_db_utils.query_page_by_date", lambda db_id, day: {"id": "page"})
    monkeypatch.setattr("notion_db_utils.extract_all_properties", lambda page: {"Habit": ["1 X Water"]})
    monkeypatch.setattr(
        "notion_db_utils.build_property_payload",
        lambda name, prop_type, value: {name: {"multi_select": value}},
    )
    monkeypatch.setattr(
        "notion_db_utils.update_page_properties",
        lambda page_id, payload: updated.update(payload),
    )

    post_cron("Habit", value="Water")

    assert updated == {"Habit": {"multi_select": ["2 X Water"]}}


def test_successful_post_marker_proves_cron_done_for_today(tmp_path, monkeypatch):
    monkeypatch.setattr(cron_manager, "DONE_FILE", tmp_path / "cron_done_today.json")

    assert is_cron_marked_done("断水") is False
    mark_cron_done("断水")

    assert is_cron_marked_done("断水") is True
