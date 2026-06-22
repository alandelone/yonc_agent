import json
from flow_pipeline import build_state_indexes, _root_id
with open('data/tasklist_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)
task_by_id, _ = build_state_indexes(state)
for t in state:
    rid = _root_id(t, task_by_id)
    r_task = task_by_id.get(rid, {})
    if 'rstv4' in r_task.get('title', '').lower():
        if t.get('timeliner_rank') is not None:
            print(f"rstv4 child rank: {t.get('timeliner_rank')}")
