"""
tests/test_cycle_runner.py — Unit tests for pipeline.runner.CycleRunner orchestration.

Uses unittest.mock to stub out all external calls (Notion, LLM, disk I/O).
Verifies:
  - Phases are called in correct order
  - dry_run=True prevents Notion writes and disk saves
  - skip_split=True bypasses Phase 3
"""
import pytest
from unittest.mock import MagicMock, patch, call


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_minimal_tree():
    return [
        {
            "id": "task1",
            "notion_block_id": "task1",
            "parent_id": None,
            "title": "Test Task",
            "original_notion_title": "Test Task",
            "type": "bulleted_list_item",
            "notion_type": "bulleted_list_item",
            "depth": 0,
            "wbs_level": 1,
            "has_tag_style": False,
            "is_generated": False,
            "checked": None,
            "tags": {},
            "children": [],
        }
    ]


# ── Phase ordering ────────────────────────────────────────────────────────────

@patch("pipeline.runner.save_state")
@patch("pipeline.runner.push_tags_to_notion")
@patch("pipeline.runner.EnrichPhase")
@patch("pipeline.runner.SplitTaskPhase")
@patch("pipeline.runner.WBSTagPhase")
@patch("pipeline.runner.FormatCheckPhase")
@patch("pipeline.runner.merge_states")
@patch("pipeline.runner.sync_from_notion")
@patch("pipeline.runner.flatten_tree")
@patch("pipeline.runner.fetch_and_build_task_tree")
@patch("pipeline.runner.structure_yonctask_config")
@patch("pipeline.runner.load_config")
def test_phases_called_in_order(
    mock_load_cfg, mock_struct, mock_fetch, mock_flatten,
    mock_sync, mock_merge, mock_p1, mock_p2, mock_p3, mock_p4,
    mock_push, mock_save
):
    call_order = []

    tree = _make_minimal_tree()
    mock_load_cfg.return_value = {}
    mock_struct.return_value = {"themes": {}, "modes": [], "priorities": {},
                                 "task_states": {}, "task_types": {}, "wbs_levels": {}}
    mock_fetch.return_value = tree
    mock_flatten.return_value = tree
    mock_sync.return_value = tree
    mock_merge.return_value = tree

    for name, mock_cls in [("P1", mock_p1), ("P2", mock_p2),
                           ("P3", mock_p3), ("P4", mock_p4)]:
        instance = MagicMock()
        instance.run.side_effect = lambda ctx, n=name: call_order.append(n)
        mock_cls.return_value = instance

    from pipeline.runner import CycleRunner
    CycleRunner(dry_run=False, skip_split=False).run()

    assert call_order == ["P1", "P2", "P3", "P4"], f"Wrong order: {call_order}"


# ── dry_run prevents writes ───────────────────────────────────────────────────

@patch("pipeline.runner.save_state")
@patch("pipeline.runner.push_tags_to_notion")
@patch("pipeline.runner.EnrichPhase")
@patch("pipeline.runner.SplitTaskPhase")
@patch("pipeline.runner.WBSTagPhase")
@patch("pipeline.runner.FormatCheckPhase")
@patch("pipeline.runner.merge_states")
@patch("pipeline.runner.sync_from_notion")
@patch("pipeline.runner.flatten_tree")
@patch("pipeline.runner.fetch_and_build_task_tree")
@patch("pipeline.runner.structure_yonctask_config")
@patch("pipeline.runner.load_config")
def test_dry_run_no_notion_write(
    mock_load_cfg, mock_struct, mock_fetch, mock_flatten,
    mock_sync, mock_merge, mock_p1, mock_p2, mock_p3, mock_p4,
    mock_push, mock_save
):
    tree = _make_minimal_tree()
    mock_load_cfg.return_value = {}
    mock_struct.return_value = {"themes": {}, "modes": [], "priorities": {},
                                 "task_states": {}, "task_types": {}, "wbs_levels": {}}
    mock_fetch.return_value = tree
    mock_flatten.return_value = tree
    mock_sync.return_value = tree
    mock_merge.return_value = tree
    for mock_cls in [mock_p1, mock_p2, mock_p3, mock_p4]:
        mock_cls.return_value.run = MagicMock()

    from pipeline.runner import CycleRunner
    CycleRunner(dry_run=True, skip_split=False).run()

    mock_push.assert_not_called()
    mock_save.assert_not_called()


# ── skip_split bypasses Phase 3 ──────────────────────────────────────────────

@patch("pipeline.runner.save_state")
@patch("pipeline.runner.push_tags_to_notion")
@patch("pipeline.runner.EnrichPhase")
@patch("pipeline.runner.SplitTaskPhase")
@patch("pipeline.runner.WBSTagPhase")
@patch("pipeline.runner.FormatCheckPhase")
@patch("pipeline.runner.merge_states")
@patch("pipeline.runner.sync_from_notion")
@patch("pipeline.runner.flatten_tree")
@patch("pipeline.runner.fetch_and_build_task_tree")
@patch("pipeline.runner.structure_yonctask_config")
@patch("pipeline.runner.load_config")
def test_skip_split_omits_phase3(
    mock_load_cfg, mock_struct, mock_fetch, mock_flatten,
    mock_sync, mock_merge, mock_p1, mock_p2, mock_p3, mock_p4,
    mock_push, mock_save
):
    tree = _make_minimal_tree()
    mock_load_cfg.return_value = {}
    mock_struct.return_value = {"themes": {}, "modes": [], "priorities": {},
                                 "task_states": {}, "task_types": {}, "wbs_levels": {}}
    mock_fetch.return_value = tree
    mock_flatten.return_value = tree
    mock_sync.return_value = tree
    mock_merge.return_value = tree
    for mock_cls in [mock_p1, mock_p2, mock_p3, mock_p4]:
        mock_cls.return_value.run = MagicMock()

    from pipeline.runner import CycleRunner
    CycleRunner(dry_run=True, skip_split=True).run()

    # Phase 3 instantiated but .run() never called
    mock_p3.return_value.run.assert_not_called()
    # Phases 1, 2, 4 still called
    mock_p1.return_value.run.assert_called_once()
    mock_p2.return_value.run.assert_called_once()
    mock_p4.return_value.run.assert_called_once()


# ── Empty Notion tree exits early ────────────────────────────────────────────

@patch("pipeline.runner.save_state")
@patch("pipeline.runner.push_tags_to_notion")
@patch("pipeline.runner.EnrichPhase")
@patch("pipeline.runner.SplitTaskPhase")
@patch("pipeline.runner.WBSTagPhase")
@patch("pipeline.runner.FormatCheckPhase")
@patch("pipeline.runner.fetch_and_build_task_tree")
@patch("pipeline.runner.structure_yonctask_config")
@patch("pipeline.runner.load_config")
def test_empty_notion_tree_aborts(
    mock_load_cfg, mock_struct, mock_fetch,
    mock_p1, mock_p2, mock_p3, mock_p4,
    mock_push, mock_save
):
    mock_load_cfg.return_value = {}
    mock_struct.return_value = {"themes": {}, "modes": [], "priorities": {},
                                 "task_states": {}, "task_types": {}, "wbs_levels": {}}
    mock_fetch.return_value = []  # empty tree

    from pipeline.runner import CycleRunner
    CycleRunner(dry_run=True, skip_split=True).run()

    # No phases should have run
    mock_p1.return_value.run.assert_not_called()
    mock_push.assert_not_called()
    mock_save.assert_not_called()
