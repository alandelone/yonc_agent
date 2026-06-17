import json
from config_reader import load_config
from sync_engine import push_tags_to_notion
import sys

cfg = load_config()

with open('data/current_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)

# Filter state to just one of the problem tasks
test_tasks = [t for t in state if t.get('id') == '37fe1eb5-ce57-81c5-9f76-ed56bb539387']

# Mimic restore_correct_wbs.py modification
task = test_tasks[0]
task['has_tag_style'] = True
task['synced_tags'] = False
title = task.get('title', '')
clean_idx = min(title.find('Thesis') if 'Thesis' in title else 9999,
                title.find('SolarMan') if 'SolarMan' in title else 9999)
clean_title = title[clean_idx:]
task['title'] = '🔸 ' + clean_title
task['notion_rich_text'] = [
    {
        "type": "text",
        "text": {"content": "🔸 "},
        "annotations": {"bold": False, "code": False, "color": "default"}
    },
    {
        "type": "text",
        "text": {"content": "SolarMan"},
        "annotations": {"bold": True, "code": True, "color": "default"}
    }
]

# Write a monkey patch for update_block so we don't actually hit Notion API
import notion_client
notion_client.update_block = lambda a, b: print("UPDATE_BLOCK CALLED!")
notion_client.replace_with_bullet = lambda a, b, c, color, children: print("REPLACE_WITH_BULLET CALLED!")

# Override print to see what's happening
original_print = print
def debug_print(*args):
    original_print(*args)
    sys.stdout.flush()
import builtins
builtins.print = debug_print

push_tags_to_notion(test_tasks, cfg)
