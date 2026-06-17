import json
with open('data/tasklist_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)

res = []
for t in state:
    title = t.get('title', '')
    if 'SolarMan' in title or 'Thesis' in title:
        emoji = ''
        if title and not title[0].isalnum() and title[0] not in '[] ':
            emoji = title[0]
        res.append(f"{t.get('id')}: {emoji}")
        
with open('debug_tasklist_emoji.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(res))
