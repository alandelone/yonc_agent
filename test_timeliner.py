import json
from flow_pipeline import build_timeliner_scope

d = json.load(open('data/tasklist_state.json', encoding='utf-8'))
scoped_ids, ranks, keys = build_timeliner_scope(d, require_cached_state=True)

daq = [t for t in d if 'DAQ' in t.get('title', '')][0]
print("DAQ timeliner_key:", daq.get("timeliner_key"))
