from unittest.mock import patch

from llm_pipeline import mode_tasktype_pass, priority_pass, theme_pass, wbs_pass


def _config():
    return {
        "Task Theme with colour": [{"text": "Maker Sprint|Design", "color": "blue"}],
        "WBS level": ["1 | Level 1", "2 | Level 2", "3 | Level 3", "4 | Level 4"],
        "Priority": ["CRIT | (P$)", "ALERT | (P0)", "HIGH | (P1)", "NORMAL | (P2)"],
        "Modes": ["1 Focus  Deep work"],
        "Task Type": ["🔧 Build"],
    }


def test_quote_content_block_is_not_tagged_by_pipeline_passes():
    quote = {
        "id": "quote-1",
        "notion_block_id": "quote-1",
        "title": "Maker Sprint quote note",
        "original_notion_title": "Maker Sprint quote note",
        "type": "quote",
        "notion_type": "quote",
        "parent_id": "p1",
        "depth": 1,
        "is_content_block": True,
        "tags": {},
        "wbs_level": None,
        "timeliner_rank": 1,
        "timeliner_section": "sub",
        "timeliner_is_subproject": True,
        "timeliner_priority": 2,
    }
    state = [quote]
    scoped_ids = {"quote-1"}

    state = theme_pass(state, _config())
    with patch("llm_pipeline.classify_task") as classify_mock:
        state = wbs_pass(state, _config(), scoped_ids=scoped_ids)
    state = priority_pass(state, _config(), scoped_ids=scoped_ids, rank_by_task_id={"quote-1": 0})
    with patch("llm_pipeline.tag_task") as tag_mock:
        state = mode_tasktype_pass(state, _config(), scoped_ids=scoped_ids)

    assert state[0]["tags"] == {}
    assert state[0]["wbs_level"] is None
    classify_mock.assert_not_called()
    tag_mock.assert_not_called()
