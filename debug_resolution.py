import sys
sys.stdout.reconfigure(encoding='utf-8')

from state_manager import load_state, STATE_FILE
from flow_pipeline import _pick_theme_key
from timeliner_sync import _build_theme_original_title_index, _resolve_task_label_for_entry
from timeliner_reader import fetch_and_parse_timeliner

flat_tasks = load_state(STATE_FILE)
title_idx = _build_theme_original_title_index(flat_tasks)

print("=== title_idx contents ===")
for k, v in list(title_idx.items())[:10]:
    print(f"  {k!r} -> {v!r}")

print("\n=== Resolutions ===")
entries = fetch_and_parse_timeliner(force_live=True)
for e in entries:
    label = _resolve_task_label_for_entry(e, e.project, title_idx)
    print(f"subtheme={e.colour_subtheme!r} -> resolved={label!r}")
