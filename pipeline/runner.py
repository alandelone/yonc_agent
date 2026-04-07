"""
pipeline/runner.py — CycleRunner: orchestrates all 4 pipeline phases.

Usage (from main.py):
    runner = CycleRunner(dry_run=False, skip_split=False)
    runner.run()
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List

from config_reader import load_config, structure_yonctask_config
from task_reader import fetch_and_build_task_tree
from state_manager import flatten_tree, load_state, save_state, merge_states, STATE_FILE, CURRENT_STATE_FILE
from sync_engine import sync_from_notion, push_tags_to_notion

from pipeline.context import PipelineContext
from pipeline.phase1_format import FormatCheckPhase
from pipeline.phase2_wbs import WBSTagPhase
from pipeline.phase3_split import SplitTaskPhase
from pipeline.phase4_enrich import EnrichPhase


class CycleRunner:
    """
    Runs the full 4-phase processing cycle against the Notion task tree.

    Phases run in strict order:
      1. FormatCheckPhase  — detect + auto-fix tag format violations
      2. WBSTagPhase       — assign WBS levels with block context
      3. SplitTaskPhase    — interactive CLI task decomposition
      4. EnrichPhase       — priority, type, mode, state tagging

    After all phases, tags are pushed back to Notion (unless dry_run=True).
    """

    def __init__(self, dry_run: bool = False, skip_split: bool = False):
        self.dry_run = dry_run
        self.skip_split = skip_split

    def run(self) -> None:
        sys.stdout.reconfigure(encoding="utf-8")
        _p = lambda msg: sys.stdout.buffer.write((msg + "\n").encode("utf-8"))

        _p("=" * 60)
        _p("  YONC AGENT — Cycle Run" + (" [DRY-RUN]" if self.dry_run else ""))
        _p("=" * 60)

        # ── 0. Bootstrap ─────────────────────────────────────────────────────
        _p("\n[0/4] Bootstrapping: loading config and Notion tree...")
        raw_config = load_config()
        structured_cfg = structure_yonctask_config(raw_config)

        notion_tree = fetch_and_build_task_tree()
        if not notion_tree:
            _p("  ✗ No tasks found in Notion. Aborting cycle.")
            return

        flat_notion = flatten_tree(notion_tree)
        working_state = sync_from_notion(flat_notion)
        flat_state = merge_states(notion_tree, working_state)

        # Load timeliner entries for Phase 3
        timeliner_entries: List[Any] = []
        try:
            from timeliner_reader import fetch_and_parse_timeliner
            timeliner_entries = fetch_and_parse_timeliner()
        except Exception as e:
            _p(f"  ⚠ Could not load timeliner entries: {e}")

        ctx = PipelineContext(
            raw_config=raw_config,
            structured_cfg=structured_cfg,
            notion_tree=notion_tree,
            flat_state=flat_state,
            timeliner_entries=timeliner_entries,
            dry_run=self.dry_run,
            skip_split=self.skip_split,
        )
        ctx.build_task_by_id()

        # ── Phase 1: Format Check ─────────────────────────────────────────────
        _p("\n[1/4] Phase 1 — Format Check...")
        FormatCheckPhase().run(ctx)
        auto_fixed = sum(1 for i in ctx.issues if i.get("auto_fix"))
        warnings   = sum(1 for i in ctx.issues if not i.get("auto_fix"))
        _p(f"  ✓ {auto_fixed} auto-fixed | {warnings} warnings")

        # ── Phase 2: WBS Tagging ──────────────────────────────────────────────
        _p("\n[2/4] Phase 2 — WBS Tagging...")
        WBSTagPhase().run(ctx)
        tagged = sum(1 for t in ctx.flat_state if t.get("wbs_level"))
        _p(f"  ✓ {tagged} blocks have a WBS level assigned")

        # ── Phase 3: Split Tasking ────────────────────────────────────────────
        if self.skip_split:
            _p("\n[3/4] Phase 3 — Split Tasking... SKIPPED (--no-split)")
        else:
            _p("\n[3/4] Phase 3 — Split Tasking (interactive)...")
            SplitTaskPhase().run(ctx)

        # ── Phase 4: Enrichment ───────────────────────────────────────────────
        _p("\n[4/4] Phase 4 — Level-Based Enrichment...")
        EnrichPhase().run(ctx)
        _p("  ✓ Enrichment complete")

        # ── Push + Save ───────────────────────────────────────────────────────
        if self.dry_run:
            _p("\n[DRY-RUN] No changes written to Notion or disk.")
        else:
            _p("\nPushing tags to Notion...")
            push_tags_to_notion(ctx.flat_state, raw_config)

            clean_state = [t for t in ctx.flat_state if not t.get("deleted")]
            save_state(clean_state, STATE_FILE)
            _p(f"State saved ({len(clean_state)} tasks).")

        _p("\n" + "=" * 60)
        _p("  Cycle complete.")
        _p("=" * 60 + "\n")
