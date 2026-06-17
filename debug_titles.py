import json
state = json.load(open('data/current_state.json', encoding='utf-8'))
with open('debug_titles.txt', 'w', encoding='utf-8') as f:
    for t in state:
        title = t.get('title', '')
        if 'Logic' in title or 'SolarMan' in title or 'Thesis' in title:
            orig = t.get('original_notion_title', '')
            f.write(f"Title: {title}\nOrig:  {orig}\n\n")
