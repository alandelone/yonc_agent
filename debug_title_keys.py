import sys
import json
sys.stdout.reconfigure(encoding='utf-8')

from state_manager import load_state, STATE_FILE
from flow_pipeline import _timeliner_entry_title_match_keys, _pick_theme_key
flat_tasks = load_state(STATE_FILE)

print("=== Task Details from tasklist_state.json ===")
for t in flat_tasks:
    title = str(t.get("original_notion_title", "")) or str(t.get("title", ""))
    if "solarman" in title.lower() or "phd logic" in title.lower():
        theme_key = _pick_theme_key(t).lower()
        match_keys = _timeliner_entry_title_match_keys(t)
        print(f"Title: {title!r}")
        print(f"  theme_key: {theme_key!r}")
        print(f"  match_keys: {match_keys}")
        print()
