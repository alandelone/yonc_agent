"""
pipeline/phase3_split.py — Phase 3: Interactive Task Splitting.

Processes leaf blocks stage-by-stage:
  - Reads timeliner entries to order by WBS Lv1 priority
  - Classifies each block's split state: free / suggesting / waiting_review
  - Presents LLM-generated subtask suggestions via CLI (accept/reject/skip)
  - Pushes accepted subtasks to Notion
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from pipeline.context import PipelineContext
from pipeline.block_reader import BlockReader

_DONE_MARK = "\u2705"
_p = lambda msg: sys.stdout.buffer.write((msg + "\n").encode("utf-8"))


# ── Split-state classification ─────────────────────────────────────────────────

def classify_split_state(task: Dict[str, Any], children: List[Dict[str, Any]]) -> str:
    """
    Returns one of:
      'free'          — no children, not done, ready to split
      'suggesting'    — has generated (unchecked) to-do children pending user review
      'waiting_review'— has generated children that are checked (selected by user)
      'has_children'  — has non-generated children (already split by human or previous cycle)
      'done'          — task is marked done; skip
    """
    title = str(task.get("original_notion_title") or task.get("title") or "")
    if _DONE_MARK in title or task.get("checked"):
        return "done"

    if not children:
        return "free"

    generated = [c for c in children if c.get("is_generated")]
    human     = [c for c in children if not c.get("is_generated")]

    if human:
        return "has_children"

    if generated:
        checked_gen   = [c for c in generated if c.get("checked") is True]
        unchecked_gen = [c for c in generated if c.get("checked") is False]
        if checked_gen:
            return "waiting_review"
        if unchecked_gen:
            return "suggesting"

    return "free"


# ── Timeliner priority ordering ────────────────────────────────────────────────

def _timeliner_priority_map(timeliner_entries: List[Any]) -> Dict[str, int]:
    """
    Return a dict mapping subtheme name → priority rank (lower = higher priority)
    derived from the order of timeliner rows.
    """
    return {
        str(getattr(e, "colour_subtheme", "") or "").strip(): i
        for i, e in enumerate(timeliner_entries)
    }


def _task_priority(task: Dict[str, Any], priority_map: Dict[str, int]) -> int:
    """Score a task by its closest timeliner subtheme priority (lower = higher)."""
    theme_str = str((task.get("tags") or {}).get("Task Theme with colour", "")).strip()
    for subtheme, rank in priority_map.items():
        if subtheme and subtheme in theme_str:
            return rank
    return 9999  # unordered → last


# ── CLI interaction ────────────────────────────────────────────────────────────

def _prompt_accept(title: str, suggestions: List[str]) -> str:
    """
    Display suggestion and prompt user: [a]ccept / [r]eject / [s]kip
    Returns 'accept', 'reject', or 'skip'.
    """
    sys.stdout.flush()
    _p(f"\n  ┌─ Suggestion for: {title[:70]}")
    for i, s in enumerate(suggestions, 1):
        _p(f"  │  {i}. {s}")
    _p("  └─ [a] Accept  [r] Reject  [s] Skip")
    sys.stdout.flush()
    while True:
        try:
            raw = input("     > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "skip"
        if raw in ("a", "accept"):
            return "accept"
        if raw in ("r", "reject"):
            return "reject"
        if raw in ("s", "skip", ""):
            return "skip"
        _p("     Please enter a, r, or s.")


# ── Phase ──────────────────────────────────────────────────────────────────────

class SplitTaskPhase:
    """
    Phase 3 — Stage-by-stage interactive task decomposition.

    For each eligible block (leaf, not done, wbs_level ≤ 3):
      1. Classify split state
      2. If 'free': generate LLM suggestions and prompt CLI
      3. If 'suggesting': show existing suggestions and re-prompt
      4. If 'waiting_review': confirm and push to Notion
      5. If 'has_children' / 'done': skip
    """

    def run(self, ctx: PipelineContext) -> None:
        reader = BlockReader(ctx.flat_state, ctx.task_by_id)
        priority_map = _timeliner_priority_map(ctx.timeliner_entries)

        # Collect eligible tasks: leaf or suggesting/waiting_review, wbs ≤ 3
        candidates = []
        for task in ctx.flat_state:
            block_type = task.get("notion_type") or task.get("type") or ""
            if block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
                continue
            wbs = task.get("wbs_level")
            if isinstance(wbs, int) and wbs > 3:
                continue
            title = str(task.get("original_notion_title") or task.get("title") or "")
            if _DONE_MARK in title:
                continue
            candidates.append(task)

        # Sort by timeliner priority
        candidates.sort(key=lambda t: _task_priority(t, priority_map))

        accepted = rejected = skipped = 0

        for task in candidates:
            block_id = str(task.get("notion_block_id") or task.get("id") or "")
            title = str(task.get("original_notion_title") or task.get("title") or "")
            children = reader.direct_children(task)
            state = classify_split_state(task, children)

            if state in ("done", "has_children"):
                continue

            wbs_level = task.get("wbs_level") or 0

            if state == "free":
                # Generate suggestions via LLM
                suggestions = self._generate(task, ctx, reader)
                if not suggestions:
                    continue
                decision = _prompt_accept(title, suggestions)
                if decision == "accept":
                    self._push(block_id, suggestions, task, ctx)
                    accepted += 1
                    # Tag parent block's WBS level if not already set
                    self._tag_parent_wbs(task, wbs_level, ctx)
                elif decision == "reject":
                    rejected += 1
                else:
                    skipped += 1

            elif state == "suggesting":
                gen_children = [c for c in children if c.get("is_generated")]
                suggestions = [
                    str(c.get("original_notion_title") or c.get("title") or "")
                    for c in gen_children
                ]
                decision = _prompt_accept(f"[existing suggestions] {title}", suggestions)
                if decision == "accept":
                    # Mark all as checked in local state — push_tags_to_notion handles convert
                    for c in gen_children:
                        c["checked"] = True
                    accepted += 1
                elif decision == "reject":
                    for c in gen_children:
                        c["_mark_delete"] = True
                    rejected += 1
                else:
                    skipped += 1

            elif state == "waiting_review":
                # Already reviewed subset; just confirm
                checked_gen = [c for c in children if c.get("is_generated") and c.get("checked")]
                _p(f"\n  ✓ [waiting_review] {len(checked_gen)} selected subtasks for: {title[:60]}")
                # Will be handled by sync_engine push_tags_to_notion (convert checked to toggle)
                accepted += 1

        _p(f"\n  Split tasking: {accepted} accepted, {rejected} rejected, {skipped} skipped.")

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _generate(
        self,
        task: Dict[str, Any],
        ctx: PipelineContext,
        reader: BlockReader,
    ) -> List[str]:
        """Call llm_pipeline.split_task() with block context."""
        from llm_pipeline import split_task
        from config_reader import clean_task_title

        title = str(task.get("original_notion_title") or task.get("title") or "")
        clean = clean_task_title(title, ctx.structured_cfg)

        # Build context string from ancestors
        summary = reader.summary(task)
        parent_ctx = " > ".join(summary.get("parent_titles", [])[:3])
        toggle_ctx = summary.get("toggle_summary") or ""
        context_str = " | ".join(filter(None, [parent_ctx, toggle_ctx]))

        try:
            return split_task(clean, context=context_str)
        except Exception as e:
            _p(f"  [Split/LLM] Failed for '{clean[:40]}': {e}")
            return []

    def _push(
        self,
        parent_block_id: str,
        subtasks: List[str],
        parent_task: Dict[str, Any],
        ctx: PipelineContext,
    ) -> None:
        """Push accepted subtasks as generated to-do blocks to Notion."""
        if ctx.dry_run:
            _p(f"  [DRY-RUN] Would push {len(subtasks)} subtasks to {parent_block_id}")
            return

        from sync_engine import push_subtasks_to_notion

        tags = parent_task.get("tags") or {}
        theme_str = str(tags.get("Task Theme with colour", "")).strip()

        # Try to resolve parent_theme and color
        parent_theme: Optional[str] = None
        parent_theme_color: str = "default"
        for t_name, t_data in ctx.structured_cfg.get("themes", {}).items():
            if t_name in theme_str:
                parent_theme = t_name
                parent_theme_color = t_data.get("color", "default")
                break

        try:
            push_subtasks_to_notion(
                parent_block_id, subtasks, parent_theme, parent_theme_color
            )
            _p(f"  ✓ Pushed {len(subtasks)} subtasks to Notion for: {parent_block_id}")
        except Exception as e:
            _p(f"  ✗ Push failed for {parent_block_id}: {e}")

    def _tag_parent_wbs(
        self, task: Dict[str, Any], child_wbs: int, ctx: PipelineContext
    ) -> None:
        """If the parent block has no WBS level, tag it as child_wbs - 1."""
        pid = str(task.get("parent_id") or "")
        parent = ctx.task_by_id.get(pid)
        if not parent:
            return
        if not isinstance(parent.get("wbs_level"), int):
            parent_level = max(1, child_wbs - 1)
            parent["wbs_level"] = parent_level
            from pipeline.phase2_wbs import _resolve_wbs_tag, _write_wbs_tag
            from pipeline.phase2_wbs import WBSTagPhase
            WBSTagPhase._write_wbs_tag(parent, parent_level, ctx.structured_cfg)
