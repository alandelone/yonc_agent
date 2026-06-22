import json
with open('data/tasklist_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)
for t in state:
    if t.get('depth') == 0 and 'thesis writing' in t.get('title', '').lower():
        for k, v in t.items():
            if 'timeliner' in k:
                print(f"{k}: {v}")
