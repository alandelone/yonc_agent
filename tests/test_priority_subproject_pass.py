from llm_pipeline import priority_pass


def _config():
    return {
        "Priority": ["CRIT | (P$)", "ALERT | (P0)", "HIGH | (P1)", "NORMAL | (P2)"],
    }


def test_only_main_project_scoped_tasks_are_overwritten():
    state = [
        {
            "id": "a",
            "notion_block_id": "a",
            "depth": 0,
            "tags": {},
            "timeliner_section": "main",
            "timeliner_priority": 1,
        },
        {
            "id": "b",
            "notion_block_id": "b",
            "depth": 0,
            "tags": {},
            "timeliner_section": "main",
            "timeliner_priority": 2,
        },
        {
            "id": "c",
            "notion_block_id": "c",
            "depth": 0,
            "tags": {},
            "timeliner_section": "main",
            "timeliner_priority": 3,
        },
        {
            "id": "s",
            "notion_block_id": "s",
            "depth": 0,
            "tags": {"Priority": "MANUAL"},
            "timeliner_section": "sub",
            "timeliner_priority": 1,
        },
    ]
    scoped_ids = {"a", "b", "c", "s"}
    rank_by_task_id = {"a": 0, "b": 1, "c": 2, "s": 0}

    out = priority_pass(state, _config(), scoped_ids=scoped_ids, rank_by_task_id=rank_by_task_id)
    tags_by_id = {str(t.get("id")): (t.get("tags") or {}).get("Priority", "") for t in out}

    assert tags_by_id["a"] == "ALERT | (P0)"
    assert tags_by_id["b"] == "HIGH | (P1)"
    assert tags_by_id["c"] == "HIGH | (P1)"
    assert tags_by_id["s"] == ""


def test_subproject_only_scope_is_cleared():
    state = [
        {
            "id": "s1",
            "notion_block_id": "s1",
            "depth": 0,
            "tags": {"Priority": "KEEP-1"},
            "timeliner_section": "sub",
            "timeliner_priority": 1,
        },
        {
            "id": "s2",
            "notion_block_id": "s2",
            "depth": 1,
            "tags": {"Priority": "KEEP-2"},
            "timeliner_section": "sub",
            "timeliner_priority": 2,
        },
    ]
    scoped_ids = {"s1", "s2"}
    rank_by_task_id = {"s1": 0, "s2": 1}

    out = priority_pass(state, _config(), scoped_ids=scoped_ids, rank_by_task_id=rank_by_task_id)
    priorities = [(t.get("tags") or {}).get("Priority", "") for t in out]

    assert priorities == ["", ""]


def test_subproject_priority_is_removed_without_fallback():
    state = [
        {
            "id": "s1",
            "notion_block_id": "s1",
            "depth": 1,
            "tags": {},
            "timeliner_section": "sub",
            "timeliner_is_subproject": True,
            "timeliner_priority": 2,
        },
        {
            "id": "s2",
            "notion_block_id": "s2",
            "depth": 1,
            "tags": {"Priority": "KEEP"},
            "timeliner_section": "sub",
            "timeliner_is_subproject": True,
            "timeliner_priority": 4,
        },
    ]
    scoped_ids = {"s1", "s2"}
    rank_by_task_id = {"s1": 0, "s2": 1}

    out = priority_pass(state, _config(), scoped_ids=scoped_ids, rank_by_task_id=rank_by_task_id)
    tags_by_id = {str(t.get("id")): (t.get("tags") or {}).get("Priority", "") for t in out}

    assert tags_by_id["s1"] == ""
    assert tags_by_id["s2"] == ""


def test_non_timeliner_priority_is_removed():
    state = [
        {
            "id": "x",
            "notion_block_id": "x",
            "depth": 0,
            "original_notion_title": "ALERT task outside timeliner",
            "tags": {"Priority": "KEEP"},
            "timeliner_section": "",
            "timeliner_priority": None,
        },
    ]

    out = priority_pass(state, _config(), scoped_ids=set(), rank_by_task_id={})

    assert (out[0].get("tags") or {}).get("Priority", "") == ""
