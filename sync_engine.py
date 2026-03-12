import json
import os
from datetime import datetime
from typing import List, Dict, Any
from state_manager import load_state, STATE_FILE, CURRENT_STATE_FILE, save_state

TUNABLE_FILE = "tunable.jsonl"

def log_conflict(task_id: str, task_title: str, field: str, old_value: Any, new_value: Any, source: str):
    """
    Log preference drift and manual overrides to tunable.jsonl
    """
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "task_id": task_id,
        "task_title": task_title,
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
        "source": source
    }
    
    with open(TUNABLE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

def compute_diff(current_state: List[Dict[str, Any]], new_notion_state: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compares the last snapshot against the freshly fetched Notion state.
    Returns structurally changed objects to apply patches.
    """
    curr_dict = {item.get("notion_block_id"): item for item in current_state}
    new_dict = {item.get("notion_block_id"): item for item in new_notion_state}
    
    changes_detected = []
    
    for b_id, new_item in new_dict.items():
        if b_id in curr_dict:
            curr_item = curr_dict[b_id]
            # Simple text diff detecting manual text overrides in Notion
            if new_item.get("title") != curr_item.get("title"):
                log_conflict(
                    b_id, 
                    curr_item.get("title"), 
                    "title", 
                    curr_item.get("title"), 
                    new_item.get("title"), 
                    "notion_manual"
                )
                changes_detected.append({"id": b_id, "type": "update", "item": new_item})
        else:
            changes_detected.append({"id": b_id, "type": "add", "item": new_item})
            
    for b_id in curr_dict.keys():
        if b_id not in new_dict:
            changes_detected.append({"id": b_id, "type": "delete", "item": curr_dict[b_id]})
            
    return {"changes": changes_detected, "new_dict": new_dict}

def sync_from_notion(flat_notion_state: List[Dict[str, Any]]):
    """
    Pull Notion -> Diff against CURRENT_STATE -> Update state
    """
    current_state = load_state(CURRENT_STATE_FILE)
    
    diff_result = compute_diff(current_state, flat_notion_state)
    
    if diff_result["changes"]:
        print(f"Detected {len(diff_result['changes'])} changes in Notion.")
        
    # Overwrite the latest snapshot
    save_state(flat_notion_state, CURRENT_STATE_FILE)
    
    # Check what needs to be synced back to working tasklist_state
    working_state = load_state(STATE_FILE)
    # The actual merge logic sits in state_manager.merge_states
    
    return working_state

def push_tags_to_notion(enriched_state: List[Dict[str, Any]], config_dict: Dict[str, List[Any]]):
    """
    Pushes LLM-generated tags back to Notion by adding formatted prefixes.
    Adds Theme and Mode as bold/code text, and removes [] from emojis.
    Senses "✅" as Done sign to format the text with strikethrough.
    """
    from notion_client import update_block
    from config_reader import structure_yonctask_config
    import re
    
    structured_cfg = structure_yonctask_config(config_dict)
    themes = structured_cfg.get("themes", {})
    
    for task in enriched_state:
        tags = task.get("tags")
        if not tags:
            continue
            
        block_id = task.get("notion_block_id") or task.get("id")
        block_type = task.get("type")
        original_title = task.get("original_notion_title", task.get("title", ""))
        
        if not block_type or not block_id:
            continue
            
        if block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
            # 只删除被 LLM 标记过的 paragraph/heading（已合并到子任务中的主题块）
            # tags 为空的 paragraph 是用户手写的 section heading（如 "婚姻"），必须保留作为 context
            if not tags:
                continue
            from notion_client import delete_block
            try:
                delete_block(block_id)
                import sys
                msg = f"Merged and deleted theme block {block_id}: {original_title}\n"
                sys.stdout.buffer.write(msg.encode('utf-8'))
            except Exception as e:
                print(f"Failed to delete theme block {block_id}: {e}")
            continue
            
        is_done = "✅" in original_title
        
        # Clean previous generated prefixes to prevent stacking
        clean_title = original_title
        # Remove [emoji_block] if any
        clean_title = re.sub(r'^\[.*?\]\s*', '', clean_title)
        
        rich_text = []
        theme_val = tags.get("Task Theme with colour", "")
        mode_val = tags.get("Modes", "")
        
        target_color = "default"
        theme_str = ""
        
        if theme_val:
            original_theme_name = theme_val.split()[0]
            main_theme_name = original_theme_name
            context_heading = task.get("context_heading", "")
            
            # Fallback 1: 用清理后的标题首词（去掉已有主题名和 mode 名）做 context
            if not context_heading and clean_title:
                # 先从 clean_title 中去掉所有已知主题名，避免之前错误推送的主题名循环传播
                fallback_title = clean_title
                for t_name in themes.keys():
                    fallback_title = fallback_title.replace(t_name, "").strip()
                if fallback_title:
                    context_heading = fallback_title.split()[0].strip()
            
            # 仅当 LLM 返回的主题不是有效 config 主题时，才用 context_heading 覆盖
            if main_theme_name not in themes and context_heading:
                for t_name, t_data in themes.items():
                    if context_heading == t_name or context_heading in t_data.get("sub_themes", []):
                        main_theme_name = t_name
                        break
                        
            theme_str = main_theme_name
            
            if main_theme_name in themes:
                target_color = themes[main_theme_name].get("color", "default")
                sub_themes = themes[main_theme_name].get("sub_themes", [])
                
                # Check if context_heading matches a sub-theme
                if context_heading and context_heading in sub_themes:
                    theme_str = context_heading
                else:
                    # Fallback check against title
                    for st in sub_themes:
                        if st in clean_title:
                            theme_str = st
                            break
                            
            # 移除所有已知主题名，防止之前错误推送的主题名残留
            for t_name in themes.keys():
                if t_name in clean_title:
                    clean_title = clean_title.replace(t_name, "").strip()
            if original_theme_name in clean_title:
                clean_title = clean_title.replace(original_theme_name, "").strip()
        
        # 1. Theme formatting
        if theme_str:
            if theme_str in clean_title:
                clean_title = clean_title.replace(theme_str, "").strip()
                
            rich_text.append({
                "type": "text",
                "text": {"content": theme_str},
                "annotations": {"bold": True, "code": True, "strikethrough": is_done, "color": "gray" if is_done else target_color}
            })
            rich_text.append({
                "type": "text",
                "text": {"content": " "},
                "annotations": {"strikethrough": is_done, "color": "gray" if is_done else "default"}
            })
            
        # 2. Mode formatting
        if mode_val:
            # We must use structured_cfg "modes" to check if the generated words match any valid mode_name
            for mode_cfg in structured_cfg.get("modes", []):
                mode_name = mode_cfg.get("mode_name", "")
                if not mode_name: continue
                
                # Check if this valid mode exists in the generated text
                if mode_name in mode_val:
                    mode_annos = mode_cfg.get("annotations", {"color": "default", "bold": False, "code": False, "italic": False, "strikethrough": False, "underline": False})
                    
                    if mode_name in clean_title:
                        clean_title = clean_title.replace(mode_name, "").strip()
                        
                    # Apply strike and gray out for done state, otherwise keep configured style
                    final_mode_annos = mode_annos.copy()
                    if is_done:
                        final_mode_annos["strikethrough"] = True
                        final_mode_annos["color"] = "gray"
                        
                    rich_text.append({
                        "type": "text",
                        "text": {"content": mode_name},
                        "annotations": final_mode_annos
                    })
                    rich_text.append({
                        "type": "text",
                        "text": {"content": " "},
                        "annotations": {"strikethrough": is_done, "color": "gray" if is_done else "default"}
                    })
        # 3. Emoji tags without brackets
        emojis = []
        for k, v in tags.items():
            if k in ["Task Theme with colour", "Modes"]:
                continue
            match = re.search(r'(?:[^\w\s\x00-\x7F\|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+', str(v))
            if match:
                emojis.append(match.group())
                
        if emojis:
            emojis_str = "".join(emojis)
            for e in emojis:
                clean_title = clean_title.replace(e, "").strip()
            
            rich_text.append({
                "type": "text",
                "text": {"content": emojis_str + " "},
                "annotations": {"strikethrough": is_done, "color": "gray" if is_done else "default"}
            })
            
        # 4. The actual cleaned task title
        rich_text.append({
            "type": "text",
            "text": {"content": clean_title.strip()},
            "annotations": {"strikethrough": is_done, "color": "gray" if is_done else "default"}
        })
        
        content_payload = {
            block_type: {
                "rich_text": rich_text,
                "color": "gray" if is_done else "default"
            }
        }
        
        # Stop if no update needed (compare raw string loosely)
        new_plain_title = "".join([rt["text"]["content"] for rt in rich_text])
        if task.get("synced_tags") and new_plain_title == original_title:
            continue
        
        try:
            update_block(block_id, content_payload)
            task["synced_tags"] = True
            task["title"] = new_plain_title
            
            import sys
            msg = f"Pushed formatted tags to Notion for {block_id}: {new_plain_title}\n"
            sys.stdout.buffer.write(msg.encode('utf-8'))
        except Exception as e:
            print(f"Failed to push tags to Notion for {block_id}: {e}")

def push_subtasks_to_notion(task_id: str, subtasks: List[str], parent_theme: str = None, parent_theme_color: str = "default"):
    """Creates physical to_do blocks under the parent abstract task."""
    from notion_client import append_children
    children_payload = []
    for st in subtasks:
        rich_text_array = []
        
        # Prepend the theme badge if provided
        if parent_theme:
            rich_text_array.append({
                "type": "text",
                "text": {"content": parent_theme},
                "annotations": {"bold": True, "code": True, "color": parent_theme_color}
            })
            rich_text_array.append({
                "type": "text",
                "text": {"content": " "},
                "annotations": {"color": "default"}
            })
            
        rich_text_array.append({
            "type": "text",
            "text": {"content": st}
        })
        
        children_payload.append({
            "object": "block",
            "type": "to_do",
            "to_do": {
                "rich_text": rich_text_array,
                "checked": False
            }
        })
    try:
        append_children(task_id, children_payload, position="start")
        import sys
        sys.stdout.buffer.write(f"Added {len(subtasks)} physical subtasks to the top of {task_id}\n".encode('utf-8'))
    except Exception as e:
        print(f"Failed to add subtasks to {task_id}: {e}")
