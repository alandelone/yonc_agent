import json
with open('data/current_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)
for t in state:
    title = t.get('title', '')
    if 'sort' in title.lower() or 'process' in title.lower():
        print(title)
