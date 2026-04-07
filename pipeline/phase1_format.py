"""
pipeline/phase1_format.py — Phase 1: Format Check.

Validates tag structure of every block deterministically (no LLM).
Auto-fixes stale WBS prefixes and accumulates ctx.issues for anything else.
"""
from __future__ import annotations

import re
import sys
from typing import Any, Dict, List, Set

from pipeline.context import PipelineContext


# ── Helpers ────────────────────────────────────────────────────────────────────

_EMOJI_RE = re.compile(
    r"(?:[^\w\s\x00-\x7F|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+"
)


def _extract_leading_emojis(text: str) -> List[str]:
    """Return list of leading emoji tokens from text (before any word chars)."""
    result = []
    pos = 0
    while pos < len(text):
        m = _EMOJI_RE.match(text, pos)
        if m:
            result.append(m.group())
            pos = m.end()
            # skip whitespace between tokens
            while pos < len(text) and text[pos] == " ":
                pos += 1
        else:
            break
    return result


def _strip_stale_wbs_prefix(text: str, wbs_emojis: Set[str]) -> str:
    """Remove leading known WBS emojis from text."""
    cleaned = text
    changed = True
    while changed:
        changed = False
        for e in wbs_emojis:
            updated = re.sub(rf"^\s*{re.escape(e)}\s*", "", cleaned).strip()
            if updated != cleaned:
                cleaned = updated
                changed = True
    return cleaned.strip()


def _collect_wbs_emojis(structured_cfg: Dict[str, Any]) -> Set[str]:
    emojis: Set[str] = set()
    for _, val in structured_cfg.get("wbs_levels", {}).items():
        if isinstance(val, dict):
            raw = val.get("raw") or val.get("emoji", "")
        else:
            raw = str(val)
        m = _EMOJI_RE.search(raw)
        if m:
            emojis.add(m.group())
    return emojis


# ── Phase ──────────────────────────────────────────────────────────────────────

class FormatCheckPhase:
    """
    Phase 1 — deterministic rule-based format validation.

    Checks performed (per block):
    1. Stale WBS emoji prefix on block that has a valid wbs_level → auto-strip
    2. Multiple leading WBS emojis (double-tagged) → auto-strip extras
    3. Block has has_tag_style=True but wbs_level is None (orphan style tag) → warning
    4. Generated (is_generated) to-do that is unchecked — should have been cleaned by
       a previous push-sync; logged as a warning so the runner can decide.
    """

    def run(self, ctx: PipelineContext) -> None:
        wbs_emojis = _collect_wbs_emojis(ctx.structured_cfg)
        _p = lambda msg: sys.stdout.buffer.write((msg + "\n").encode("utf-8"))

        for task in ctx.flat_state:
            block_id = str(task.get("notion_block_id") or task.get("id") or "")
            block_type = task.get("notion_type") or task.get("type") or ""
            original_title = str(
                task.get("original_notion_title") or task.get("title") or ""
            ).strip()

            if not block_id or not block_type:
                continue
            if block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
                continue

            wbs_level = task.get("wbs_level")
            has_tag_style = task.get("has_tag_style", False)
            is_generated = task.get("is_generated", False)

            # ── Check 1: Stale WBS emoji prefix ──────────────────────────────
            leading = _extract_leading_emojis(original_title)
            has_stale_wbs = any(e in wbs_emojis for e in leading)

            if has_stale_wbs:
                fixed_title = _strip_stale_wbs_prefix(original_title, wbs_emojis)
                if fixed_title != original_title:
                    # Auto-fix: update title in local state only (Notion write done by runner)
                    task["title"] = fixed_title
                    task["original_notion_title"] = fixed_title
                    ctx.phase1_fixed_ids.add(block_id)
                    ctx.issues.append({
                        "block_id": block_id,
                        "title": original_title,
                        "issue_type": "stale_wbs_prefix",
                        "auto_fix": True,
                        "detail": f"Stripped stale WBS emoji from '{original_title}' → '{fixed_title}'",
                    })

            # ── Check 2: Multiple WBS emojis ─────────────────────────────────
            wbs_in_leading = [e for e in leading if e in wbs_emojis]
            if len(wbs_in_leading) > 1:
                ctx.issues.append({
                    "block_id": block_id,
                    "title": original_title,
                    "issue_type": "double_wbs_tag",
                    "auto_fix": False,
                    "detail": f"Multiple WBS emojis found: {wbs_in_leading}",
                })
                _p(f"  ⚠ [double_wbs_tag] {original_title[:60]}")

            # ── Check 3: Orphan tag style ─────────────────────────────────────
            if has_tag_style and wbs_level is None:
                ctx.issues.append({
                    "block_id": block_id,
                    "title": original_title,
                    "issue_type": "orphan_tag_style",
                    "auto_fix": False,
                    "detail": "Block has bold/code formatting but no wbs_level.",
                })

            # ── Check 4: Stale unchecked generated to-do ─────────────────────
            if (
                is_generated
                and block_type in ["to_do", "todo"]
                and task.get("checked") is False
            ):
                ctx.issues.append({
                    "block_id": block_id,
                    "title": original_title,
                    "issue_type": "stale_generated_todo",
                    "auto_fix": False,
                    "detail": "Unchecked generated to-do survived previous cycle; should be deleted.",
                })
                _p(f"  ⚠ [stale_generated_todo] {original_title[:60]}")
