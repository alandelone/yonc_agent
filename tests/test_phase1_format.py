"""
tests/test_phase1_format.py — Unit tests for pipeline.phase1_format.FormatCheckPhase
"""
import pytest
from pipeline.context import PipelineContext
from pipeline.phase1_format import FormatCheckPhase, _strip_stale_wbs_prefix, _collect_wbs_emojis


# ── Shared config fixture ──────────────────────────────────────────────────────

STRUCTURED_CFG = {
    "themes": {
        "DZao": {"sub_themes": ["3dpF"], "color": "blue"},
    },
    "modes": [],
    "priorities": {},
    "task_states": {},
    "task_types": {},
    "wbs_levels": {
        1: {"emoji": "🎯", "label": "Level 1", "raw": "🎯 | Level 1"},
        2: {"emoji": "📦", "label": "Level 2", "raw": "📦 | Level 2"},
        3: {"emoji": "🔧", "label": "Level 3", "raw": "🔧 | Level 3"},
        4: {"emoji": "⚡", "label": "Level 4", "raw": "⚡ | Level 4"},
    },
}

RAW_CONFIG: dict = {}


def make_ctx(flat_state):
    ctx = PipelineContext(
        raw_config=RAW_CONFIG,
        structured_cfg=STRUCTURED_CFG,
        notion_tree=[],
        flat_state=flat_state,
    )
    ctx.build_task_by_id()
    return ctx


def make_task(id_, title, block_type="bulleted_list_item", wbs_level=None,
              has_tag_style=False, is_generated=False, checked=None):
    return {
        "id": id_,
        "notion_block_id": id_,
        "parent_id": None,
        "title": title,
        "original_notion_title": title,
        "type": block_type,
        "notion_type": block_type,
        "wbs_level": wbs_level,
        "has_tag_style": has_tag_style,
        "is_generated": is_generated,
        "checked": checked,
        "tags": {},
    }


# ── _strip_stale_wbs_prefix helper ────────────────────────────────────────────

def test_strip_known_wbs_emoji():
    wbs_emojis = {"🎯", "📦"}
    result = _strip_stale_wbs_prefix("🎯 My Task Title", wbs_emojis)
    assert result == "My Task Title"

def test_strip_multiple_wbs_emojis():
    wbs_emojis = {"🎯", "📦"}
    result = _strip_stale_wbs_prefix("🎯 📦 My Task", wbs_emojis)
    assert result == "My Task"

def test_no_strip_when_no_wbs_emoji():
    wbs_emojis = {"🎯"}
    result = _strip_stale_wbs_prefix("✅ Done task", wbs_emojis)
    assert result == "✅ Done task"


# ── _collect_wbs_emojis ───────────────────────────────────────────────────────

def test_collect_wbs_emojis():
    emojis = _collect_wbs_emojis(STRUCTURED_CFG)
    assert "🎯" in emojis
    assert "📦" in emojis
    assert "🔧" in emojis
    assert "⚡" in emojis


# ── FormatCheckPhase: stale WBS prefix auto-fix ───────────────────────────────

def test_stale_wbs_prefix_auto_fixed():
    task = make_task("t1", "🎯 My Task", wbs_level=1)
    ctx = make_ctx([task])
    FormatCheckPhase().run(ctx)

    # Title should be stripped in local state
    assert task["title"] == "My Task"
    assert task["original_notion_title"] == "My Task"
    assert "t1" in ctx.phase1_fixed_ids

    # Issue should be recorded as auto_fix=True
    stale_issues = [i for i in ctx.issues if i["issue_type"] == "stale_wbs_prefix"]
    assert len(stale_issues) == 1
    assert stale_issues[0]["auto_fix"] is True


def test_clean_task_no_issues():
    task = make_task("t2", "Build the widget", wbs_level=3)
    ctx = make_ctx([task])
    FormatCheckPhase().run(ctx)

    assert ctx.issues == []
    assert task["title"] == "Build the widget"  # unchanged


def test_paragraph_block_skipped():
    task = make_task("t3", "🎯 Section heading", block_type="paragraph")
    ctx = make_ctx([task])
    FormatCheckPhase().run(ctx)

    # Paragraph blocks are skipped entirely
    assert ctx.issues == []
    assert task["title"] == "🎯 Section heading"  # not stripped


# ── FormatCheckPhase: orphan tag style ───────────────────────────────────────

def test_orphan_tag_style_issue():
    task = make_task("t4", "My styled task", wbs_level=None, has_tag_style=True)
    ctx = make_ctx([task])
    FormatCheckPhase().run(ctx)

    orphan_issues = [i for i in ctx.issues if i["issue_type"] == "orphan_tag_style"]
    assert len(orphan_issues) == 1
    assert orphan_issues[0]["auto_fix"] is False


def test_no_orphan_when_wbs_present():
    task = make_task("t5", "My styled task", wbs_level=2, has_tag_style=True)
    ctx = make_ctx([task])
    FormatCheckPhase().run(ctx)

    orphan_issues = [i for i in ctx.issues if i["issue_type"] == "orphan_tag_style"]
    assert len(orphan_issues) == 0


# ── FormatCheckPhase: stale generated to-do ──────────────────────────────────

def test_stale_generated_todo_issue():
    task = make_task(
        "t6", "Generated subtask", block_type="to_do",
        is_generated=True, checked=False
    )
    ctx = make_ctx([task])
    FormatCheckPhase().run(ctx)

    stale_gen = [i for i in ctx.issues if i["issue_type"] == "stale_generated_todo"]
    assert len(stale_gen) == 1
    assert stale_gen[0]["auto_fix"] is False


def test_checked_generated_todo_not_flagged():
    task = make_task(
        "t7", "Accepted subtask", block_type="to_do",
        is_generated=True, checked=True
    )
    ctx = make_ctx([task])
    FormatCheckPhase().run(ctx)

    stale_gen = [i for i in ctx.issues if i["issue_type"] == "stale_generated_todo"]
    assert len(stale_gen) == 0


# ── Multiple tasks — isolation ────────────────────────────────────────────────

def test_multiple_tasks_isolated():
    tasks = [
        make_task("m1", "🎯 Stale prefix task", wbs_level=1),
        make_task("m2", "Clean task",           wbs_level=2),
        make_task("m3", "🎯 Another stale",     wbs_level=1),
    ]
    ctx = make_ctx(tasks)
    FormatCheckPhase().run(ctx)

    stale = [i for i in ctx.issues if i["issue_type"] == "stale_wbs_prefix"]
    assert len(stale) == 2
    # Clean task untouched
    assert tasks[1]["title"] == "Clean task"
