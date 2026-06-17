import json
with open('data/tasklist_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)
res = []
for t in state:
    title = t.get('title', '')
    if 'SolarMan' in title or 'Thesis' in title:
        res.append(f"{t.get('id')}: {title[0]} -> {title}")
with open('debug_tasklist.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(res))
