"""
pipeline/phase4_enrich.py — Phase 4: Level-Based Tag Enrichment.

Per-level rules:
  - Priority auto-tag  → WBS ≤ 2 only, no LLM
  - Task Type          → LLM suggestion from name+description, CLI confirm
  - Modes              → resolve by task-type tree first, else LLM
  - State tagging      → BlockReader-based heuristics + benchmark logging
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from pipeline.context import PipelineContext
from pipeline.block_reader import BlockReader

_p = lambda msg: sys.stdout.buffer.write((msg + "\n").encode("utf-8"))
_DONE_MARK = "\u2705"

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
STATE_BENCHMARK_FILE = os.path.join(DATA_DIR, "state_tagging_benchmark.jsonl")

# Toggle this to enable LLM-assisted state tagging (placeholder for future)
USE_STATE_LLM = False


# ── Priority ───────────────────────────────────────────────────────────────────

def _auto_tag_priority(task: Dict[str, Any], structured_cfg: Dict[str, Any]) -> Optional[str]:
    """
    Return a priority emoji for tasks with WBS ≤ 2.
    Uses the first configured priority option (highest priority).
    Returns None if no priorities are configured.
    """
    priorities = structured_cfg.get("priorities", {})
    if not priorities:
        return None
    # Return the first priority emoji (assumes config is ordered highest → lowest)
    return next(iter(priorities), None)


# ── Task Type ──────────────────────────────────────────────────────────────────

_TASK_TYPE_TREE: Dict[str, List[str]] = {
    # Maps generic task-type labels to keywords found in names / descriptions
    "Research":    ["research", "study", "investigate", "explore", "review"],
    "Build":       ["build", "create", "implement", "develop", "write", "code", "setup"],
    "Test":        ["test", "verify", "validate", "check", "qa"],
    "Communicate": ["meeting", "discuss", "call", "sync", "present", "email"],
    "Admin":       ["plan", "organize", "schedule", "document", "record", "log"],
    "Routine":     ["daily", "weekly", "routine", "habit", "review"],
}


def _infer_type_from_tree(title: str) -> Optional[str]:
    """Keyword-tree match before calling LLM."""
    lower = title.lower()
    for type_label, keywords in _TASK_TYPE_TREE.items():
        if any(k in lower for k in keywords):
            return type_label
    return None


def _prompt_type_confirm(title: str, suggestion: str) -> str:
    """CLI prompt: accept suggestion or enter custom type."""
    _p(f"\n  Task Type for: {title[:60]}")
    _p(f"  Suggestion: [{suggestion}]  — press Enter to accept, or type a custom value:")
    sys.stdout.flush()
    try:
        raw = input("     > ").strip()
    except (EOFError, KeyboardInterrupt):
        return suggestion
    return raw if raw else suggestion


# ── Modes ──────────────────────────────────────────────────────────────────────

def _resolve_mode(
    task: Dict[str, Any],
    task_type: Optional[str],
    structured_cfg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Choose the best mode annotation dict from config:
    1. Match mode by task_type (mode_name contains task type keyword)
    2. Fallback: match by title keywords
    Returns the mode config entry dict (with mode_name, annotations) or None.
    """
    modes: List[Dict[str, Any]] = structured_cfg.get("modes", [])
    if not modes:
        return None

    title = str(task.get("original_notion_title") or task.get("title") or "").lower()

    # 1. By task type
    if task_type:
        for m in modes:
            if task_type.lower() in m.get("mode_name", "").lower():
                return m

    # 2. By title keyword match (same tree)
    for type_label, keywords in _TASK_TYPE_TREE.items():
        if any(k in title for k in keywords):
            for m in modes:
                if type_label.lower() in m.get("mode_name", "").lower():
                    return m

    return None


# ── State Tagging ──────────────────────────────────────────────────────────────

def _determine_state(
    task: Dict[str, Any],
    reader: BlockReader,
    task_states: Dict[str, str],
) -> Optional[str]:
    """
    Heuristic state detection based on block structure:
      - done          → ✅ in title or checked=True
      - in_progress   → has_focus emoji OR child blocks have mixed checked/unchecked
      - blocked       → title contains "blocked" / "waiting" / "依赖"
      - not_started   → no children, no done mark, no signals
      - partial       → some children done, some not

    Returns the state emoji key from task_states config, or None.
    """
    title = str(task.get("original_notion_title") or task.get("title") or "")
    checked = task.get("checked")

    if _DONE_MARK in title or checked is True:
        return _find_state_emoji(task_states, ["done", "✅", "完成"])

    lower = title.lower()
    if any(k in lower for k in ["blocked", "waiting", "依赖", "等待"]):
        return _find_state_emoji(task_states, ["blocked", "阻塞", "🚫"])

    children = reader.direct_children(task)
    if children:
        done_children  = [c for c in children if _DONE_MARK in str(c.get("title", "")) or c.get("checked")]
        total_children = len(children)
        done_count     = len(done_children)

        if done_count == total_children:
            return _find_state_emoji(task_states, ["done", "✅"])
        if done_count > 0:
            return _find_state_emoji(task_states, ["partial", "in_progress", "进行中"])
        return _find_state_emoji(task_states, ["not_started", "未开始", "⬜"])

    return _find_state_emoji(task_states, ["not_started", "未开始", "⬜"])


def _find_state_emoji(task_states: Dict[str, str], hints: List[str]) -> Optional[str]:
    """Return first emoji whose description matches any hint string."""
    for emoji, desc in task_states.items():
        combined = (emoji + " " + desc).lower()
        if any(h.lower() in combined for h in hints):
            return emoji
    return None


def _write_benchmark(
    task: Dict[str, Any],
    state_emoji: Optional[str],
    what_known: str,
    how_clearly: str,
) -> None:
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "block_id": str(task.get("notion_block_id") or task.get("id") or ""),
        "title": str(task.get("original_notion_title") or task.get("title") or ""),
        "wbs_level": task.get("wbs_level"),
        "state_assigned": state_emoji,
        "what_known": what_known,
        "how_clearly": how_clearly,
    }
    with open(STATE_BENCHMARK_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Phase ──────────────────────────────────────────────────────────────────────

class EnrichPhase:
    """
    Phase 4 — Level-based tag enrichment.

    Enrichment matrix:
      WBS 1 → Priority auto-tag + State
      WBS 2 → Priority auto-tag + State
      WBS 3 → Task Type + Mode + State
      WBS 4 → Task Type + Mode + State
      Other → Task Type + Mode (no priority, no state tagging)
    """

    def run(self, ctx: PipelineContext) -> None:
        reader = BlockReader(ctx.flat_state, ctx.task_by_id)
        task_states = ctx.structured_cfg.get("task_states", {})
        interactive = not ctx.dry_run  # only prompt in live mode

        for task in ctx.flat_state:
            block_type = task.get("notion_type") or task.get("type") or ""
            if block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
                continue

            title = str(task.get("original_notion_title") or task.get("title") or "")
            if _DONE_MARK in title:
                continue

            wbs_level = task.get("wbs_level")
            if isinstance(wbs_level, str) and wbs_level.isdigit():
                wbs_level = int(wbs_level)

            tags = task.get("tags") or {}

            # ── Priority (WBS ≤ 2) ────────────────────────────────────────
            if isinstance(wbs_level, int) and wbs_level <= 2:
                if "Priority" not in tags:
                    prio = _auto_tag_priority(task, ctx.structured_cfg)
                    if prio:
                        tags["Priority"] = prio

            # ── Task Type ─────────────────────────────────────────────────
            if isinstance(wbs_level, int) and wbs_level >= 3:
                if "Task Type" not in tags:
                    inferred_type = _infer_type_from_tree(title)

                    if inferred_type is None:
                        # LLM fallback for task type
                        inferred_type = self._llm_task_type(task, ctx)

                    if inferred_type:
                        if interactive:
                            inferred_type = _prompt_type_confirm(title, inferred_type)
                        tags["Task Type"] = inferred_type

            # ── Modes ─────────────────────────────────────────────────────
            if isinstance(wbs_level, int) and wbs_level >= 3:
                if "Modes" not in tags:
                    task_type = tags.get("Task Type")
                    mode_entry = _resolve_mode(task, task_type, ctx.structured_cfg)
                    if mode_entry:
                        tags["Modes"] = mode_entry.get("mode_name", "")

            # ── State ─────────────────────────────────────────────────────
            if "State of Parent Task" not in tags:
                state_emoji = _determine_state(task, reader, task_states)
                what_known = "heuristic"
                how_clearly = "medium"

                if USE_STATE_LLM and state_emoji is None:
                    # Placeholder for future LLM-based state determination
                    pass

                if state_emoji:
                    tags["State of Parent Task"] = state_emoji

                # Benchmark log for every tagged state
                _write_benchmark(task, state_emoji, what_known, how_clearly)

            task["tags"] = tags

    @staticmethod
    def _llm_task_type(task: Dict[str, Any], ctx: PipelineContext) -> Optional[str]:
        """Use existing tag_task() LLM call to get a Task Type suggestion."""
        try:
            from llm_pipeline import tag_task
            from config_reader import clean_task_title

            title = str(task.get("original_notion_title") or task.get("title") or "")
            clean = clean_task_title(title, ctx.structured_cfg)
            llm_config = {"Task Type": ctx.raw_config.get("Task Type", [])}
            result = tag_task(clean, llm_config)
            return result.get("Task Type")
        except Exception as e:
            _p(f"  [Enrich/LLM] Task Type failed: {e}")
            return None
