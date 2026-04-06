import json
import os
from datetime import datetime
from typing import List, Dict, Any
from state_manager import load_state, STATE_FILE, CURRENT_STATE_FILE, save_state

import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

TUNABLE_FILE = os.path.join(DATA_DIR, "tunable.jsonl")
PREFERENCE_DIFF_FILE = os.path.join(DATA_DIR, "generated_preference_diffs.jsonl")

DONE_MARK = "\u2705"

def log_generated_preference_diff(
    task: Dict[str, Any],
    action: str,
    before: Dict[str, Any],
    after: Dict[str, Any]
):
    """
    Logs generated-task transformation based on user preference actions.
    This dataset can be used for future split optimization.
    """
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "action": action,
        "task_id": task.get("notion_block_id") or task.get("id"),
        "source_task_id": before.get("task_id"),
        "parent_id": task.get("parent_id"),
        "title": task.get("original_notion_title", task.get("title", "")),
        "wbs_level": task.get("wbs_level"),
        "is_generated": task.get("is_generated", False),
        "origin": task.get("origin", "unknown"),
        "before": before,
        "after": after
    }
    with open(PREFERENCE_DIFF_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

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
            title_changed = new_item.get("title") != curr_item.get("title")
            checked_changed = new_item.get("checked") != curr_item.get("checked")
            if title_changed:
                log_conflict(
                    b_id, 
                    curr_item.get("title"), 
                    "title", 
                    curr_item.get("title"), 
                    new_item.get("title"), 
                    "notion_manual"
                )
            if checked_changed:
                log_conflict(
                    b_id,
                    curr_item.get("title"),
                    "checked",
                    curr_item.get("checked"),
                    new_item.get("checked"),
                    "notion_manual"
                )
            if title_changed or checked_changed:
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

def reparent_theme_containers(enriched_state: List[Dict[str, Any]], config_dict: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    """
    Flatten theme/sub-theme container blocks by moving their child subtrees one level up:
    - clone each direct child subtree under container's parent (preserve order)
    - delete original container block (archives original subtree)
    - update local state ids/parent/depth to the newly cloned blocks

    This makes structures like:
        - Theme
            - SubTheme
                - Task
    become:
        - Task
    with depth reduced once per removed container.
    """
    from notion_client import append_children, delete_block
    from config_reader import structure_yonctask_config
    import re

    structured_cfg = structure_yonctask_config(config_dict)
    themes = structured_cfg.get("themes", {})
    if not themes:
        return enriched_state

    def _task_id(task: Dict[str, Any]) -> str:
        return str(task.get("notion_block_id") or task.get("id") or "")

    def _normalize_block_type(task: Dict[str, Any]) -> str:
        block_type = task.get("notion_type") or task.get("type") or ""
        if block_type == "todo":
            return "to_do"
        if block_type == "bullet":
            return "bulleted_list_item"
        return block_type

    def _normalize_theme_text(text: str) -> str:
        t = str(text or "").strip()
        if not t:
            return ""
        t = re.sub(r'^\[.*?\]\s*', '', t).strip()
        t = t.replace("`", "").replace("*", "").strip()
        t = re.sub(r'^(?:[^\w\s\x00-\x7F\|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+\s*', '', t).strip()
        t = re.sub(r'\s+', ' ', t).strip()
        return t

    def _match_theme_or_subtheme(text: str) -> tuple[str | None, str | None]:
        raw = str(text or "").strip()
        normalized = _normalize_theme_text(raw)
        for t_name, t_data in themes.items():
            if raw == t_name or normalized == t_name:
                return (t_name, t_name)
            for st in t_data.get("sub_themes", []):
                if raw == st or normalized == st:
                    return (t_name, st)
        return (None, None)

    def _build_children_map(state: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        children_map: Dict[str, List[Dict[str, Any]]] = {}
        for task in state:
            tid = _task_id(task)
            if not tid:
                continue
            pid = str(task.get("parent_id") or "")
            if not pid:
                continue
            children_map.setdefault(pid, []).append(task)
        return children_map

    def _collect_subtree_ids(root_id: str, children_map: Dict[str, List[Dict[str, Any]]]) -> set:
        ids = set()
        stack = [root_id]
        while stack:
            current = stack.pop()
            if current in ids:
                continue
            ids.add(current)
            for child in children_map.get(current, []):
                cid = _task_id(child)
                if cid:
                    stack.append(cid)
        return ids

    def _build_block_payload(task: Dict[str, Any]) -> Dict[str, Any]:
        block_type = _normalize_block_type(task)
        annotations = task.get("annotations", {}) if isinstance(task.get("annotations"), dict) else {}
        color = annotations.get("color", "default")
        title = str(task.get("original_notion_title", task.get("title", "")) or "").strip()
        if not title:
            title = " "
        rich_text = [{
            "type": "text",
            "text": {"content": title}
        }]

        if block_type == "to_do":
            return {
                "object": "block",
                "type": "to_do",
                "to_do": {
                    "rich_text": rich_text,
                    "checked": bool(task.get("checked")),
                    "color": color
                }
            }
        if block_type == "bulleted_list_item":
            return {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": rich_text,
                    "color": color
                }
            }
        if block_type == "numbered_list_item":
            return {
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {
                    "rich_text": rich_text,
                    "color": color
                }
            }
        if block_type == "toggle":
            return {
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": rich_text,
                    "color": color
                }
            }
        if block_type in ["heading_1", "heading_2", "heading_3"]:
            return {
                "object": "block",
                "type": block_type,
                block_type: {
                    "rich_text": rich_text,
                    "color": color
                }
            }
        # Default fallback
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": rich_text,
                "color": color
            }
        }

    def _clone_subtree(
        source_task: Dict[str, Any],
        new_parent_id: str,
        after_id: str | None,
        children_map: Dict[str, List[Dict[str, Any]]]
    ) -> tuple[List[Dict[str, Any]], Dict[str, str], str]:
        source_id = _task_id(source_task)
        if not source_id:
            raise ValueError("Cannot clone subtree task without id")

        payload = _build_block_payload(source_task)
        append_res = append_children(new_parent_id, [payload], after_id=after_id)
        new_block = (append_res.get("results") or [{}])[-1]
        new_id = str(new_block.get("id") or "")
        if not new_id:
            raise RuntimeError(f"Failed to create cloned block for {source_id}")

        cloned_root = source_task.copy()
        cloned_root["id"] = new_id
        cloned_root["notion_block_id"] = new_id
        cloned_root["parent_id"] = new_parent_id
        if isinstance(source_task.get("depth"), int):
            cloned_root["depth"] = max(0, int(source_task.get("depth")) - 1)

        cloned_list = [cloned_root]
        id_map = {source_id: new_id}

        child_after = None
        for child in children_map.get(source_id, []):
            child_clones, child_map, child_new_id = _clone_subtree(
                source_task=child,
                new_parent_id=new_id,
                after_id=child_after,
                children_map=children_map
            )
            cloned_list.extend(child_clones)
            id_map.update(child_map)
            child_after = child_new_id

        return cloned_list, id_map, new_id

    def _is_theme_container(task: Dict[str, Any], children_map: Dict[str, List[Dict[str, Any]]]) -> bool:
        tid = _task_id(task)
        if not tid or not children_map.get(tid):
            return False
        if not task.get("parent_id"):
            return False
        title = task.get("original_notion_title", task.get("title", ""))
        theme_key, _ = _match_theme_or_subtheme(title)
        return bool(theme_key)

    state = list(enriched_state)
    changed_count = 0

    while True:
        children_map = _build_children_map(state)
        order_index = {_task_id(task): i for i, task in enumerate(state) if _task_id(task)}

        container = None
        for task in state:
            if _is_theme_container(task, children_map):
                container = task
                break
        if container is None:
            break

        container_id = _task_id(container)
        container_parent_id = str(container.get("parent_id") or "")
        direct_children = children_map.get(container_id, [])
        if not container_parent_id or not direct_children:
            break

        cloned_flat: List[Dict[str, Any]] = []
        after_cursor = container_id
        try:
            for child in direct_children:
                child_clones, _, new_root_id = _clone_subtree(
                    source_task=child,
                    new_parent_id=container_parent_id,
                    after_id=after_cursor,
                    children_map=children_map
                )
                cloned_flat.extend(child_clones)
                after_cursor = new_root_id

            delete_block(container_id)
        except Exception as e:
            print(f"Failed to reparent theme container {container_id}: {e}")
            break

        old_subtree_ids = _collect_subtree_ids(container_id, children_map)
        container_idx = order_index.get(container_id, len(state))
        insert_idx = sum(1 for t in state[:container_idx] if _task_id(t) not in old_subtree_ids)

        remaining = [t for t in state if _task_id(t) not in old_subtree_ids]
        state = remaining[:insert_idx] + cloned_flat + remaining[insert_idx:]
        changed_count += 1

    if changed_count:
        print(f"Reparented and removed {changed_count} theme container block(s).")

    return state

def push_tags_to_notion(enriched_state: List[Dict[str, Any]], config_dict: Dict[str, List[Any]]):
    """
    Pushes LLM-generated tags back to Notion by adding formatted prefixes.
    Adds Theme and Mode as bold/code text, and removes [] from emojis.
    Senses "\u2705" as Done sign to format the text with strikethrough.
    """
    from notion_client import update_block, replace_with_toggle_item, delete_block
    from config_reader import structure_yonctask_config
    import re
    
    structured_cfg = structure_yonctask_config(config_dict)
    themes = structured_cfg.get("themes", {})
    emoji_pattern = re.compile(r'(?:[^\w\s\x00-\x7F\|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+')

    def _extract_emoji(val: Any) -> str:
        match = emoji_pattern.search(str(val))
        return match.group() if match else ""

    known_wbs_emojis = set()
    for _, wbs_entry in structured_cfg.get("wbs_levels", {}).items():
        if isinstance(wbs_entry, dict):
            wbs_raw = wbs_entry.get("raw") or wbs_entry.get("emoji", "")
        else:
            wbs_raw = str(wbs_entry)
        e = _extract_emoji(wbs_raw)
        if e:
            known_wbs_emojis.add(e)

    def _strip_stale_wbs_prefix(text: str) -> str:
        cleaned = text
        if not known_wbs_emojis:
            return cleaned.strip()
        changed = True
        while changed:
            changed = False
            for wbs_e in known_wbs_emojis:
                updated = re.sub(rf'^\s*{re.escape(wbs_e)}\s*', '', cleaned).strip()
                if updated != cleaned:
                    cleaned = updated
                    changed = True
        return cleaned.strip()
    
    for task in enriched_state:
        tags = task.get("tags") or {}
            
        block_id = task.get("notion_block_id") or task.get("id")
        block_type = task.get("notion_type") or task.get("type")
        original_title = task.get("original_notion_title", task.get("title", ""))
        wbs_level = task.get("wbs_level")
        is_generated = bool(task.get("is_generated"))
        origin = task.get("origin", "unknown")
        if isinstance(wbs_level, str) and wbs_level.isdigit():
            wbs_level = int(wbs_level)
        
        if block_type == "todo":
            block_type = "to_do"
        elif block_type == "bullet":
            block_type = "bulleted_list_item"

        if not block_type or not block_id:
            continue

        checked = task.get("checked") if block_type == "to_do" else None
        is_done = (DONE_MARK in original_title) or bool(checked)

        # No tags: only do a lightweight cleanup for stale WBS prefix text.
        if not tags:
            if block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
                continue

            clean_title = re.sub(r'^\[.*?\]\s*', '', original_title).strip()
            clean_title = _strip_stale_wbs_prefix(clean_title)
            should_normalize_style = bool(task.get("has_tag_style", False))
            if clean_title == original_title and not should_normalize_style:
                continue

            rich_text = [{
                "type": "text",
                "text": {"content": clean_title},
                "annotations": {"strikethrough": is_done, "color": "gray" if is_done else "default"}
            }]
            content_payload = {
                block_type: {
                    "rich_text": rich_text,
                    "color": "gray" if is_done else "default"
                }
            }
            if block_type == "to_do":
                content_payload[block_type]["checked"] = bool(checked)

            try:
                update_block(block_id, content_payload)
                task["title"] = clean_title
                if block_type == "to_do":
                    task["checked"] = bool(checked)
                import sys
                msg = f"Cleaned stale WBS prefix for {block_id}: {clean_title}\n"
                sys.stdout.buffer.write(msg.encode('utf-8'))
            except Exception as e:
                print(f"Failed to clean stale WBS prefix for {block_id}: {e}")
            continue
             
        if block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
            # 只删除被 LLM 标记过的 paragraph/heading（已合并到子任务中的主题块）
            # tags 为空的 paragraph 是用户手写的 section heading（如 "婚姻"），必须保留作为 context
            if not tags:
                continue
            try:
                delete_block(block_id)
                import sys
                msg = f"Merged and deleted theme block {block_id}: {original_title}\n"
                sys.stdout.buffer.write(msg.encode('utf-8'))
            except Exception as e:
                print(f"Failed to delete theme block {block_id}: {e}")
            continue
            
        selection_mode = block_type == "to_do" and is_generated

        # Generated split tasks are treated as a preference selector:
        # - unchecked -> delete
        # - checked L1-L3 -> convert to toggle
        # - checked L4 -> reset to unchecked to_do
        if selection_mode and checked is False:
            try:
                delete_block(block_id)
                log_generated_preference_diff(
                    task=task,
                    action="delete_unchecked_generated_todo",
                    before={
                        "task_id": block_id,
                        "block_type": "to_do",
                        "checked": False,
                        "wbs_level": wbs_level,
                        "origin": origin
                    },
                    after={"block_type": "deleted"}
                )
                task["deleted"] = True
                import sys
                msg = f"Deleted unchecked generated to-do {block_id}: {original_title}\n"
                sys.stdout.buffer.write(msg.encode('utf-8'))
            except Exception as e:
                print(f"Failed to delete unchecked generated to-do {block_id}: {e}")
            continue

        # For generated selector to-do, checked does not imply completion.
        is_done = (DONE_MARK in original_title) or (bool(checked) and not selection_mode)
        
        # Clean previous generated prefixes to prevent stacking
        clean_title = original_title
        # Remove [emoji_block] if any
        clean_title = re.sub(r'^\[.*?\]\s*', '', clean_title)
        # Remove stale leading WBS emojis from older runs when current tags no longer carry WBS.
        clean_title = _strip_stale_wbs_prefix(clean_title)
        
        rich_text = []
        wbs_val = tags.get("WBS level", "")
        wbs_emoji = _extract_emoji(wbs_val)
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
        
        # 0. WBS level (always first)
        if wbs_emoji:
            if wbs_emoji in clean_title:
                clean_title = clean_title.replace(wbs_emoji, "").strip()
            rich_text.append({
                "type": "text",
                "text": {"content": wbs_emoji + " "},
                "annotations": {"strikethrough": is_done, "color": "gray" if is_done else "default"}
            })

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
        # 3. Emoji tags without brackets (excluding WBS level)
        emojis = []
        for k, v in tags.items():
            if k in ["Task Theme with colour", "Modes", "WBS level"]:
                continue
            emoji = _extract_emoji(v)
            if emoji:
                emojis.append(emoji)
                
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
        checked_for_payload = bool(checked)
        should_reset_l4_to_unchecked = selection_mode and bool(checked) and wbs_level == 4
        if should_reset_l4_to_unchecked:
            checked_for_payload = False
        if block_type == "to_do":
            content_payload[block_type]["checked"] = checked_for_payload
        
        # Stop if no update needed (compare raw string loosely)
        new_plain_title = "".join([rt["text"]["content"] for rt in rich_text])
        should_convert_to_toggle = selection_mode and bool(checked) and wbs_level != 4
        if should_convert_to_toggle:
            parent_id = task.get("parent_id")
            if not parent_id:
                print(f"Cannot convert to toggle: missing parent_id for {block_id}")
            else:
                try:
                    new_block = replace_with_toggle_item(block_id, parent_id, rich_text, color="gray" if is_done else "default")
                    new_block_id = new_block.get("id")
                    before = {
                        "task_id": block_id,
                        "block_type": "to_do",
                        "checked": True,
                        "wbs_level": wbs_level,
                        "origin": origin
                    }
                    if new_block_id:
                        task["id"] = new_block_id
                        task["notion_block_id"] = new_block_id
                    task["notion_type"] = "toggle"
                    task["type"] = "toggle"
                    task["checked"] = None
                    task["synced_tags"] = True
                    task["title"] = new_plain_title
                    log_generated_preference_diff(
                        task=task,
                        action="convert_checked_non_l4_to_toggle",
                        before=before,
                        after={
                            "block_type": "toggle",
                            "checked": None,
                            "new_task_id": new_block_id
                        }
                    )
                    
                    import sys
                    msg = f"Converted checked to-do to toggle for {block_id}: {new_plain_title}\n"
                    sys.stdout.buffer.write(msg.encode('utf-8'))
                    continue
                except Exception as e:
                    print(f"Failed to convert to toggle for {block_id}: {e}")
        if task.get("synced_tags") and new_plain_title == original_title and (block_type != "to_do" or bool(checked) == checked_for_payload):
            continue
        
        try:
            update_block(block_id, content_payload)
            task["synced_tags"] = True
            task["title"] = new_plain_title
            if block_type == "to_do":
                task["checked"] = checked_for_payload
            if should_reset_l4_to_unchecked:
                log_generated_preference_diff(
                    task=task,
                    action="convert_checked_l4_to_unchecked_todo",
                    before={
                        "task_id": block_id,
                        "block_type": "to_do",
                        "checked": True,
                        "wbs_level": wbs_level,
                        "origin": origin
                    },
                    after={
                        "block_type": "to_do",
                        "checked": False
                    }
                )
            
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
