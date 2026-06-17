import json
state = json.load(open('data/current_state.json', encoding='utf-8'))
res = []
for t in state:
    title = t.get('title', '')
    if 'SolarMan' in title or 'Thesis' in title:
        res.append(f"{t.get('id')}: Depth {t.get('depth')}")
with open('debug_depth.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(res))
