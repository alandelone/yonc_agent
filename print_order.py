import json
with open('data/current_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)
with open('order_out.txt', 'w', encoding='utf-8') as out:
    for i, t in enumerate(state):
        if t.get('depth') == 0:
            title = t.get('title', '').lower()
            if any(k in title for k in ['apparatus learning', 'thesis writing', 'rs_ems', 'rs_sf', 'rstv4']):
                out.write(f"Index: {i}, Title: {t.get('title')}\n")
