import json
from sync_engine import push_tags_to_notion
from config_reader import load_config, structure_yonctask_config

cfg = load_config()
yonc_config = structure_yonctask_config(cfg)

with open('data/current_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)

print("Restoring correct WBS tags from config...")

wbs_levels = yonc_config.get('wbs_levels', {})

def get_wbs_emoji(depth):
    d = depth or 0
    lvl = d + 1
    if lvl in wbs_levels:
        return wbs_levels[lvl].get('emoji', '🔸')
    else:
        return '🔸'

count = 0
for task in state:
    title = task.get('title', '')
    
    if 'Thesis' in title or 'SolarMan' in title:
        task['has_tag_style'] = True
        task['synced_tags'] = False
        
        # Clean title
        clean_idx = min(title.find('Thesis') if 'Thesis' in title else 9999,
                        title.find('SolarMan') if 'SolarMan' in title else 9999)
        clean_title = title[clean_idx:]
        
        theme_word = 'Thesis' if 'Thesis' in clean_title else 'SolarMan'
        emoji = get_wbs_emoji(task.get('depth', 0))
        
        task['title'] = emoji + " " + clean_title
        
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
