import json
import sys
from config_reader import load_config
import re
from config_reader import structure_yonctask_config

def test_push_tags(task, config_dict):
    structured_cfg = structure_yonctask_config(config_dict)
    themes = structured_cfg.get("themes", {})
    emoji_pattern = re.compile(r'(?:[^\w\s\x00-\x7F\|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+')

    def _extract_emoji(val):
        match = emoji_pattern.search(str(val))
        return match.group() if match else ""

    known_prefix_emojis = set()
    wbs_emojis = set()
    for _, wbs_entry in structured_cfg.get("wbs_levels", {}).items():
        if isinstance(wbs_entry, dict):
            wbs_raw = wbs_entry.get("raw") or wbs_entry.get("emoji", "")
        else:
            wbs_raw = str(wbs_entry)
        e = _extract_emoji(wbs_raw)
        if e:
            known_prefix_emojis.add(e)
            wbs_emojis.add(e)

    priority_emojis = set()
    for e in structured_cfg.get("priorities", {}).keys():
        e_str = str(e).strip()
        if e_str: 
            known_prefix_emojis.add(e_str)
            priority_emojis.add(e_str)

    print("--- STARTING TASK LOOP ---")
    block_id = task.get("notion_block_id") or task.get("id")
    block_type = task.get("notion_type") or task.get("type")
    
    if block_type == "todo":
        block_type = "to_do"
    elif block_type == "bullet":
        block_type = "bulleted_list_item"

    if not block_type or not block_id:
        print("SKIP: missing block type or id")
        return
    if task.get("is_content_block") or block_type == "quote":
        print("SKIP: content block or quote")
        return

    original_title = task.get("original_notion_title", task.get("title", ""))
    tags = task.get("tags", {})
    
    wbs_val = tags.get("WBS level", "")
    wbs_emoji = _extract_emoji(wbs_val)
    print("wbs_emoji:", wbs_emoji)
    
    is_generated = bool(task.get("is_generated"))
    print("is_generated:", is_generated)

    # fast pass check
    is_already_themed = False
    plain_title_trimmed = original_title.strip()
    for t_name, t_data in themes.items():
        if plain_title_trimmed.startswith(t_name):
            is_already_themed = True
            break
        for st in t_data.get("sub_themes", []):
            if plain_title_trimmed.startswith(st):
                is_already_themed = True
                break
        if is_already_themed:
            break
            
    print("is_already_themed:", is_already_themed)

    if not tags and not is_already_themed and not bool(task.get("has_tag_style", False)):
        print("SKIP: no tags block")
        return
        
    print("REACHED END OF LOOP without skipping!")


d = json.load(open('temp_out.json', encoding='utf-8'))
task = d[0]
cfg = load_config()
test_push_tags(task, cfg)
