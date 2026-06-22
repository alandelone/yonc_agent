import json
with open('data/tasklist_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)
with open('tasklist_dump.txt', 'w', encoding='utf-8') as out:
    for i, t in enumerate(state):
        if t.get('depth') == 0:
            title = t.get('title', '').lower()
            if any(k in title for k in ['apparatus learning', 'thesis writing', 'rs_ems', 'rs_sf', 'rstv4']):
                out.write(f"Index: {i}, Title: {t.get('title')}\n")
                out.write(f"  timeliner_priority: {t.get('timeliner_priority')}\n")
                out.write(f"  timeliner_rank: {t.get('timeliner_rank')}\n")
