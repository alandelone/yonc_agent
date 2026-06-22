import json
from flow_pipeline import build_timeliner_scope
with open('data/tasklist_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)

# Clear rank to see what it assigns
for t in state:
    t['timeliner_rank'] = 'UNKNOWN'

scoped_ids, rank_by_task_id, scope_entries = build_timeliner_scope(state)

with open('out.txt', 'w', encoding='utf-8') as f:
    for t in state:
        if 'Rs_EMS' in t.get('title',''):
            f.write(t['title'] + ' ' + str(t.get('timeliner_rank')) + '\n')
