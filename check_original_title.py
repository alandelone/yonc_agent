import json
with open('data/current_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)

for t in state:
    if 'irradiance module' in t.get('title', ''):
        print(f"original: {t.get('original_notion_title').encode('unicode_escape').decode('utf-8')}")
