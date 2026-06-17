import json
state = json.load(open('data/current_state.json', encoding='utf-8'))
with open('debug_tags.txt', 'w', encoding='utf-8') as f:
    for t in state:
        title = t.get('title', '')
        if 'Logic' in title or 'SolarMan' in title or 'Thesis' in title:
            f.write(f"Title: {title}\nTags: {t.get('tags', {}).get('Task Theme with colour')}\n\n")
