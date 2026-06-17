import json
import traceback
from sync_engine import push_tags_to_notion
from config_reader import load_config

cfg = load_config()
state = json.load(open('data/current_state.json', encoding='utf-8'))

with open('debug_skip.txt', 'w', encoding='utf-8') as f:
    f.write("Starting skip check...\n")

for t in state:
    try:
        title = t.get('original_notion_title', '')
        if 'Logic' in title or 'SolarMan' in title or 'Thesis' in title:
            is_generated = t.get("is_generated", False)
            checked = t.get("checked", False)
            wbs_level = t.get("wbs_level")
            tags = t.get("tags", {})
            origin = t.get("origin", "")
            
            with open('debug_skip.txt', 'a', encoding='utf-8') as f:
                f.write(f"Title: {title[:40]}\n")
                f.write(f"  is_generated: {is_generated}\n")
                f.write(f"  tags: {tags}\n")
                f.write(f"  wbs_level: {wbs_level}\n")
                f.write(f"  checked: {checked}\n")
                f.write(f"  origin: {origin}\n\n")
    except Exception as e:
        pass
