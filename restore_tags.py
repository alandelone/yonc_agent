import json
from sync_engine import push_tags_to_notion
from config_reader import load_config
import time

cfg = load_config()

with open('data/current_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)

print("Restoring wiped manual tags for 'Thesis' and 'SolarMan'...")

# We will manually inject the rich text annotations so sync_engine picks them up
for task in state:
    title = task.get('title', '')
    if title.startswith('Thesis') or title.startswith('SolarMan'):
        # Force it to process
        task['has_tag_style'] = True
        task['synced_tags'] = False
        
        # Inject the mock rich text so the fallback extracts the theme
        theme_word = 'Thesis' if title.startswith('Thesis') else 'SolarMan'
        task['notion_rich_text'] = [
            {
                "type": "text",
                "text": {"content": theme_word},
                "annotations": {"bold": True, "code": True, "color": "default"}
            }
        ]

print("Pushing to Notion...")
push_tags_to_notion(state, cfg)
print("Finished!")
