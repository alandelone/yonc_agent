import json
from flow_pipeline import build_timeliner_scope
with open('data/tasklist_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)
_, scope_entries, _ = build_timeliner_scope(state)
with open('test_out2.txt', 'w', encoding='utf-8') as out:
    for se in scope_entries:
        out.write(f"subtheme: {se.get('subtheme_key')}, priority: {se.get('priority')}\n")
    for t in state:
        if t.get('depth') == 0 and any(k in t.get('title', '').lower() for k in ['apparatus learning', 'thesis writing', 'rs_ems', 'rs_sf', 'rstv4']):
            out.write(f"Task: {t.get('title')}, matched rank: {t.get('timeliner_rank')}\n")
