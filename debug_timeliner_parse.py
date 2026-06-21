import sys
sys.stdout.reconfigure(encoding='utf-8')

from timeliner_reader import fetch_and_parse_timeliner
from timeliner_sync import _resolve_task_label_for_entry, _resolve_theme_label_for_entry
from timeliner_sync import _build_task_theme_label_index, _build_theme_original_title_index
from state_manager import load_state, STATE_FILE

entries = fetch_and_parse_timeliner(force_live=True)
flat_tasks = load_state(STATE_FILE)
theme_label_index = _build_task_theme_label_index(flat_tasks)
original_title_index = _build_theme_original_title_index(flat_tasks)

for e in entries:
    theme_label = _resolve_theme_label_for_entry(e, theme_label_index)
    resolved_task_label = _resolve_task_label_for_entry(e, theme_label, original_title_index)
    print(f"Entry: project={e.project!r} subproject={e.subproject!r} subtheme={e.colour_subtheme!r}")
    print(f"  theme_label={theme_label!r}")
    print(f"  resolved_task_label={resolved_task_label!r}")
    print(f"  entry.task_title={getattr(e, 'task_title', '')!r}")
    print()
