import json
from sync_engine import push_tags_to_notion
from config_reader import load_config

cfg = load_config()

with open('data/current_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)

print("Restoring WBS tags properly...")

def get_wbs_emoji(depth):
    d = depth or 0
    if d == 0: return '💠'
    if d == 1: return '🔹'
    if d == 2: return '🔸'
    return '▫️'

count = 0
for task in state:
    title = task.get('title', '')
    if title.startswith('Thesis') or title.startswith('SolarMan'):
        # Force it to process
        task['has_tag_style'] = True
        task['synced_tags'] = False
        
        theme_word = 'Thesis' if title.startswith('Thesis') else 'SolarMan'
        emoji = get_wbs_emoji(task.get('depth', 0))
        
        # Inject the WBS emoji into the TITLE so sync_engine picks it up!
        task['title'] = emoji + " " + title
        
        # Also provide the mock rich text for the theme
        task['notion_rich_text'] = [
            {
                "type": "text",
                "text": {"content": emoji + " "},
                "annotations": {"bold": False, "code": False, "color": "default"}
            },
            {
                "type": "text",
                "text": {"content": theme_word},
                "annotations": {"bold": True, "code": True, "color": "default"}
            }
        ]
        count += 1

print(f"Restoring {count} tasks...")
push_tags_to_notion(state, cfg)
print("Finished!")
