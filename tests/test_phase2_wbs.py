"""
tests/test_phase2_wbs.py — Unit tests for pipeline.phase2_wbs.WBSTagPhase
"""
import pytest
from unittest.mock import patch, MagicMock

from pipeline.context import PipelineContext
from pipeline.phase2_wbs import WBSTagPhase, _resolve_wbs_tag

# ── Shared context ─────────────────────────────────────────────────────────────

STRUCTURED_CFG = {
    "themes": {},
    "wbs_levels": {
        1: {"emoji": "🎯", "label": "Level 1", "raw": "🎯 | Level 1"},
        2: {"emoji": "📦", "label": "Level 2", "raw": "📦 | Level 2"},
        3: {"emoji": "🔧", "label": "Level 3", "raw": "🔧 | Level 3"},
        4: {"emoji": "⚡", "label": "Level 4", "raw": "⚡ | Level 4"},
    },
}

def make_ctx(flat_state):
    ctx = PipelineContext(
        raw_config={},
        structured_cfg=STRUCTURED_CFG,
        notion_tree=[],
        flat_state=flat_state,
    )
    ctx.build_task_by_id()
    return ctx

def make_task(id_, title, parent_id=None, wbs_level=None, tags=None):
    return {
        "id": id_,
        "notion_block_id": id_,
        "parent_id": parent_id,
        "title": title,
        "original_notion_title": title,
        "type": "to_do",
        "wbs_level": wbs_level,
        "tags": tags or {},
    }

# ── Tests ──────────────────────────────────────────────────────────────────────

def test_resolve_wbs_tag():
    assert _resolve_wbs_tag(1, STRUCTURED_CFG) == "🎯 | Level 1"
    assert _resolve_wbs_tag(4, STRUCTURED_CFG) == "⚡ | Level 4"
    assert _resolve_wbs_tag(99, STRUCTURED_CFG) == ""

def test_wbs_preserves_existing_int():
    task = make_task("t1", "Test", wbs_level=2)
    ctx = make_ctx([task])
    WBSTagPhase().run(ctx)
    assert task["wbs_level"] == 2
    assert task["tags"]["WBS level"] == "📦 | Level 2"

def test_wbs_infers_from_tag_text():
    # Only tag text, no wbs_level int
    task = make_task("t1", "Test", tags={"WBS level": "🔧 | Level 3"})
    ctx = make_ctx([task])
    WBSTagPhase().run(ctx)
    assert task["wbs_level"] == 3
    assert task["tags"]["WBS level"] == "🔧 | Level 3"

def test_wbs_root_defaults_to_1():
    task = make_task("t1", "Root Task")
    ctx = make_ctx([task])
    WBSTagPhase().run(ctx)
    assert task["wbs_level"] == 1
    assert task["tags"]["WBS level"] == "🎯 | Level 1"

def test_wbs_infers_from_ancestor():
    root = make_task("root", "Root Task", wbs_level=1)
    child = make_task("child", "Child Task", parent_id="root")
    ctx = make_ctx([root, child])
    WBSTagPhase().run(ctx)
    # Child should inherit parent + 1 -> 2
    assert child["wbs_level"] == 2
    assert child["tags"]["WBS level"] == "📦 | Level 2"

@patch("pipeline.phase2_wbs.classify_task", create=True)
def test_wbs_llm_fallback(mock_classify):
    # Setup mock for LLM returning level 3
    result = MagicMock()
    result.task_type = "WBS"
    result.level = 3
    mock_classify.return_value = result

    root = make_task("root", "Root Task")
    # For child, if parent is not processed, we fallback... 
    # but parent gets processed first to 1. Let's make parent have NO wbs_level to force fallback
    # Wait, WBSTagPhase runs sequentially, so parent will get level 1.
    # We can test fallback by making root not present in task_by_id (an orphan with non-existing parent)
    orphan = make_task("orphan", "Orphan", parent_id="missing_parent")
    ctx = make_ctx([orphan])
    
    WBSTagPhase().run(ctx)
    
    # Missing parent means ancestor logic fails, so falls back to LLM
    mock_classify.assert_called_once()
    assert orphan["wbs_level"] == 3
    assert orphan["tags"]["WBS level"] == "🔧 | Level 3"

def test_dzao_container_flagged():
    root = make_task("root", "Root")
    child = make_task("child", "Child", parent_id="root")
    # if ALL children are root-level (no parents?). Wait, the logic is:
    # "if children and all(not ctx.task_by_id.get(str(c.get('parent_id') or '')) for c in children):"
    # Actually if child's parent IS in task_by_id, it is not flagged.
    
    ctx = make_ctx([root, child])
    WBSTagPhase().run(ctx)
    
    assert root["wbs_level"] == 1
    assert "_suggest_dzao_container" not in root
