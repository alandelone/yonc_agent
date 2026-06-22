import sys
sys.stdout.reconfigure(encoding='utf-8')

from timeliner_reader import fetch_and_parse_timeliner
entries = fetch_and_parse_timeliner(force_live=True)

for e in entries:
    print(f"project={e.project!r} subproject={e.subproject!r} subtheme={e.colour_subtheme!r} task_title={getattr(e, 'task_title', '')!r}")
