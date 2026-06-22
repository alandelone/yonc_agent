import json
import sys
from config_reader import load_config
from sync_engine import push_tags_to_notion

d = json.load(open('temp_out.json', encoding='utf-8'))
task = d[0] # 方法论证 Report

# I will check conditions manually
original_title = task.get("original_notion_title", "")
wbs_level = task.get("wbs_level")
tags = task.get("tags", {})
synced_tags = task.get("synced_tags", False)
split_stage = task.get("split_stage", "none")
origin = task.get("origin", "human")
generated_selection_processed = task.get("generated_selection_processed", False)

tags_synced = bool(synced_tags)
has_passed_stages = tags_synced and split_stage not in ["none", "suggested"]
is_valid_flow = (origin == "human" or generated_selection_processed) and has_passed_stages

print("tags_synced:", tags_synced)
print("has_passed_stages:", has_passed_stages)
print("is_valid_flow:", is_valid_flow)

import re
emoji_pattern = re.compile(r'(?:[^\w\s\x00-\x7F\|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+')
def _extract_emoji(val):
    match = emoji_pattern.search(str(val))
    return match.group() if match else ""

wbs_val = tags.get("WBS level", "")
wbs_emoji = _extract_emoji(wbs_val)
missing_wbs = bool(wbs_emoji and wbs_emoji not in original_title)
print("missing_wbs:", missing_wbs)

is_already_themed = False
themes = load_config().get("yonctask", {}).get("themes", {})
plain_title_trimmed = original_title.strip()
for t_name, t_data in themes.items():
    if plain_title_trimmed.startswith(t_name):
        is_already_themed = True
        break
    for st in t_data.get("sub_themes", []):
        if plain_title_trimmed.startswith(st):
            is_already_themed = True
            break
    if is_already_themed: break

print("is_already_themed:", is_already_themed)
print("has_tag_style:", task.get("has_tag_style"))
print("needs_colon_formatting:", ":" in original_title)

char_limit = 200 # approx
needs_compaction = len(str(original_title or "")) > char_limit
print("needs_compaction:", needs_compaction)

has_unwanted_theme_badge = False
print("has_unwanted_theme_badge:", has_unwanted_theme_badge)

if is_already_themed and task.get("has_tag_style") and not (":" in original_title) and not needs_compaction and not missing_wbs and not has_unwanted_theme_badge:
    print("=> Would SKIP in first check!")
else:
    print("=> Would NOT skip in first check")
    
# Wait! Look at lines 1120-1160 in sync_engine.py
