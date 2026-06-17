import json
with open('data/current_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)

for t in state:
    if 'irradiance module' in t.get('title', '') or 'BOM list with links' in t.get('title', ''):
        print(f"ID: {t.get('id')}")
        print(f"Title: {t.get('title').encode('unicode_escape').decode('utf-8')}")
        print(f"Depth: {t.get('depth')}")
        print(f"Has tag style: {t.get('has_tag_style')}")
        print(f"Synced tags: {t.get('synced_tags')}")
