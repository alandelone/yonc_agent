import re
from typing import Dict, List, Any, Union
from notion_client import get_page_blocks
from config import YONCTASK_CONFIG_PAGE_ID

def parse_rich_text(rich_text_array: List[Dict[str, Any]]) -> str:
    """Extract plain text from a Notion rich text array."""
    return "".join([t.get("plain_text", "") for t in rich_text_array])

def parse_options_from_block(block: Dict[str, Any], current_heading: str = "") -> List[Any]:
    """
    Extract text options from a block.
    If it's under 'Task Theme with colour', we return a dict with text and color.
    Otherwise, we return a string.
    """
    block_type = block.get("type", "")
    
    if block_type == "toggle" and current_heading in ("DayStyle", "DayStyle_Dict"):
        return [block]
        
    content = ""
    color = "default"
    rich_text = []
    
    if block_type in ["paragraph", "bulleted_list_item", "numbered_list_item", "to_do"]:
        type_content = block.get(block_type, {})
        rich_text = type_content.get("rich_text", [])
        content = parse_rich_text(rich_text)
        
        # Try finding the first explicit color in annotations
        for rt in rich_text:
            annos = rt.get("annotations", {})
            c = annos.get("color", "default")
            if c != "default":
                color = c
                
            # For Themes we just want the color.
            # For Modes, we specifically want the annotations of the element structured as `Code`
            if "Modes" in current_heading:
                # If this specific block is marked as code, it's the Mode name badge we want to copy styles from.
                if annos.get("code") is True:
                    if not 'extracted_annotations' in locals():
                        extracted_annotations = annos.copy()
        
    if not content.strip():
        return []
        
    lines = [line.strip() for line in content.split("\n") if line.strip()]
    
    if "Theme" in current_heading:
        return [{"text": line, "color": color} for line in lines]
    elif "Modes" in current_heading:
        annos = locals().get('extracted_annotations', {"color": color})
        # ensure color is at least default if not present
        if "color" not in annos: annos["color"] = color
        # Also include the raw rich_text so we can parse multiple modes per line
        return [{"text": line, "annotations": annos, "rich_text": rich_text} for line in lines]
    elif "Task Type" in current_heading:
        tag = ""
        for rt in rich_text:
            if rt.get("annotations", {}).get("code") is True:
                tag = rt.get("text", {}).get("content", rt.get("plain_text", "")).strip()
                break
        return [{"text": line, "tag": tag} for line in lines]
    else:
        return lines

def clean_task_title(title: str, structured_cfg: Dict[str, Any]) -> str:
    """Removes themes, modes, and emojis from the task title so it's clean for the LLM."""
    clean_title = re.sub(r'^\[.*?\]\s*', '', title)
    
    # Strip emojis from the beginning first to expose the theme text
    clean_title = re.sub(r'^(?:[^\w\s\x00-\x7F\|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+\s*', '', clean_title).strip()
    
    for mode_cfg in structured_cfg.get("modes", []):
        mode_name = mode_cfg.get("mode_name", "")
        if mode_name and mode_name in clean_title:
            clean_title = clean_title.replace(mode_name, "").strip()
            
    for t_name, t_data in structured_cfg.get("themes", {}).items():
        if t_name in clean_title:
            clean_title = clean_title.replace(t_name, "").strip()
        for sub_theme in t_data.get("sub_themes", []):
            if sub_theme and clean_title.startswith(sub_theme):
                clean_title = clean_title[len(sub_theme):].strip()
            
    # Remove remaining emojis and special characters at the beginning/end
    clean_title = re.sub(r'(?:[^\w\s\x00-\x7F\|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+', '', clean_title).strip()
    return clean_title

def load_config() -> Dict[str, List[Any]]:
    """
    Auto-discovers configuring sections and options from YONCTASK_CONFIG_PAGE_ID.
    Collects heading_1/2/3 as keys and parses lists/paragraphs as options.
    If data/tasklist.json exists, load from there first. Otherwise, fetch from Notion and save to data/tasklist.json.
    """
    import os
    import json
    import time
    
    config_path = os.path.join(os.path.dirname(__file__), "data", "tasklist.json")
    if os.path.exists(config_path):
        # Check cache age (e.g., 6 hours)
        cache_age = time.time() - os.path.getmtime(config_path)
        if cache_age < 6 * 3600:
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load config from {config_path}: {e}")
        else:
            print(f"Config cache is {cache_age/3600:.1f} hours old. Fetching fresh config from Notion...")

    blocks = get_page_blocks(YONCTASK_CONFIG_PAGE_ID)
    config_dict = {}
    current_heading = None
    
    for block in blocks:
        block_type = block.get("type", "")
        
        if block_type in ["heading_1", "heading_2", "heading_3"]:
            # New config section
            heading_content = block.get(block_type, {})
            rich_text = heading_content.get("rich_text", [])
            current_heading = parse_rich_text(rich_text).strip()
            
            if current_heading and current_heading not in config_dict:
                config_dict[current_heading] = []
                
        elif current_heading:
            # We are under a heading, collect options
            options = parse_options_from_block(block, current_heading)
            if options:
                config_dict[current_heading].extend(options)
                
    # Save to data/tasklist.json
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save config to {config_path}: {e}")

    return config_dict

def structure_yonctask_config(raw_config: Dict[str, List[Any]]) -> Dict[str, Any]:
    structured = {
        "themes": {},
        "modes": [],
        "priorities": {},
        "task_states": {},
        "task_types": {},
        "wbs_levels": {}
    }

    emoji_pattern = re.compile(r'^((?:[^\w\s\x00-\x7F\|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+)\s*(.*)$')

    # 1. Parse Priorities (Split by " | " or extract emoji fallback)
    for item in raw_config.get("Priority", []):
        if "|" in item:
            emoji, p_level = map(str.strip, item.split("|", 1))
            structured["priorities"][emoji] = p_level.strip("()")
        else:
            match = emoji_pattern.match(item.strip())
            if match:
                structured["priorities"][match.group(1).strip()] = match.group(2).strip("()")

    # 2. Parse Task States (Split by " | " or extract emoji fallback)
    for item in raw_config.get("State of Parent Task", []):
        if "|" in item:
            emoji, desc = map(str.strip, item.split("|", 1))
            structured["task_states"][emoji] = desc
        else:
            match = emoji_pattern.match(item.strip())
            if match:
                structured["task_states"][match.group(1).strip()] = match.group(2).strip()

    # 3. Parse Task Types
    for item in raw_config.get("Task Type", []):
        text = item.get("text", "") if isinstance(item, dict) else item
        tag = item.get("tag", "") if isinstance(item, dict) else ""
        if not text or "---" in text:
            continue
            
        # Parse new format: 🔬| Research : description
        pipe_match = re.match(r"^([^|]+)\|\s*([^:]+)\s*:\s*(.*)$", text)
        if pipe_match:
            emoji, name, desc = pipe_match.groups()
            key = f"{emoji.strip()}| {name.strip()}"
            structured["task_types"][key] = {
                "name": name.strip(),
                "name_cn": name.strip(),  # backward compatibility
                "description": desc.strip(),
                "tag": tag
            }
            continue
            
        # Fallback: {emoji} : {name_or_desc} (e.g. ❓ : Unknown TYPE)
        colon_match = re.match(r"^([^:]+)\s*:\s*(.*)$", text)
        if colon_match:
            emoji_part, name_or_desc = colon_match.groups()
            structured["task_types"][emoji_part.strip()] = {
                "name": name_or_desc.strip(),
                "name_cn": name_or_desc.strip(),  # backward compatibility
                "description": "",
                "tag": tag
            }

    # 3.5 Parse WBS Levels (Split by " | ")
    wbs_key = None
    for k in raw_config.keys():
        if k.strip().lower() == "wbs level":
            wbs_key = k
            break
    if wbs_key:
        for item in raw_config.get(wbs_key, []):
            if "|" in item:
                emoji, level_label = map(str.strip, item.split("|", 1))
            else:
                match = emoji_pattern.match(item.strip())
                if match:
                    emoji = match.group(1).strip()
                    level_label = match.group(2).strip()
                else:
                    continue

            level_num = None
            match = re.search(r'\d+', level_label)
            if match:
                try:
                    level_num = int(match.group())
                except ValueError:
                    level_num = None
            key = level_num if level_num is not None else level_label
            structured["wbs_levels"][key] = {
                "emoji": emoji,
                "label": level_label,
                "raw": f"{emoji} | {level_label}"
            }

    # 4. Parse Modes (Level, Tags, Description)
    for item in raw_config.get("Modes", []):
        text = item.get("text", "") if isinstance(item, dict) else item
        annos = item.get("annotations", {"color": "default", "bold": False, "code": False, "italic": False, "strikethrough": False, "underline": False}) if isinstance(item, dict) else {"color": "default", "bold": False, "code": False, "italic": False, "strikethrough": False, "underline": False}
        rich_text = item.get("rich_text") if isinstance(item, dict) else None
        
        if not text: continue
        
        # Must start with Lv or Level (case-insensitive, optional space)
        clean_prefix = text.lstrip("*").strip()
        if not re.match(r'^(?:Level|Lv)\s*\d', clean_prefix, re.IGNORECASE): continue
        
        if rich_text:
            level = 0
            description_parts = []
            parsed_modes = []
            current_mode_text = ""
            current_mode_annos = None
            
            for rt in rich_text:
                rt_text = rt.get("text", {}).get("content", "")
                rt_annos = rt.get("annotations", {})
                is_code = rt_annos.get("code", False)
                
                if is_code:
                    if current_mode_annos is None:
                        current_mode_annos = rt_annos.copy()
                    if current_mode_annos.get("color", "default") == "default" and rt_annos.get("color", "default") != "default":
                        current_mode_annos["color"] = rt_annos["color"]
                    current_mode_text += rt_text
                else:
                    if current_mode_text:
                        mode_names = [m.strip() for m in current_mode_text.split() if m.strip()]
                        for m_name in mode_names:
                            parsed_modes.append({"mode_name": m_name, "annotations": current_mode_annos})
                        current_mode_text = ""
                        current_mode_annos = None
                        
                    clean_text = rt_text.replace("*", "").strip()
                    if not clean_text:
                        continue
                        
                    lv_match = re.search(r'(?:Level|Lv)\s*([\d\.]+)', rt_text, re.IGNORECASE)
                    if lv_match:
                        lv_str = lv_match.group(1)
                        try: level = float(lv_str) if "." in lv_str else int(lv_str)
                        except ValueError: pass
                    else:
                        description_parts.append(clean_text)
                        
            if current_mode_text:
                mode_names = [m.strip() for m in current_mode_text.split() if m.strip()]
                for m_name in mode_names:
                    parsed_modes.append({"mode_name": m_name, "annotations": current_mode_annos})
                    
            desc = " ".join(description_parts).replace(" | ", " | ").strip()
            
            if parsed_modes:
                for m in parsed_modes:
                    structured["modes"].append({
                        "level": level,
                        "mode_name": m["mode_name"],
                        "description": desc,
                        "annotations": m["annotations"]
                    })
                continue
                
        # Fallback text parsing if no rich_text or no modes found
        parts = [p.strip() for p in re.split(r'\s{2,}', text)]
        level_str = parts[0].replace("*", "").strip()
        level_str = re.sub(r'^(?:Level|Lv)\s*', '', level_str, flags=re.IGNORECASE).strip()
        try: level = float(level_str) if '.' in level_str else int(level_str)
        except ValueError: level = 0
        
        mode_names_raw = parts[1] if len(parts) > 1 else ""
        mode_names = [m.strip() for m in mode_names_raw.split() if m.strip()]
        description = " ".join(p.replace("*", "").strip() for p in parts[2:]) if len(parts) > 2 else ""
            
        for mode_name in mode_names:
            structured["modes"].append({
                "level": level,
                "mode_name": mode_name,
                "description": description,
                "annotations": annos
            })

    # 5. Parse Themes
    for item in raw_config.get("Task Theme with colour", []):
        text = item
        color = "default"
        if isinstance(item, dict):
            text = item.get("text", "")
            color = item.get("color", "default")
            
        if not text: continue
            
        parts = text.split(" ", 1)
        name = parts[0]
        desc = parts[1] if len(parts) > 1 else ""
        
        sub_themes = [s.strip() for s in desc.split("|") if s.strip()]
        
        structured["themes"][name] = {
            "name": name,
            "sub_themes": sub_themes,
            "color": color
        }

    return structured

def _parse_timeline_entry(text: str) -> dict:
    """Parse: time: "07:00" || activity: WakeUp || location: Home || energy: 3 [|| tasktype: X, Y]"""
    entry = {}
    fields = [f.strip() for f in text.split("||")]
    for field in fields:
        if ":" not in field:
            continue
        key, val = field.split(":", 1)
        key = key.strip().lower()
        val = val.strip().strip('"')
        if key == "energy":
            try: val = int(val)
            except ValueError: pass
        elif key == "tasktype":
            val = [t.strip() for t in val.split(",") if t.strip()]
        entry[key] = val
    if "tasktype" not in entry:
        entry["tasktype"] = []
    return entry

def parse_daystyles(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    daystyles = []
    for block in blocks:
        if block.get("type") != "toggle":
            continue
            
        toggle_data = block.get("toggle", {})
        title_text = parse_rich_text(toggle_data.get("rich_text", [])).strip()
        if not title_text:
            continue
            
        # Split title by ":" to get name and description
        if ":" in title_text:
            name, desc = title_text.split(":", 1)
            name = name.strip()
            desc = desc.strip()
        else:
            name = title_text
            desc = ""
            
        children = block.get("children_blocks", [])
        
        trajectory = []
        timeline = []
        current_section = None
        
        for child in children:
            child_type = child.get("type", "")
            if child_type == "heading_4":
                h_text = parse_rich_text(child.get("heading_4", {}).get("rich_text", [])).strip()
                if "Trajectory" in h_text:
                    current_section = "trajectory"
                elif "Expected State Timeline" in h_text:
                    current_section = "timeline"
                else:
                    current_section = None
            elif current_section == "trajectory" and child_type == "bulleted_list_item":
                loc_text = parse_rich_text(child.get("bulleted_list_item", {}).get("rich_text", [])).strip()
                if loc_text:
                    trajectory.append({
                        "location": loc_text,
                        "block_id": child.get("id")
                    })
            elif current_section == "timeline" and child_type == "paragraph":
                line_text = parse_rich_text(child.get("paragraph", {}).get("rich_text", [])).strip()
                if line_text:
                    entry = _parse_timeline_entry(line_text)
                    entry["block_id"] = child.get("id")
                    entry["raw"] = line_text
                    timeline.append(entry)
                    
        daystyles.append({
            "dayStyle": name,
            "description": desc,
            "block_id": block.get("id"),
            "trajectory": trajectory,
            "expectedStateTimeline": timeline
        })
    return daystyles

def parse_block_text(block: Dict[str, Any]) -> str:
    b_type = block.get("type", "")
    if not b_type:
        return ""
    type_data = block.get(b_type, {})
    return parse_rich_text(type_data.get("rich_text", [])).strip()

def parse_daystyle_dicts(blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    dicts = {}
    for block in blocks:
        if block.get("type") != "toggle":
            continue
        dict_name = parse_block_text(block)
        if not dict_name:
            continue
            
        dict_data = {}
        children = block.get("children_blocks", [])
        for child in children:
            child_type = child.get("type", "")
            if child_type not in ("toggle", "bulleted_list_item"):
                continue
            sub_name = parse_block_text(child)
            if not sub_name:
                continue
                
            sub_children = child.get("children_blocks", [])
            sub_items = []
            for sub_child in sub_children:
                sub_child_type = sub_child.get("type", "")
                if sub_child_type in ("toggle", "bulleted_list_item"):
                    item_text = parse_block_text(sub_child)
                    if item_text:
                        sub_items.append(item_text)
                        
            dict_data[sub_name] = {
                "sub_items": sub_items,
                "block_id": child.get("id")
            }
        dicts[dict_name] = dict_data
    return dicts

if __name__ == "__main__":
    import json
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    # For quick testing
    raw_cfg = load_config()
    cfg = structure_yonctask_config(raw_cfg)
    print(json.dumps(cfg, indent=2, ensure_ascii=False))
