"""
pipeline/context.py — Shared pipeline context dataclass.

PipelineContext is created once by the CycleRunner and passed through
every phase. Phases read from it and mutate `flat_state` and `issues` in place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PipelineContext:
    # ── Configuration ────────────────────────────────────────────────────────
    raw_config: Dict[str, List[Any]]
    """Raw config dict loaded from the YoncTask config Notion page."""

    structured_cfg: Dict[str, Any]
    """Parsed structured config (themes, modes, wbs_levels, etc.)."""

    # ── Task data ────────────────────────────────────────────────────────────
    notion_tree: List[Dict[str, Any]]
    """Hierarchical tree of blocks as returned by fetch_and_build_task_tree()."""

    flat_state: List[Dict[str, Any]]
    """Flat list of task dicts (merged Notion + local state). Mutated in place by phases."""

    task_by_id: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    """Lookup map: notion_block_id → task dict. Built once by runner after flat_state is set."""

    # ── Timeliner data ────────────────────────────────────────────────────────
    timeliner_entries: List[Any] = field(default_factory=list)
    """Parsed timeliner rows (TimelineEntry objects) used by Phase 3 for priority ordering."""

    # ── Metadata ─────────────────────────────────────────────────────────────
    dry_run: bool = False
    """If True, no writes are made to Notion or disk."""

    skip_split: bool = False
    """If True, Phase 3 (SplitTaskPhase) is skipped entirely."""

    # ── Cross-phase communication ─────────────────────────────────────────────
    issues: List[Dict[str, Any]] = field(default_factory=list)
    """
    Issues accumulated by Phase 1 (FormatCheckPhase).
    Schema per issue:
        {
            "block_id": str,
            "title": str,
            "issue_type": str,   # e.g. "stale_wbs_prefix", "unknown_emoji", "bad_tag_order"
            "auto_fix": bool,    # True = already fixed inline by Phase 1
            "detail": str,       # human-readable description
        }
    """

    phase1_fixed_ids: set = field(default_factory=set)
    """Block IDs that Phase 1 auto-fixed. Phase 2+ can skip re-processing their titles."""

    def build_task_by_id(self) -> None:
        """Populate task_by_id from flat_state. Call after flat_state is ready."""
        self.task_by_id = {
            str(t.get("notion_block_id") or t.get("id") or ""): t
            for t in self.flat_state
            if t.get("notion_block_id") or t.get("id")
        }

    def children_of(self, block_id: str) -> List[Dict[str, Any]]:
        """Return direct children of block_id from flat_state."""
        return [
            t for t in self.flat_state
            if str(t.get("parent_id") or "") == block_id
        ]

    def parent_of(self, task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return direct parent task dict, or None if root."""
        pid = str(task.get("parent_id") or "")
        return self.task_by_id.get(pid)
