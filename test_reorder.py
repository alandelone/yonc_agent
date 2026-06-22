import json
from flow_pipeline import _reorder_state_by_root_rank
with open('data/tasklist_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)
new_state = _reorder_state_by_root_rank(state)
for i, t in enumerate(new_state):
    if t.get('depth') == 0 and any(k in t.get('title', '').lower() for k in ['apparatus learning', 'thesis writing', 'rs_ems', 'rs_sf', 'rstv4']):
        print(f"Index: {i}, Title: {t.get('title')}, Rank: {t.get('timeliner_rank')}")
