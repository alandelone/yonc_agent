"""
pipeline/phase2_wbs.py — Phase 2: WBS Tagging.

Assigns WBS levels to blocks using:
- Rule: new root blocks (no parents) default to WBS 1
- BlockReader for structural context (ancestors, children, toggle content)
- LLM classify_task() from llm_pipeline.py when no WBS yet exists
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from pipeline.context import PipelineContext
from pipeline.block_reader import BlockReader


_DONE_MARK = "\u2705"


def _resolve_wbs_tag(level: int, structured_cfg: Dict[str, Any]) -> str:
    """Return the raw WBS emoji tag string for a given integer level."""
    levels = structured_cfg.get("wbs_levels", {})
    entry = levels.get(level)
    if isinstance(entry, dict):
        return entry.get("raw") or entry.get("emoji", "")
    for key, val in levels.items():
        label = val.get("label", "") if isinstance(val, dict) else str(val)
        if str(level) in str(key) or str(level) in label:
            if isinstance(val, dict):
                return val.get("raw") or val.get("emoji", "")
            return str(val)
    return ""


def _infer_wbs_from_existing_tag(tags: Dict[str, Any], structured_cfg: Dict[str, Any]) -> Optional[int]:
    """Try to derive integer WBS level from an existing tags["WBS level"] string."""
    import re
    wbs_text = str(tags.get("WBS level", "")).strip()
    if not wbs_text:
        return None
    direct = re.search(r"([1-4])", wbs_text)
    if direct:
        return int(direct.group(1))
    return None


class WBSTagPhase:
    """
    Phase 2 — Assign WBS levels with block context enrichment.

    Logic per block:
      1. Already has wbs_level int → keep (respect existing)
      2. Has tags["WBS level"] text → decode to int
      3. Is a root block (no parent in the tree) → default WBS 1
         - If all children also appear root-level → flag for DZaoSpaceV1 container
      4. Has ancestors with WBS levels → infer as parent_level + 1 (capped at 4)
      5. Fall back to LLM classify_task() with BlockReader context injected
    """

    def run(self, ctx: PipelineContext) -> None:
        reader = BlockReader(ctx.flat_state, ctx.task_by_id)
        _p = lambda msg: sys.stdout.buffer.write((msg + "\n").encode("utf-8"))

        # Build parent_id set (any task that has children)
        parent_ids = {
            str(t.get("parent_id") or "")
            for t in ctx.flat_state
            if t.get("parent_id")
        }

        for task in ctx.flat_state:
            block_id = str(task.get("notion_block_id") or task.get("id") or "")
            block_type = task.get("notion_type") or task.get("type") or ""

            # Skip structural/non-content blocks
            if not block_id or block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
                continue

            # Skip done tasks
            title = str(task.get("original_notion_title") or task.get("title") or "")
            if _DONE_MARK in title:
                continue

            tags = task.get("tags") or {}

            # ── 1. Already has int wbs_level → honour it ──────────────────
            existing = task.get("wbs_level")
            if isinstance(existing, str) and existing.isdigit():
                existing = int(existing)
                task["wbs_level"] = existing
            if isinstance(existing, int):
                self._write_wbs_tag(task, existing, ctx.structured_cfg)
                continue

            # ── 2. Tags["WBS level"] text → decode ───────────────────────
            inferred = _infer_wbs_from_existing_tag(tags, ctx.structured_cfg)
            if isinstance(inferred, int):
                task["wbs_level"] = inferred
                self._write_wbs_tag(task, inferred, ctx.structured_cfg)
                continue

            # ── 3. Root block (no parent in task_by_id) → WBS 1 ──────────
            pid = str(task.get("parent_id") or "")
            parent_in_tree = bool(pid and ctx.task_by_id.get(pid))
            if not parent_in_tree:
                task["wbs_level"] = 1
                self._write_wbs_tag(task, 1, ctx.structured_cfg)
                # Check if children need DZaoSpaceV1 container flagging
                children = reader.direct_children(task)
                if children and all(not ctx.task_by_id.get(str(c.get("parent_id") or "")) for c in children):
                    task["_suggest_dzao_container"] = True
                    _p(f"  [WBS] Root block with unparented children → flag DZaoSpaceV1: {title[:50]}")
                continue

            # ── 4. Infer from ancestor WBS levels ─────────────────────────
            ancestors = reader.ancestors(task)
            ancestor_level = None
            for anc in ancestors:
                anc_level = anc.get("wbs_level")
                if isinstance(anc_level, int):
                    ancestor_level = anc_level
                    break
            if isinstance(ancestor_level, int):
                inferred_level = min(ancestor_level + 1, 4)
                task["wbs_level"] = inferred_level
                self._write_wbs_tag(task, inferred_level, ctx.structured_cfg)
                continue

            # ── 5. LLM fallback with BlockReader context ──────────────────
            try:
                from llm_pipeline import classify_task
                from config_reader import clean_task_title

                block_summary = reader.summary(task)
                toggle_ctx = block_summary.get("toggle_summary") or ""
                parent_ctx = " > ".join(block_summary.get("parent_titles", [])[:3])
                clean = clean_task_title(title, ctx.structured_cfg)
                prompt_title = f"[parents: {parent_ctx}] {clean}" if parent_ctx else clean

                _p(f"  [WBS/LLM] Classifying: {title[:50]}")
                cls_result = classify_task(prompt_title)
                wbs_level = 1 if cls_result.task_type == "OKR" else cls_result.level
                task["wbs_level"] = wbs_level
                self._write_wbs_tag(task, wbs_level, ctx.structured_cfg)
            except Exception as e:
                _p(f"  [WBS] LLM classification failed for {block_id}: {e}")

    @staticmethod
    def _write_wbs_tag(task: Dict[str, Any], level: int, structured_cfg: Dict[str, Any]) -> None:
        """Write wbs_tag string into task["tags"]["WBS level"]."""
        wbs_tag = _resolve_wbs_tag(level, structured_cfg)
        if wbs_tag:
            tags = task.get("tags") or {}
            tags["WBS level"] = wbs_tag
            task["tags"] = tags
