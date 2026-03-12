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
    content = ""
    color = "default"
    
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
    else:
        return lines

def clean_task_title(title: str, structured_cfg: Dict[str, Any]) -> str:
    """Removes themes, modes, and emojis from the task title so it's clean for the LLM."""
    clean_title = re.sub(r'^\[.*?\]\s*', '', title)
    
    for mode_cfg in structured_cfg.get("modes", []):
        mode_name = mode_cfg.get("mode_name", "")
        if mode_name and mode_name in clean_title:
            clean_title = clean_title.replace(mode_name, "").strip()
            
    for t_name in structured_cfg.get("themes", {}).keys():
        if t_name in clean_title:
            clean_title = clean_title.replace(t_name, "").strip()
            
    # Remove remaining emojis and special characters at the beginning/end
    clean_title = re.sub(r'(?:[^\w\s\x00-\x7F\|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+', '', clean_title).strip()
    return clean_title

def load_config() -> Dict[str, List[Any]]:
    """
    Auto-discovers configuring sections and options from YONCTASK_CONFIG_PAGE_ID.
    Collects heading_1/2/3 as keys and parses lists/paragraphs as options.
    """
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
                
    return config_dict

def structure_yonctask_config(raw_config: Dict[str, List[Any]]) -> Dict[str, Any]:
    structured = {
        "themes": {},
        "modes": [],
        "priorities": {},
        "task_states": {},
        "task_types": {}
    }

    # 1. Parse Priorities (Split by " | ")
    for item in raw_config.get("Priority", []):
        if "|" in item:
            emoji, p_level = map(str.strip, item.split("|", 1))
            structured["priorities"][emoji] = p_level.strip("()")

    # 2. Parse Task States (Split by " | ")
    for item in raw_config.get("State of Parent Task", []):
        if "|" in item:
            emoji, desc = map(str.strip, item.split("|", 1))
            structured["task_states"][emoji] = desc

    # 3. Parse Task Types (Regex extraction)
    # Matches format: 🔍 (测试): Stress & Load Testing
    type_pattern = re.compile(r"^(.*?)\s*\((.*?)\):\s*(.*)$")
    for item in raw_config.get("Task Type", []):
        if "---" in item: continue # skip dividers
        match = type_pattern.match(item)
        if match:
            emoji, name_cn, desc = match.groups()
            structured["task_types"][emoji.strip()] = {
                "name_cn": name_cn.strip(),
                "description": desc.strip()
            }
        elif ":" in item: # fallback for unknown types
             parts = item.split(":", 1)
             structured["task_types"][parts[0].strip()] = {"description": parts[1].strip()}

    # 4. Parse Modes (Regex for Level, Tags, Description)
    for item in raw_config.get("Modes", []):
        text = item.get("text", "") if isinstance(item, dict) else item
        annos = item.get("annotations", {"color": "default", "bold": False, "code": False, "italic": False, "strikethrough": False, "underline": False}) if isinstance(item, dict) else {"color": "default", "bold": False, "code": False, "italic": False, "strikethrough": False, "underline": False}
        rich_text = item.get("rich_text") if isinstance(item, dict) else None
        
        if not text: continue
        
        # Must start with Lv
        clean_prefix = text.lstrip("*").strip()
        if not clean_prefix.startswith("Lv"): continue
        
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
                        mode_name = current_mode_text.strip()
                        if mode_name:
                            parsed_modes.append({"mode_name": mode_name, "annotations": current_mode_annos})
                        current_mode_text = ""
                        current_mode_annos = None
                        
                    clean_text = rt_text.replace("*", "").strip()
                    if not clean_text:
                        continue
                        
                    if "Lv" in rt_text:
                        match = re.search(r'Lv([\d\.]+)', rt_text)
                        if match:
                            lv_str = match.group(1)
                            try: level = float(lv_str) if "." in lv_str else int(lv_str)
                            except ValueError: pass
                    else:
                        description_parts.append(clean_text)
                        
            if current_mode_text:
                mode_name = current_mode_text.strip()
                if mode_name:
                    parsed_modes.append({"mode_name": mode_name, "annotations": current_mode_annos})
                    
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
        level_str = parts[0].replace("*", "").replace("Lv", "").strip()
        try: level = float(level_str) if '.' in level_str else int(level_str)
        except ValueError: level = 0
        
        mode_name = parts[1] if len(parts) > 1 else ""
        description = " ".join(p.replace("*", "").strip() for p in parts[2:]) if len(parts) > 2 else ""
            
        structured["modes"].append({
            "level": level,
            "mode_name": mode_name,
            "description": description,            "annotations": annos
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

if __name__ == "__main__":
    import json
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    # For quick testing
    raw_cfg = load_config()
    cfg = structure_yonctask_config(raw_cfg)
    print(json.dumps(cfg, indent=2, ensure_ascii=False))
