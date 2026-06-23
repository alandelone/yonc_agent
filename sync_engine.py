import json
import os
import re
from datetime import datetime, timezone
from typing import List, Dict, Any
from state_manager import load_state, STATE_FILE, CURRENT_STATE_FILE, save_state

import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

TUNABLE_FILE = os.path.join(DATA_DIR, "tunable.jsonl")
PREFERENCE_DIFF_FILE = os.path.join(DATA_DIR, "generated_preference_diffs.jsonl")

emoji_pattern = re.compile(r'(?:[^\w\s\x00-\x7F\|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+')

def _extract_emoji(val: Any) -> str:
    match = emoji_pattern.search(str(val))
    return match.group() if match else ""

def reverse_sync_tags_from_title(working_state: List[Dict[str, Any]], diff_changes: List[Dict[str, Any]]):
    from config_reader import load_config, structure_yonctask_config
    config_dict = load_config()
    structured_cfg = structure_yonctask_config(config_dict)
    
    # 1. Build lookup dictionaries
    wbs_map = {} # emoji -> level
    wbs_levels = structured_cfg.get("wbs_levels", {})
    for level, wbs_entry in wbs_levels.items():
        if isinstance(wbs_entry, dict):
            raw = str(wbs_entry.get("raw") or wbs_entry.get("emoji") or "")
        else:
            raw = str(wbs_entry)
        emoji = _extract_emoji(raw)
        if emoji:
            wbs_map[emoji] = level

    modes = structured_cfg.get("modes", [])
    mode_names = [str(m.get("mode_name", "")).strip() for m in modes if str(m.get("mode_name", "")).strip()]

    task_types_map = {} # text/emoji -> original key
    for k in structured_cfg.get("task_types", {}).keys():
        k_str = str(k).strip()
        if k_str:
            task_types_map[k_str] = k_str

    working_dict = {str(item.get("notion_block_id") or item.get("id")): item for item in working_state}

    import sys
    for change in diff_changes:
        if change.get("type") != "update":
            continue
            
        new_item = change.get("item", {})
        b_id = new_item.get("notion_block_id") or new_item.get("id")
        if not b_id or str(b_id) not in working_dict:
            continue
            
        w_item = working_dict[str(b_id)]
        
        # Check if the task is in complete style
        if not w_item.get("synced_tags"):
            continue
            
        new_title = new_item.get("original_notion_title") or new_item.get("title") or ""
        old_title = w_item.get("original_notion_title") or w_item.get("title") or ""
        
        if new_title == old_title:
            continue
            
        tags = w_item.get("tags") or {}
        changed = False
        
        # Detect new Mode
        new_mode = ""
        for m in mode_names:
            if m in new_title:
                new_mode = m
                break
        
        if new_mode and new_mode != str(tags.get("Modes", "")).strip():
            sys.stdout.buffer.write(f"Reverse sync: Mode changed to '{new_mode}' for task {b_id}\n".encode('utf-8'))
            tags["Modes"] = new_mode
            changed = True
            
        # Detect new Task Type
        new_tt = ""
        for tt in task_types_map:
            if tt in new_title:
                new_tt = tt
                break
                
        if new_tt and new_tt != str(tags.get("Task Type", "")).strip():
            sys.stdout.buffer.write(f"Reverse sync: Task Type changed to '{new_tt}' for task {b_id}\n".encode('utf-8'))
            tags["Task Type"] = new_tt
            changed = True
            
        # Detect new WBS level
        new_wbs_emoji = ""
        new_wbs_level = None
        for emoji, level in wbs_map.items():
            if emoji in new_title:
                new_wbs_emoji = emoji
                new_wbs_level = level
                break
                
        old_wbs_val = tags.get("WBS level", "")
        old_wbs_emoji = _extract_emoji(old_wbs_val)
        
        if new_wbs_emoji and new_wbs_emoji != old_wbs_emoji:
            sys.stdout.buffer.write(f"Reverse sync: WBS tag changed to '{new_wbs_emoji}' (Level {new_wbs_level}) for task {b_id}\n".encode('utf-8'))
            target_raw = new_wbs_emoji
            if new_wbs_level in wbs_levels:
                entry = wbs_levels[new_wbs_level]
                if isinstance(entry, dict):
                    target_raw = entry.get("raw") or entry.get("emoji") or new_wbs_emoji
                else:
                    target_raw = str(entry)
            tags["WBS level"] = target_raw
            w_item["wbs_level"] = new_wbs_level
            changed = True
            
        if changed:
            w_item["tags"] = tags

def _normalize_uuid(raw_id: str) -> str:
    """灏?32 浣嶆棤杩炲瓧绗︾殑 hex ID 杞崲涓烘爣鍑?UUID 鏍煎紡 (8-4-4-4-12)銆?
    Notion API 瑕佹眰 UUID 鏍煎紡锛屼絾 page ID 鍦?config 涓彲鑳戒笉甯﹁繛瀛楃銆?
    """
    if not raw_id:
        return raw_id
    clean = raw_id.replace("-", "")
    if len(clean) == 32:
        return f"{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}"
    return raw_id

def _sanitize_rich_text_for_create(rich_text: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep Notion rich_text fields that are valid in create/update payloads."""
    sanitized: List[Dict[str, Any]] = []
    for rt in rich_text or []:
        if not isinstance(rt, dict):
            continue
        item_type = rt.get("type", "text")
        if item_type != "text":
            continue
        text_obj = rt.get("text") if isinstance(rt.get("text"), dict) else {}
        content = text_obj.get("content") or rt.get("plain_text") or ""
        if not content:
            continue
        clean: Dict[str, Any] = {
            "type": "text",
            "text": {"content": str(content)},
        }
        link_obj = text_obj.get("link")
        url = link_obj.get("url") if isinstance(link_obj, dict) else None
        if url:
            clean["text"]["link"] = {"url": str(url)}
        if isinstance(rt.get("annotations"), dict):
            clean["annotations"] = rt["annotations"].copy()
        sanitized.append(clean)
    return sanitized

def _rich_text_for_task_creation(task: Dict[str, Any], fallback_title: str) -> List[Dict[str, Any]]:
    rich_text = _sanitize_rich_text_for_create(task.get("notion_rich_text") or [])
    if rich_text:
        return rich_text
    title = str(fallback_title or "").strip() or " "
    return [{"type": "text", "text": {"content": title}}]

def _plain_text_from_block(block: Dict[str, Any]) -> str:
    block_type = block.get("type") or ""
    rich_text = (block.get(block_type) or {}).get("rich_text") or []
    return "".join(str(rt.get("plain_text") or "") for rt in rich_text).strip()

def _dedupe_visible_title(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = text.replace("`", "").replace("*", "")
    return text.casefold()

def _direct_notion_children(parent_id: str) -> List[Dict[str, Any]]:
    import requests
    from config import NOTION_HEADERS

    url = f"https://api.notion.com/v1/blocks/{_normalize_uuid(parent_id)}/children"
    params: Dict[str, Any] = {"page_size": 100}
    children: List[Dict[str, Any]] = []
    while True:
        response = requests.get(url, headers=NOTION_HEADERS, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        children.extend(data.get("results") or [])
        if not data.get("has_more"):
            return children
        params["start_cursor"] = data.get("next_cursor")

def _archive_duplicate_direct_children_by_title(parent_id: str, preferred_ids: List[str] = None) -> set:
    """
    Repair interrupted clone/delete root moves.

    Root ordering recreates blocks because Notion cannot move arbitrary blocks. If a run
    dies after append but before archive, the Linev2 page shows duplicate root containers.
    Keep the first preferred/current block for each visible title and archive later copies.
    """
    from notion_client import delete_block

    preferred = {_normalize_uuid(str(x or "")) for x in (preferred_ids or []) if x}
    by_title: Dict[str, List[Dict[str, Any]]] = {}
    for child in _direct_notion_children(parent_id):
        if child.get("archived"):
            continue
        title_key = _dedupe_visible_title(_plain_text_from_block(child))
        if title_key:
            by_title.setdefault(title_key, []).append(child)

    archived_ids = set()
    for siblings in by_title.values():
        if len(siblings) < 2:
            continue
        preferred_siblings = [b for b in siblings if _normalize_uuid(str(b.get("id") or "")) in preferred]
        keep = preferred_siblings[0] if preferred_siblings else siblings[0]
        keep_id = _normalize_uuid(str(keep.get("id") or ""))
        for duplicate in siblings:
            duplicate_id = _normalize_uuid(str(duplicate.get("id") or ""))
            if not duplicate_id or duplicate_id == keep_id:
                continue
            delete_block(duplicate_id)
            archived_ids.add(duplicate_id)
    return archived_ids

def _rebuild_notion_block_payload(block: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rebuilds a valid Notion block creation payload from a raw block object.
    Recursively handles children if they are present in 'children_blocks'.
    """
    b_type = block.get("type")
    if not b_type:
        return {}

    type_data = block.get(b_type, {}).copy()
    
    # Remove system-generated fields that can't be set during creation
    # rich_text usually contains 'plain_text', 'href' etc. in Notion objects,
    # but the API usually ignores them if present in a creation call.
    # To be safe, we could strip them, but Notion is usually lenient.
    
    payload = {
        "object": "block",
        "type": b_type,
        b_type: type_data
    }

    # Handle nested children if they were fetched (recursive rebuild)
    # This ensures that even nested manual notes are preserved during cloning.
    children_blocks = block.get("children_blocks")
    if children_blocks:
        payload[b_type]["children"] = [_rebuild_notion_block_payload(child) for child in children_blocks]
    
    return payload

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
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "task_id": task_id,
        "task_title": task_title,
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
        "source": source
    }
    
    with open(TUNABLE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

def _is_llm_generated_task(task: Dict[str, Any]) -> bool:
    """Return True when a local task is known to have come from LLM generation."""
    return bool(task.get("is_generated")) or task.get("origin") == "generated"

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
            should_log_tunable = _is_llm_generated_task(curr_item)
            if should_log_tunable and title_changed:
                log_conflict(
                    b_id, 
                    curr_item.get("title"), 
                    "title", 
                    curr_item.get("title"), 
                    new_item.get("title"), 
                    "notion_manual"
                )
            if should_log_tunable and checked_changed:
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
    
    # Reverse sync tags from manual Notion edits
    if diff_result["changes"]:
        reverse_sync_tags_from_title(working_state, diff_result["changes"])
        save_state(working_state, STATE_FILE)
        
    # The actual merge logic sits in state_manager.merge_states
    
    return working_state

def reparent_theme_containers(enriched_state: List[Dict[str, Any]], config_dict: Dict[str, List[Any]], dry_run: bool = False) -> List[Dict[str, Any]]:
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

    When dry_run=True, only prints planned actions without calling Notion API.
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
        best_match: tuple[int, int, str, str] | None = None
        for t_name, t_data in themes.items():
            if raw == t_name or normalized == t_name:
                return (t_name, t_name)
            for st in t_data.get("sub_themes", []):
                if raw == st or normalized == st:
                    return (t_name, st)
            # Fallback for previously prefixed rows, e.g. "閸涢€燣ab 閸涢€燤aker".
            candidates = [t_name] + list(t_data.get("sub_themes", []))
            for candidate in candidates:
                c = str(candidate or "").strip()
                if not c:
                    continue
                pos = normalized.rfind(c)
                if pos < 0:
                    continue
                key = (pos, len(c), t_name, c)
                if best_match is None or key[:2] > best_match[:2]:
                    best_match = key
        if best_match is not None:
            return (best_match[2], best_match[3])
        return (None, None)

    def _extract_theme_prefixed_suffix(text: str) -> tuple[str | None, str | None]:
        normalized = _normalize_theme_text(text)
        for t_name in themes.keys():
            prefix = f"{t_name} "
            if normalized.startswith(prefix):
                suffix = normalized[len(prefix):].strip()
                if suffix:
                    return (t_name, suffix)
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
        # 灏嗙紪鍙峰垪琛ㄨ浆涓烘棤搴忓垪琛紙鐢ㄦ埛瑕佹眰瀛愪富棰樹笅鎵€鏈夊唴瀹逛娇鐢?bullet 鏍煎紡锛?
        if block_type == "numbered_list_item":
            block_type = "bulleted_list_item"
        annotations = task.get("annotations", {}) if isinstance(task.get("annotations"), dict) else {}
        color = annotations.get("color", "default")
        title = str(task.get("original_notion_title", task.get("title", "")) or "").strip()
        rich_text = _rich_text_for_task_creation(task, title)

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

    def _batch_clone_children(
        source_tasks: List[Dict[str, Any]],
        new_parent_id: str,
        children_map: Dict[str, List[Dict[str, Any]]],
        after_id: str = None
    ) -> List[Dict[str, Any]]:
        """鎵归噺灏?source_tasks 鍐呭鍒涘缓鍒?new_parent_id 涓嬶紝涓嶄娇鐢?after 鍙傛暟閬垮厤 ID 閲嶇敤銆?
        杩斿洖骞冲睍鍚庣殑鍏嬮殕浠诲姟鍒楄〃銆?
        """
        if not source_tasks:
            return []

        safe_parent_id = _normalize_uuid(new_parent_id)

        # 涓€娆℃€ф壒閲?append 鎵€鏈?direct children锛堜笉甯?after锛変互閬垮厤 ID 閲嶇敤 bug
        payloads = [_build_block_payload(t) for t in source_tasks]

        if dry_run:
            import uuid
            new_ids = [f"dry-{uuid.uuid4().hex[:12]}" for _ in source_tasks]
        else:
            append_res = append_children(safe_parent_id, payloads, after_id=after_id)
            results = append_res.get("results") or []
            
            # When using after_id, Notion API returns newly created blocks AND subsequent siblings.
            if len(results) > len(source_tasks):
                results = results[:len(source_tasks)]
                
            if len(results) != len(source_tasks):
                raise RuntimeError(
                    f"append_children returned {len(results)} blocks, expected {len(source_tasks)}"
                )
            new_ids = [str(r.get("id") or "") for r in results]
            missing = [i for i, nid in enumerate(new_ids) if not nid]
            if missing:
                raise RuntimeError(f"Missing IDs for cloned blocks at indices {missing}")

        cloned_flat: List[Dict[str, Any]] = []
        for source_task, new_id in zip(source_tasks, new_ids):
            source_id = _task_id(source_task)
            cloned_root = source_task.copy()
            cloned_root["id"] = new_id
            cloned_root["notion_block_id"] = new_id
            cloned_root["parent_id"] = new_parent_id
            if isinstance(source_task.get("depth"), int):
                cloned_root["depth"] = max(0, int(source_task.get("depth")) - 1)
            cloned_root["_original_depth_for_reparent"] = source_task.get(
                "_original_depth_for_reparent",
                source_task.get("depth")
            )
            cloned_flat.append(cloned_root)

            # 閫掑綊澶勭悊璇ヨ妭鐐圭殑瀛愯妭鐐癸紙鍚屾牱鎵归噺涓嶅甫 after锛?
            grandchildren = children_map.get(source_id, [])
            if grandchildren:
                cloned_flat.extend(
                    _batch_clone_children(grandchildren, new_id, children_map)
                )

        return cloned_flat

    def _is_theme_container(task: Dict[str, Any], children_map: Dict[str, List[Dict[str, Any]]]) -> bool:
        tid = _task_id(task)
        if not tid or not children_map.get(tid):
            return False
        if not task.get("parent_id"):
            return False
        depth = task.get("_original_depth_for_reparent", task.get("depth"))
        if isinstance(depth, int) and depth > 1:
            # Only flatten shallow theme/sub-theme containers.
            # Keep deeper hierarchy (e.g. 3dpF under 閸涢€燤aker) intact.
            return False
        title = task.get("original_notion_title", task.get("title", ""))
        
        raw = str(title or "").strip()
        normalized = _normalize_theme_text(raw)
        for t_name, t_data in themes.items():
            if raw == t_name or normalized == t_name:
                return True
            for st in t_data.get("sub_themes", []):
                if raw == st or normalized == st:
                    return True

        # Dynamic fallback for "Theme SomeLabel" rows that are effectively
        # one-child grouping wrappers (e.g. "鎴戞祦鏂圭煩 鍒氫綋" -> "鍒氫綋鎵撻€犲拰璁粌璁?).
        pref_theme, pref_suffix = _extract_theme_prefixed_suffix(title)
        if pref_theme and pref_suffix:
            configured_subthemes = set(themes.get(pref_theme, {}).get("sub_themes", []))
            if pref_suffix in configured_subthemes:
                return True
            if len(children_map.get(tid, [])) == 1:
                return True

        return False

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

        # 瑙ｆ瀽瀹瑰櫒鍖归厤鍒扮殑瀛愪富棰樺悕锛岀敤浜庝紶鎾粰瀛愯妭鐐圭殑 theme_display_label
        container_title = container.get("original_notion_title", container.get("title", ""))
        _, pref_suffix = _extract_theme_prefixed_suffix(container_title)
        if pref_suffix:
            container_matched_subtheme = pref_suffix
        else:
            _, container_matched_subtheme = _match_theme_or_subtheme(container_title)

        import sys
        if dry_run:
            msg = f"[DRY-RUN] Would reparent container '{container_title}' (id={container_id})\n"
            msg += f"  parent_id={container_parent_id} -> normalized={_normalize_uuid(container_parent_id)}\n"
            msg += f"  matched_subtheme='{container_matched_subtheme}', direct children={len(direct_children)}\n"
            for child in direct_children:
                child_title = child.get('original_notion_title', child.get('title', ''))
                msg += f"    -> child: '{child_title}'\n"
            sys.stdout.buffer.write(msg.encode('utf-8'))

        try:
            safe_container_id = _normalize_uuid(container_id) if not dry_run else None
            
            cloned_flat = _batch_clone_children(
                direct_children, container_parent_id, children_map, after_id=safe_container_id
            )

            # Insert first, then delete to avoid using after=archived_id
            if not dry_run:
                delete_block(safe_container_id)
            else:
                msg = f"[DRY-RUN] Would delete container block {container_id}\n"
                sys.stdout.buffer.write(msg.encode('utf-8'))
        except Exception as e:
            print(f"Failed to reparent theme container {container_id}: {e}")
            break

        # 浼犳挱 theme_display_label 鍒扮洿鎺ュ瓙鑺傜偣
        # clone 鍚庣洿鎺ュ瓙鑺傜偣鐨?parent_id == container_parent_id锛堝鍣ㄧ殑鐖剁骇锛?
        if container_matched_subtheme:
            for cloned in cloned_flat:
                # 浠呭鐩存帴瀛愯妭鐐硅缃?label锛堟繁灞傚瓙鑺傜偣鐨?parent_id 涓嶇瓑浜?container_parent_id锛?
                if cloned.get("parent_id") == container_parent_id:
                    cloned["theme_display_label"] = container_matched_subtheme

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
    from notion_client import update_block, replace_with_bullet, delete_block
    from config_reader import structure_yonctask_config
    import re
    
    structured_cfg = structure_yonctask_config(config_dict)
    themes = structured_cfg.get("themes", {})

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
        
    task_type_emojis = set()
    for e in structured_cfg.get("task_types", {}).keys():
        e_str = str(e).strip()
        if e_str: 
            known_prefix_emojis.add(e_str)
            task_type_emojis.add(e_str)

    def _raw_wbs_value(level: Any) -> str:
        if level is None:
            return ""
        wbs_levels = structured_cfg.get("wbs_levels", {})
        candidates = [level]
        try:
            candidates.append(int(level))
        except (TypeError, ValueError):
            pass
        candidates.append(str(level))
        for key in candidates:
            if key not in wbs_levels:
                continue
            val = wbs_levels.get(key)
            if isinstance(val, dict):
                return str(val.get("raw") or val.get("emoji") or "").strip()
            return str(val or "").strip()
        return ""

    def _strip_stale_prefix_emojis(text: str) -> str:
        cleaned = text
        if not known_prefix_emojis:
            return cleaned.strip()
        for e in known_prefix_emojis:
            cleaned = cleaned.replace(e, "")
        return cleaned.strip()

    def _normalize_for_theme_match(text: str) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return ""
        normalized = re.sub(r'^\[.*?\]\s*', '', normalized).strip()
        normalized = normalized.replace("`", "").replace("*", "").strip()
        normalized = re.sub(r'^(?:[^\w\s\x00-\x7F\|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+\s*', '', normalized).strip()
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized

    def _resolve_display_theme_label(task: Dict[str, Any], main_theme_name: str) -> str:
        explicit = str(task.get("theme_display_label", "")).strip()
        if explicit:
            return explicit

        context_heading = str(task.get("context_heading", "")).strip()
        if main_theme_name in themes:
            sub_themes = themes[main_theme_name].get("sub_themes", [])
            if context_heading and context_heading in sub_themes:
                return context_heading

        full_title = _normalize_for_theme_match(task.get("title", ""))
        original_title = _normalize_for_theme_match(task.get("original_notion_title", task.get("title", "")))
        prefix = full_title
        if original_title and full_title.endswith(original_title):
            prefix = full_title[:-len(original_title)].strip()

        search_target = prefix if prefix else original_title
        if main_theme_name in themes and search_target:
            subthemes = list(themes[main_theme_name].get("sub_themes", []))
            best_submatch: tuple[int, int, str] | None = None
            
            # 1. Prefer matching sub_themes first, and find the earliest/longest
            for c in subthemes:
                c = str(c or "").strip()
                if not c:
                    continue
                pos = search_target.find(c)
                if pos < 0:
                    continue
                key = (-pos, len(c), c)
                if best_submatch is None or key[:2] > best_submatch[:2]:
                    best_submatch = key
                    
            if best_submatch:
                return best_submatch[2]
                
            # 2. If no sub_theme matched, check if main_theme matches
            if search_target.find(main_theme_name) >= 0:
                return main_theme_name

        return main_theme_name

    # --- 瀛楃鏁拌緟鍔╀笌 LLM 鍘嬬缉 ---
    def _char_limit_for_depth(depth: Any) -> int:
        try:
            d = int(depth)
        except (TypeError, ValueError):
            d = 0
        if d <= 0:   
            return 90
        if d == 1:
            return 90
        return 80

    def _compact_title_if_needed(title: str, char_limit: int, tag_char_count: int) -> str:
        """Compact title text with LLM when visible length exceeds limit."""
        from llm_pipeline import _condense_description, _condense_title

        raw_title = str(title or "").strip()
        if not raw_title:
            return ""

        allowed = max(10, char_limit - max(0, tag_char_count))
        if len(raw_title) <= allowed:
            return raw_title  # 涓嶉渶瑕佸帇缂?

        # 鏈?`:` 鍒嗛殧绗?鈫?鍙帇缂╂弿杩伴儴鍒?
        if ":" in raw_title:
            task_part, desc_part = raw_title.split(":", 1)
            task_part = task_part.strip()
            desc_part = desc_part.strip()
            if desc_part:
                condensed_desc = _condense_description(desc_part)
                result = f"{task_part} : {condensed_desc}"
                if len(result) <= allowed:
                    return result
                # 杩樻槸澶暱 鈫?鍚屾椂鍘嬬缉鏍囬閮ㄥ垎
                condensed_t = _condense_title(task_part)
                return f"{condensed_t} : {condensed_desc}"
            # 鍙湁 task_part
            return _condense_title(task_part)

        # 娌℃湁 `:` 鈫?鍘嬬缉鏁翠釜鏍囬
        return _condense_title(raw_title)

    def _link_for_segment(content: str, links: List[Dict[str, str]]) -> Dict[str, str] | None:
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return None
        for link in links or []:
            link_text = str(link.get("text") or "").strip()
            url = str(link.get("url") or "").strip()
            if not link_text or not url:
                continue
            if link_text in normalized_content or normalized_content in link_text:
                return {"url": url}
        return None

    def _append_text_segment(
        rich_text: List[Dict[str, Any]],
        content: str,
        annotations: Dict[str, Any],
        links: List[Dict[str, str]] | None = None,
    ) -> None:
        text_obj: Dict[str, Any] = {"content": content}
        link = _link_for_segment(content, links or [])
        if link:
            text_obj["link"] = link
        rich_text.append({
            "type": "text",
            "text": text_obj,
            "annotations": annotations.copy(),
        })

    def _append_title_segments(
        rich_text: List[Dict[str, Any]],
        visible_title: str,
        is_done: bool,
        total_tracked_hours: float = 0.0,
        is_hierarchically_complete: bool = False,
        links: List[Dict[str, str]] | None = None,
    ):
        if is_hierarchically_complete:
            hours_str = f"💯✅ *{round(total_tracked_hours, 1)}h* "
            rich_text.append({
                "type": "text",
                "text": {"content": hours_str},
                "annotations": {
                    "bold": False,
                    "italic": False,
                    "strikethrough": False,
                    "underline": False,
                    "code": False,
                    "color": "gray_background"
                }
            })
            base_annos = {"strikethrough": True, "color": "gray", "italic": True}
        else:
            base_annos = {"strikethrough": is_done, "color": "gray" if is_done else "default"}

        title_text = str(visible_title or "").strip()
        if not title_text:
            _append_text_segment(rich_text, " ", base_annos, links)
            return

        if ":" not in title_text:
            _append_text_segment(rich_text, title_text, base_annos, links)
            return

        task_part, desc_part = title_text.split(":", 1)
        task_part = task_part.strip()
        desc_part = desc_part.strip()

        if task_part:
            _append_text_segment(rich_text, f"{task_part} : ", base_annos, links)
        else:
            _append_text_segment(rich_text, ": ", base_annos, links)

        if desc_part:
            desc_annos = base_annos.copy()
            desc_annos["italic"] = True
            desc_annos["color"] = "gray"
            _append_text_segment(rich_text, desc_part, desc_annos, links)

    def _ordered_visible_tag_emojis(tags: Dict[str, Any]) -> List[str]:
        emojis: List[str] = []
        seen: set[str] = set()

        for k, v in tags.items():
            if k in [
                "Task Theme with colour",
                "Modes",
                "WBS level",
                "State of Parent Task",
                "Priority",
                "Task Type",
            ]:
                continue
            emoji = _extract_emoji(v)
            if emoji and emoji not in seen:
                seen.add(emoji)
                emojis.append(emoji)

        return emojis

    def _render_standard_row_tail(
        rich_text: List[Dict[str, Any]],
        tags: Dict[str, Any],
        clean_title: str,
        is_done: bool,
        depth: Any,
        total_tracked_hours: float = 0.0,
        is_hierarchically_complete: bool = False,
        links: List[Dict[str, str]] | None = None,
        extra_emojis: List[str] = None
    ) -> tuple[List[Dict[str, Any]], str]:
        emojis = _ordered_visible_tag_emojis(tags)
        if extra_emojis:
            for e in extra_emojis:
                if e not in emojis:
                    emojis.append(e)
        if emojis:
            emojis_str = "".join(emojis)
            for e in emojis:
                clean_title = clean_title.replace(e, "").strip()
            
            # Note: tags emoji annotations shouldn't have the strikethrough logic if hierarchically complete, but we follow standard annotations if not
            base_color = "gray" if (is_done or is_hierarchically_complete) else "default"
            has_strike = bool(is_done or is_hierarchically_complete)
            
            rich_text.append({
                "type": "text",
                "text": {"content": emojis_str + " "},
                "annotations": {"strikethrough": has_strike, "color": base_color}
            })

        # 根据 tag 占用的字符数计算标题可用额度，超额则 LLM 压缩
        char_limit = _char_limit_for_depth(depth)
        tag_cc = sum(
            len(str(rt.get("text", {}).get("content", "")))
            for rt in rich_text
        )
        compacted_title = _compact_title_if_needed(
            clean_title.strip(),
            char_limit,
            tag_cc,
        )
        _append_title_segments(
            rich_text,
            compacted_title,
            is_done,
            total_tracked_hours,
            is_hierarchically_complete,
            links=links,
        )
        return rich_text, compacted_title

    task_by_id: Dict[str, Dict[str, Any]] = {}
    children_map: Dict[str, List[Dict[str, Any]]] = {}
    for t in enriched_state:
        tid = str(t.get("notion_block_id") or t.get("id") or "")
        pid = str(t.get("parent_id") or "")
        if tid:
            task_by_id[tid] = t
        if pid:
            children_map.setdefault(pid, []).append(t)

    # Auto-transition parent split_stage to 'processed' if no unreviewed generated children remain
    # This covers manual deletion of all generated children or when they have all been processed/selected.
    for task in enriched_state:
        if str(task.get("split_stage", "none")).lower() == "suggested":
            pid = str(task.get("notion_block_id") or task.get("id") or "")
            children = children_map.get(pid, [])
            unreviewed_generated = [
                c for c in children
                if bool(c.get("is_generated")) and not bool(c.get("generated_selection_processed", False))
            ]
            if not unreviewed_generated:
                task["split_stage"] = "processed"


    def _normalize_state_block_type(task: Dict[str, Any]) -> str:
        block_type = str(task.get("notion_type") or task.get("type") or "paragraph")
        if block_type in ("todo", "to_do"):
            return "to_do"
        if block_type in ("bullet", "bulleted_list_item", "numbered_list_item"):
            return "bulleted_list_item"
        if block_type in ("toggle", "quote", "paragraph", "heading_1", "heading_2", "heading_3"):
            return block_type
        return "paragraph"

    def _state_task_to_block_payload(task: Dict[str, Any]) -> Dict[str, Any]:
        block_type = _normalize_state_block_type(task)
        title = str(task.get("original_notion_title", task.get("title", "")) or "").strip()
        rich_text = _rich_text_for_task_creation(task, title)
        annotations = task.get("annotations", {}) if isinstance(task.get("annotations"), dict) else {}
        color = annotations.get("color", "default")
        payload: Dict[str, Any] = {
            "object": "block",
            "type": block_type,
            block_type: {
                "rich_text": rich_text,
                "color": color,
            },
        }
        if block_type == "to_do":
            payload[block_type]["checked"] = bool(task.get("checked"))
        children = [
            _state_task_to_block_payload(child)
            for child in children_map.get(str(task.get("notion_block_id") or task.get("id") or ""), [])
        ]
        if children:
            payload[block_type]["children"] = children
        return payload

    def _child_payloads_for_replacement(task_id: str) -> List[Dict[str, Any]]:
        return [_state_task_to_block_payload(child) for child in children_map.get(task_id, [])]

    def _repoint_descendants(old_parent_id: str, new_parent_id: str) -> None:
        for child in children_map.get(old_parent_id, []):
            child["parent_id"] = new_parent_id

    def _is_task_complete(task_id: str) -> bool:
        if not task_id or task_id not in task_by_id:
            return False
        t = task_by_id[task_id]
        level = t.get("wbs_level")
        try:
            level_num = int(level)
        except (TypeError, ValueError):
            level_num = None

        if level_num == 4:
            is_generated = bool(t.get("is_generated"))
            generated_selection_processed = bool(t.get("generated_selection_processed", False))
            if is_generated and not generated_selection_processed:
                return False
            return bool(t.get("checked"))

        if level_num in [1, 2, 3]:
            direct_children = children_map.get(task_id, [])
            if not direct_children:
                return False
            for child in direct_children:
                if not _is_task_complete(str(child.get("notion_block_id") or child.get("id") or "")):
                    return False
            return True
        return False

    def _calculate_total_hours(task_id: str) -> float:
        if not task_id or task_id not in task_by_id:
            return 0.0
        t = task_by_id[task_id]
        total_hours = 0.0
        
        timetaken = t.get("metrics", {}).get("timetaken", [])
        if isinstance(timetaken, list):
            for period in timetaken:
                try:
                    if isinstance(period, (list, tuple)) and len(period) >= 2:
                        start, end = period[0], period[1]
                    elif isinstance(period, dict):
                        start, end = period.get("start"), period.get("end")
                    else:
                        continue
                    if start and end:
                        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                            total_hours += (float(end) - float(start)) / 3600.0
                        else:
                            dt_start = datetime.fromisoformat(str(start).replace('Z', '+00:00'))
                            dt_end = datetime.fromisoformat(str(end).replace('Z', '+00:00'))
                            total_hours += (dt_end - dt_start).total_seconds() / 3600.0
                except Exception:
                    pass
                
        for child in children_map.get(task_id, []):
            total_hours += _calculate_total_hours(str(child.get("notion_block_id") or child.get("id") or ""))
            
        return total_hours

    # 预计算：按 parent_id 统计 generated to_do 中 checked 的数量
    # 鍙湁鍚岀粍 checked >= 2 鏃舵墠璁や负浜虹被杩涜浜嗘湁鎰忎箟鐨勪氦浜掞紝鎵嶆縺娲?selection_mode
    from collections import defaultdict
    _generated_checked_count_by_parent: Dict[str, int] = defaultdict(int)
    for t in enriched_state:
        t_type = t.get("notion_type") or t.get("type") or ""
        if t_type in ("todo", "to_do") and bool(t.get("is_generated")) and bool(t.get("checked")):
            pid = str(t.get("parent_id") or "")
            if pid:
                _generated_checked_count_by_parent[pid] += 1

    # Option A: Update parent's split_stage to 'processed' once at least one generated child is checked
    for pid, count in _generated_checked_count_by_parent.items():
        if count >= 1 and pid in task_by_id:
            ptask = task_by_id[pid]
            if str(ptask.get("split_stage", "none")) == "suggested":
                ptask["split_stage"] = "processed"
    
    for task in enriched_state:
        tags = task.get("tags") or {}
        
        # Scrub stale priority emojis directly from memory right away so they never leak into Timeliner.
        p_emoji_should_be = _extract_emoji(tags.get("Priority", ""))
        for pe in priority_emojis:
            if pe != p_emoji_should_be:
                if "title" in task and pe in str(task["title"]):
                    task["title"] = str(task["title"]).replace(pe, "").replace("  ", " ").strip()
                if "original_notion_title" in task and pe in str(task["original_notion_title"]):
                    task["original_notion_title"] = str(task["original_notion_title"]).replace(pe, "").replace("  ", " ").strip()
            
        block_id = task.get("notion_block_id") or task.get("id")
        block_type = task.get("notion_type") or task.get("type")
        original_title = task.get("original_notion_title", task.get("title", ""))
        wbs_level = task.get("wbs_level")
        is_generated = bool(task.get("is_generated"))
        generated_selection_processed = bool(task.get("generated_selection_processed", False))
        origin = task.get("origin", "unknown")
        if isinstance(wbs_level, str) and wbs_level.isdigit():
            wbs_level = int(wbs_level)
        
        if block_type == "todo":
            block_type = "to_do"
        elif block_type == "bullet":
            block_type = "bulleted_list_item"

        if not block_type or not block_id:
            continue
        if task.get("is_content_block") or block_type == "quote":
            continue

        checked = task.get("checked") if block_type == "to_do" else None
        is_done = (DONE_MARK in original_title) or bool(checked)
        _parent_id_for_sel = str(task.get("parent_id") or "")
        _sibling_checked_count = _generated_checked_count_by_parent.get(_parent_id_for_sel, 0)
        selection_mode = (
            block_type == "to_do"
            and is_generated
            and not generated_selection_processed
            and _sibling_checked_count >= 1
        )
        is_selected_generated_l4 = selection_mode and bool(checked) and wbs_level == 4

        depth = int(task.get("depth", 0))
        
        # Pre-calculate flags for early use before potential wbs_level updates
        _early_convert_sel_non_l4_to_bullet = selection_mode and bool(checked) and wbs_level != 4
        _early_convert_non_sel_non_l4_to_bullet = (
            block_type == "to_do"
            and isinstance(wbs_level, int)
            and wbs_level in (1, 2, 3)
            and not (is_generated and not generated_selection_processed)
        )
        _early_reset_l4_to_unchecked = selection_mode and bool(checked) and wbs_level == 4
        is_pending_selection_change = (
            _early_convert_sel_non_l4_to_bullet
            or _early_convert_non_sel_non_l4_to_bullet
            or _early_reset_l4_to_unchecked
        )

        # No tags: only do a lightweight cleanup for stale WBS prefix text.
        # BUT if the title contains a known theme name OR has manual tag styles, we MUST process it to apply/preserve the badge!
        has_fallback_theme = False
        plain_title_trimmed = original_title.strip()
        for t_name, t_data in themes.items():
            if t_name and t_name in plain_title_trimmed:
                has_fallback_theme = True
                break
            for st in t_data.get("sub_themes", []):
                if st and st in plain_title_trimmed:
                    has_fallback_theme = True
                    break
            if has_fallback_theme:
                break

        if not tags and not has_fallback_theme and not bool(task.get("has_tag_style", False)):
            if block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
                continue

            clean_title = re.sub(r'^\[.*?\]\s*', '', original_title).strip()
            clean_title = _strip_stale_prefix_emojis(clean_title)
            should_normalize_style = bool(task.get("has_tag_style", False))
            if clean_title == original_title and not should_normalize_style and not wbs_emoji:
                continue

            rich_text = []
            if wbs_emoji:
                rich_text.append({
                    "type": "text",
                    "text": {"content": wbs_emoji + " "},
                    "annotations": {"strikethrough": is_done, "color": "gray" if is_done else "default"}
                })
            rich_text.append({
                "type": "text",
                "text": {"content": clean_title},
                "annotations": {"strikethrough": is_done, "color": "gray" if is_done else "default"}
            })
            content_payload = {
                block_type: {
                    "rich_text": rich_text,
                    "color": "gray" if is_done else "default"
                }
            }
            if block_type == "to_do":
                content_payload[block_type]["checked"] = bool(checked)

            try:
                if block_type != "quote":
                    update_block(block_id, content_payload)
                task["title"] = clean_title
                if block_type == "to_do":
                    task["checked"] = bool(checked)
                import sys
                msg = f"Cleaned stale prefix for {block_id}: {clean_title}\n"
                sys.stdout.buffer.write(msg.encode('utf-8'))
            except Exception as e:
                print(f"Failed to clean stale prefix for {block_id}: {e}")
            continue
             
        if block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
            # 鍙垹闄よ LLM 鏍囪杩囩殑 paragraph/heading锛堝凡鍚堝苟鍒板瓙浠诲姟涓殑涓婚鍧楋級
            # tags 涓虹┖鐨?paragraph 鏄敤鎴锋墜鍐欑殑 section heading锛堝 "濠氬Щ"锛夛紝蹇呴』淇濈暀浣滀负 context
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
        # Processed generated tasks should inherit their WBS level based on depth 
        # so they get the same styling as manual tasks.
        if is_generated:
            if generated_selection_processed or is_pending_selection_change:
                inferred_wbs_level = wbs_level if isinstance(wbs_level, int) and 1 <= wbs_level <= 4 else min(depth + 1, 4)
                if not str(tags.get("WBS level", "")).strip():
                    wbs_raw = _raw_wbs_value(inferred_wbs_level)
                    if wbs_raw:
                        tags["WBS level"] = wbs_raw
                        task["tags"] = tags
                        wbs_level = inferred_wbs_level
                        task["wbs_level"] = wbs_level
            else:
                tags.pop("WBS level", None)

        # selection_mode 浠呭湪鍚屼竴 parent 涓?generated checked >= 1 鏃舵縺娲?        # 宸插鐞嗚繃鐨?generated selector 浠诲姟涓嶅啀鍙備笌姝ゆ祦绋嬶紝閬垮厤閲嶅 reset/delete 寰幆
        # 纭繚浜虹被宸茬粡杩涜浜嗕氦浜掞紙鑷冲皯鍕鹃€変簡涓€涓級
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

        # For generated non-L4 rows, checked is a review/selection signal, not completion.
        is_generated_non_l4 = is_generated and isinstance(wbs_level, int) and wbs_level != 4
        is_done = (DONE_MARK in original_title) or (
            bool(checked) and not selection_mode and not is_generated_non_l4
        )
        
        # --- Fast pass if already formatted with Theme/SubTheme ---
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
                
        should_convert_selected_non_l4_to_bullet = selection_mode and bool(checked) and wbs_level != 4
        should_convert_non_selector_non_l4_to_bullet = (
            block_type == "to_do"
            and isinstance(wbs_level, int)
            and wbs_level in (1, 2, 3)
            and not (is_generated and not generated_selection_processed)
        )
        should_reset_l4_to_unchecked = selection_mode and bool(checked) and wbs_level == 4
        should_convert_to_bullet = should_convert_selected_non_l4_to_bullet or should_convert_non_selector_non_l4_to_bullet
        is_pending_selection_change = (
            should_convert_selected_non_l4_to_bullet
            or should_convert_non_selector_non_l4_to_bullet
            or should_reset_l4_to_unchecked
        )
        is_scoped_task = task.get("timeliner_rank") is not None
        mode_val_for_restore = str(tags.get("Modes", "")).strip()
        missing_mode_render = False
        if mode_val_for_restore:
            for mode_cfg in structured_cfg.get("modes", []):
                mode_name = str(mode_cfg.get("mode_name", "")).strip()
                if mode_name and mode_name in mode_val_for_restore and mode_name not in original_title:
                    missing_mode_render = True
                    break
        task_type_emoji = _extract_emoji(tags.get("Task Type", ""))
        missing_task_type_render = bool(task_type_emoji and task_type_emoji not in original_title)
        needs_processed_l4_wbs_restore = (
            is_generated
            and generated_selection_processed
            and wbs_level == 4
            and bool(tags.get("WBS level"))
            and _extract_emoji(tags.get("WBS level", "")) not in original_title
        )
        needs_processed_l4_mode_tasktype_restore = (
            is_generated
            and generated_selection_processed
            and wbs_level == 4
            and is_scoped_task
            and (missing_mode_render or missing_task_type_render)
        )

        # Bypass formatting for unselected suggested tasks so they don't get compacted or restyled
        # But do not bypass if we need to restore/prepend or strip the unreviewed generated prefix "🤖💬🔜"
        needs_generated_prefix_restore = is_generated and not generated_selection_processed and "🤖💬🔜" not in original_title
        needs_generated_prefix_strip = is_generated and generated_selection_processed and "🤖💬🔜" in original_title
        has_unwanted_theme_badge = (
            is_generated
            and not generated_selection_processed
            and is_already_themed
            and bool(task.get("has_tag_style"))
        )
        is_unselected_suggested = is_generated and not generated_selection_processed
        if (
            is_unselected_suggested
            and not is_pending_selection_change
            and not needs_processed_l4_wbs_restore
            and not needs_processed_l4_mode_tasktype_restore
            and not needs_generated_prefix_restore
            and not needs_generated_prefix_strip
            and not has_unwanted_theme_badge
        ):
            task["synced_tags"] = True
            continue



        # Check if WBS emoji or Priority emojis are missing or stale
        wbs_val = tags.get("WBS level", "")
        wbs_emoji = _extract_emoji(wbs_val)
        missing_wbs = bool(wbs_emoji and wbs_emoji not in original_title)
        
        emojis_that_should_be_there = _ordered_visible_tag_emojis(tags)
        missing_emojis = any(e not in original_title for e in emojis_that_should_be_there)

        # A prefix emoji is stale if it's in the title but no longer active in tags.
        has_stale_prefix = False
        for e in known_prefix_emojis:
            if e in original_title and e not in emojis_that_should_be_there and e != wbs_emoji:
                has_stale_prefix = True
                break

        # Check if the row might need colon-italic styling or word-count compaction
        needs_colon_formatting = ":" in original_title
        char_limit = _char_limit_for_depth(task.get("depth", 0))
        needs_compaction = len(str(original_title or "")) > char_limit

        # If it has tag style (e.g. bold/code) and begins with a theme/subtheme,
        # we bypass the rich text reconstruction and API update.
        # BUT we DO NOT bypass if it contains a colon, exceeds word limit, or has tag changes.
        if is_already_themed and task.get("has_tag_style") and not is_pending_selection_change and not needs_colon_formatting and not needs_compaction and not missing_wbs and not has_stale_prefix and not missing_emojis and not has_unwanted_theme_badge:
            task["synced_tags"] = True
            continue
        # --------------------------------------------------------
        
        # Clean previous generated prefixes to prevent stacking
        clean_title = original_title
        if "🤖💬🔜" in clean_title:
            clean_title = clean_title.replace("🤖💬🔜", "")
        # Remove [emoji_block] if any
        clean_title = re.sub(r'^\[.*?\]\s*', '', clean_title)
        # Strip all known prefix emojis to ensure no stale or misplaced emojis remain
        for e in known_prefix_emojis:
            clean_title = clean_title.replace(e, "")
        clean_title = clean_title.strip()
        
        rich_text = []
        wbs_val = tags.get("WBS level", "")
        wbs_emoji = _extract_emoji(wbs_val)

        theme_val = tags.get("Task Theme with colour", "")
        custom_theme_color = "default"

        if not theme_val:
            for t_name in themes.keys():
                if t_name and t_name in original_title:
                    theme_val = t_name
                    break
            if not theme_val:
                for t_name, t_data in themes.items():
                    for st in t_data.get("sub_themes", []):
                        if st and st in original_title:
                            theme_val = st
                            break
                    if theme_val:
                        break


        if task.get("notion_rich_text"):
            for rt in task["notion_rich_text"]:
                if rt.get("type") == "text":
                    annos = rt.get("annotations", {})
                    rt_content = rt.get("text", {}).get("content", "").strip()
                    # Themes are bold and code
                    if not theme_val and annos.get("code") and annos.get("bold") and rt_content:
                        theme_val = rt_content
                        custom_theme_color = annos.get("color", "default")

        mode_val = tags.get("Modes", "")
        
        if not mode_val:
            for mode_cfg in structured_cfg.get("modes", []):
                m_name = mode_cfg.get("mode_name", "")
                if m_name and m_name in clean_title:
                    mode_val = m_name
                    break
        
        target_color = "default"
        theme_str = ""
        should_strip_theme_label_from_title = True
        
        if theme_val:
            original_theme_name = str(theme_val).split()[0]
            main_theme_name = original_theme_name
            context_heading = str(task.get("context_heading", "")).strip()
            
            # Fallback 1: 鐢ㄦ竻鐞嗗悗鐨勬爣棰橀璇嶏紙鍘绘帀宸叉湁涓婚鍚嶅拰 mode 鍚嶏級鍋?context
            if not context_heading and clean_title:
                # 鍏堜粠 clean_title 涓幓鎺夋墍鏈夊凡鍐欎富棰樺悕锛岄伩鍏嶄箣鍓嶉敊璇帹閫佺殑涓婚鍚嶅惊鍜悕 涓?
                fallback_title = clean_title
                for t_name in themes.keys():
                    fallback_title = fallback_title.replace(t_name, "").strip()
                if fallback_title:
                    context_heading = fallback_title.split()[0].strip()
            
            # 浠呭綋 LLM 杩斿洖鐨勪富棰樹笉鏄湁鏁?config 涓婚鏃讹紝鎵嶇敤 context_heading 瑕嗙洊
            if main_theme_name not in themes and context_heading:
                for t_name, t_data in themes.items():
                    if context_heading == t_name or context_heading in t_data.get("sub_themes", []):
                        main_theme_name = t_name
                        break
                        
            if main_theme_name in themes:
                target_color = themes[main_theme_name].get("color", "default")
            else:
                target_color = custom_theme_color
                for t_name, t_data in themes.items():
                    if main_theme_name in t_data.get("sub_themes", []):
                        target_color = t_data.get("color", "default")
                        main_theme_name = t_name
                        break

            theme_str = _resolve_display_theme_label(task, main_theme_name)
            theme_to_strip = theme_str
            
            should_strip_theme_label_from_title = True
            
            wbs_level_int = None
            try:
                if task.get("wbs_level") is not None:
                    wbs_level_int = int(task.get("wbs_level"))
            except (TypeError, ValueError):
                pass
            
            if main_theme_name in themes:
                known_sub_themes = set(themes[main_theme_name].get("sub_themes", []))
                if theme_to_strip and theme_to_strip != main_theme_name and theme_to_strip not in known_sub_themes:
                    # Dynamic display labels (not part of configured sub-themes)
                    # should not erase semantically meaningful words in task title.
                    should_strip_theme_label_from_title = False
                    
            if is_generated and not generated_selection_processed and not is_pending_selection_change:
                # Never show theme badge on raw generated tasks
                theme_str = ""
            elif wbs_level_int in (3, 4):
                # Only wbs lv 1 and 2 shows theme badge, wbs lv 3 and 4 not need to show
                theme_str = ""
                            
            # 绉婚櫎鎵€鏈夊凡鍐欎富棰樺悕锛岄槻姝箣鍓嶉敊璇帹閫佺殑涓婚鍚嶆畫鐣?
            for t_name in themes.keys():
                if t_name and t_name in clean_title:
                    clean_title = clean_title.replace(t_name, "").strip()
            if original_theme_name and original_theme_name in clean_title:
                clean_title = clean_title.replace(original_theme_name, "").strip()
            if should_strip_theme_label_from_title and theme_to_strip and theme_to_strip in clean_title:
                clean_title = clean_title.replace(theme_to_strip, "").strip()
        
        # Determine Priority and Task Type emojis
        priority_emoji = _extract_emoji(tags.get("Priority", ""))
        task_type_emoji = _extract_emoji(tags.get("Task Type", ""))

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
            if should_strip_theme_label_from_title and theme_str in clean_title:
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

        # 2. Priority formatting
        if priority_emoji:
            if priority_emoji in clean_title:
                clean_title = clean_title.replace(priority_emoji, "").strip()
            rich_text.append({
                "type": "text",
                "text": {"content": priority_emoji},
                "annotations": {"strikethrough": is_done, "color": "gray" if is_done else "default"}
            })

        # 3. Mode formatting
        if mode_val:
            for mode_cfg in structured_cfg.get("modes", []):
                mode_name = mode_cfg.get("mode_name", "")
                if not mode_name: continue
                if mode_name in mode_val:
                    mode_annos = mode_cfg.get("annotations", {"color": "default", "bold": False, "code": False, "italic": False, "strikethrough": False, "underline": False})
                    if mode_name in clean_title:
                        clean_title = clean_title.replace(mode_name, "").strip()
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

        # 4. Task Type formatting
        if task_type_emoji:
            if task_type_emoji in clean_title:
                clean_title = clean_title.replace(task_type_emoji, "").strip()
            rich_text.append({
                "type": "text",
                "text": {"content": task_type_emoji},
                "annotations": {"strikethrough": is_done, "color": "gray" if is_done else "default"}
            })

        # 5. ordered visible tag emojis + title render锛堝惈 word-count 鍘嬬缉锛?
        is_hierarchically_complete = False
        total_tracked_hours = 0.0

        if wbs_level in [1, 2, 3]:
            tags_synced = bool(task.get("synced_tags", False))
            split_stage = task.get("split_stage", "none")
            has_passed_stages = tags_synced and split_stage not in ["none", "suggested"]

            is_valid_flow = (origin == "human" or generated_selection_processed) and has_passed_stages

            if is_valid_flow:
                if _is_task_complete(str(block_id)):
                    is_hierarchically_complete = True
                    total_tracked_hours = _calculate_total_hours(str(block_id))

        if is_generated and not generated_selection_processed and not is_pending_selection_change:
            clean_title = f"🤖💬🔜{clean_title}"

        detected_emojis = []
        for e in known_prefix_emojis:
            if e in original_title and e not in emojis_that_should_be_there and e != wbs_emoji:
                if e in wbs_emojis:
                    continue  # Do not carry forward stale WBS tags
                if e in priority_emojis:
                    continue  # Do not carry forward stale Priority tags
                if e in task_type_emojis:
                    continue  # Do not carry forward stale Task Type tags
                detected_emojis.append(e)

        rich_text, _visible_title = _render_standard_row_tail(
            rich_text=rich_text,
            tags=tags,
            clean_title=clean_title,
            is_done=is_done,
            depth=task.get("depth", 0),
            total_tracked_hours=total_tracked_hours,
            is_hierarchically_complete=is_hierarchically_complete,
            links=task.get("links") if isinstance(task.get("links"), list) else None,
            extra_emojis=detected_emojis
        )
        
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

        should_convert_to_bullet = should_convert_selected_non_l4_to_bullet or should_convert_non_selector_non_l4_to_bullet
        if should_convert_to_bullet:
            parent_id = task.get("parent_id")
            if not parent_id:
                print(f"Cannot convert to bullet: missing parent_id for {block_id}")
            else:
                try:
                    child_payloads = _child_payloads_for_replacement(str(block_id))
                    new_block = replace_with_bullet(
                        block_id,
                        parent_id,
                        rich_text,
                        color="gray" if is_done else "default",
                        children=child_payloads,
                    )
                    new_block_id = new_block.get("id")
                    before = {
                        "task_id": block_id,
                        "block_type": "to_do",
                        "checked": bool(checked),
                        "wbs_level": wbs_level,
                        "origin": origin
                    }
                    if new_block_id:
                        task["id"] = new_block_id
                        task["notion_block_id"] = new_block_id
                        _repoint_descendants(str(block_id), str(new_block_id))
                    task["notion_type"] = "bulleted_list_item"
                    task["type"] = "bullet"
                    task["checked"] = None
                    task["synced_tags"] = True
                    if should_convert_selected_non_l4_to_bullet:
                        task["generated_selection_processed"] = True
                    task["title"] = new_plain_title
                    if should_convert_selected_non_l4_to_bullet:
                        log_generated_preference_diff(
                            task=task,
                            action="convert_checked_non_l4_to_bullet",
                            before=before,
                            after={
                                "block_type": "bulleted_list_item",
                                "checked": None,
                                "new_task_id": new_block_id
                            }
                        )
                    
                    import sys
                    msg = f"Converted non-L4 to-do to bullet for {block_id}: {new_plain_title}\n"
                    sys.stdout.buffer.write(msg.encode('utf-8'))
                    continue
                except Exception as e:
                    print(f"Failed to convert to bullet for {block_id}: {e}")
        if task.get("synced_tags") and new_plain_title == original_title and (block_type != "to_do" or bool(checked) == checked_for_payload):
            continue
        
        try:
            if block_type != "quote":
                update_block(block_id, content_payload)
            task["synced_tags"] = True
            task["title"] = new_plain_title
            if block_type == "to_do":
                task["checked"] = checked_for_payload
            if should_reset_l4_to_unchecked:
                task["generated_selection_processed"] = True
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

def push_subtasks_to_notion(
    task_id: str,
    subtasks: List[str],
    parent_theme: str = None,
    parent_theme_color: str = "default"
) -> List[Dict[str, Any]]:
    """Creates physical to_do blocks under the parent abstract task and returns created block IDs/titles."""
    from notion_client import append_children
    if not subtasks:
        return []

    children_payload = []
    for st in subtasks:
        rich_text_array = []
        
        # Removed logic prepending parent_theme as a badge
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
        from notion_client import append_children, get_page_blocks
        
        # 鑾峰彇鐖跺潡鐨勭幇鏈夊瓙鍧楋紝鐢ㄤ簬纭畾鎻掑叆浣嶇疆
        # 鐩爣锛氬皢鏂板瓙浠诲姟鎻掑埌 quote/paragraph 璇存槑鍧椾箣鍚庛€佸叾浠栧唴瀹逛箣鍓?
        existing_children = []
        try:
            existing_children = get_page_blocks(task_id)
        except Exception:
            pass
            
        # 鎵弿寮€澶磋繛缁殑 quote/paragraph 鍧楋紝璁板綍鏈€鍚庝竴涓殑 ID
        after_id = None
        for child in existing_children:
            ctype = child.get("type", "")
            if ctype in ["quote", "paragraph"]:
                after_id = child.get("id")
            else:
                break

        if after_id:
            # 鏈夎鏄庡潡锛氭彃鍏ュ埌鏈€鍚庝竴涓?quote/paragraph 涔嬪悗
            append_res = append_children(task_id, children_payload, after_id=after_id)
        else:
            # 鏃犺鏄庡潡锛堢┖瀹瑰櫒鎴栫洿鎺ユ槸浠诲姟锛夛細鐩存帴杩藉姞鍗冲彲
            # 娉ㄦ剰锛歱osition="start" 闇€瑕?Notion API >= 2026-03-11锛屽綋鍓嶇増鏈笉鏀寔
            append_res = append_children(task_id, children_payload)
            
        results = append_res.get("results", []) if isinstance(append_res, dict) else []
        created: List[Dict[str, Any]] = []
        for idx, block in enumerate(results):
            block_id = str(block.get("id") or "").strip()
            if not block_id:
                continue
            title = subtasks[idx] if idx < len(subtasks) else ""
            created.append({"id": block_id, "title": title})

        import sys
        sys.stdout.buffer.write(f"Added {len(subtasks)} physical subtasks to the top of {task_id}\n".encode('utf-8'))
        return created
    except Exception as e:
        print(f"Failed to add subtasks to {task_id}: {e}")
        return []


def push_root_order_to_notion(before_state: List[Dict[str, Any]], after_state: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Physical root rank reordering: diffs roots order, deep clones the misplaced ones to the correct spot,
    then deletes the originals.
    """
    from notion_client import append_children, delete_block, get_page_blocks

    def _task_id(task: Dict[str, Any]) -> str:
        return str(task.get("notion_block_id") or task.get("id") or "")

    def _default_parent_id() -> str:
        from config import DFORGE_LINESV2_PAGE_ID
        return DFORGE_LINESV2_PAGE_ID

    def _build_root_sequence(state: List[Dict[str, Any]]) -> List[str]:
        task_by_id = {_task_id(t): t for t in state if _task_id(t)}
        seen = set()
        roots = []
        for task in state:
            current_id = _task_id(task)
            current = task
            visited = set()
            while current_id and current_id not in visited:
                visited.add(current_id)
                parent_id = str(current.get("parent_id") or "")
                parent = task_by_id.get(parent_id)
                if not parent:
                    break
                current = parent
                current_id = _task_id(parent)
            if current_id and current_id not in seen:
                seen.add(current_id)
                roots.append(current_id)
        return roots

    def _drop_duplicate_roots_from_state(state: List[Dict[str, Any]], root_ids: List[str]) -> List[Dict[str, Any]]:
        task_by_id = {_task_id(t): t for t in state if _task_id(t)}
        kept_by_title = set()
        duplicate_root_ids = set()
        for root_id in root_ids:
            task = task_by_id.get(root_id)
            if not task:
                continue
            title = str(task.get("original_notion_title", task.get("title", "")) or "")
            title_key = _dedupe_visible_title(title)
            if not title_key:
                continue
            if title_key in kept_by_title:
                duplicate_root_ids.add(root_id)
            else:
                kept_by_title.add(title_key)
        if not duplicate_root_ids:
            return state

        children_map = {}
        for task in state:
            tid = _task_id(task)
            pid = str(task.get("parent_id") or "")
            if pid and tid:
                children_map.setdefault(pid, []).append(task)
        duplicate_subtree_ids = set()
        for root_id in duplicate_root_ids:
            stack = [root_id]
            while stack:
                current = stack.pop()
                if current in duplicate_subtree_ids:
                    continue
                duplicate_subtree_ids.add(current)
                for child in children_map.get(current, []):
                    child_id = _task_id(child)
                    if child_id:
                        stack.append(child_id)
        return [task for task in state if _task_id(task) not in duplicate_subtree_ids]

    before_roots = _build_root_sequence(before_state)
    after_roots = _build_root_sequence(after_state)
    parent_ids = {
        str((next((t for t in after_state if _task_id(t) == rid), {}) or {}).get("parent_id") or _default_parent_id())
        for rid in after_roots
    }
    for parent_id in parent_ids:
        try:
            _archive_duplicate_direct_children_by_title(parent_id, preferred_ids=after_roots)
        except Exception as e:
            print(f"Warning: Failed duplicate root cleanup for {parent_id}: {e}")
    after_state = _drop_duplicate_roots_from_state(after_state, after_roots)
    after_roots = _build_root_sequence(after_state)

    if before_roots == after_roots:
        return after_state

    import sys
    sys.stdout.buffer.write(f"Physical Root Rank Reordering: synchronizing order to Notion...\n".encode('utf-8'))
    
    current_physical_order = list(before_roots)
    state = list(after_state)

    def _normalize_block_type(task: Dict[str, Any]) -> str:
        block_type = task.get("notion_type") or task.get("type") or ""
        if block_type == "todo":
            return "to_do"
        if block_type == "bullet":
            return "bulleted_list_item"
        return block_type

    def _build_block_payload(task: Dict[str, Any]) -> Dict[str, Any]:
        block_type = _normalize_block_type(task)
        if block_type == "numbered_list_item":
            block_type = "bulleted_list_item"
        annotations = task.get("annotations", {}) if isinstance(task.get("annotations"), dict) else {}
        color = annotations.get("color", "default")
        title = str(task.get("original_notion_title", task.get("title", "")) or "").strip()
        rich_text = _rich_text_for_task_creation(task, title)

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
        base = {
            "object": "block",
            "type": block_type if block_type in ["bulleted_list_item", "numbered_list_item", "toggle", "heading_1", "heading_2", "heading_3", "quote"] else "paragraph"
        }
        b_type = base["type"]
        base[b_type] = {
            "rich_text": rich_text,
            "color": color
        }
        return base

    def _batch_clone_children(
        source_tasks: List[Dict[str, Any]],
        new_parent_id: str,
        children_map: Dict[str, List[Dict[str, Any]]],
        after_id: str = None,
        position: str = None
    ) -> List[Dict[str, Any]]:
        from notion_client import append_children
        # note: _normalize_uuid is defined at the module level in sync_engine.py
        safe_parent_id = _normalize_uuid(new_parent_id)
        payloads = [_build_block_payload(t) for t in source_tasks]

        append_res = append_children(safe_parent_id, payloads, after_id=after_id, position=position)
        results = append_res.get("results") or []
        if len(results) > len(source_tasks):
            results = results[:len(source_tasks)]
        new_ids = [str(r.get("id") or "") for r in results]
        
        missing = [i for i, nid in enumerate(new_ids) if not nid]
        if missing:
            raise RuntimeError(f"Missing IDs for cloned blocks at indices {missing}")

        cloned_flat: List[Dict[str, Any]] = []
        for source_task, new_id in zip(source_tasks, new_ids):
            source_id = _task_id(source_task)
            cloned_root = source_task.copy()
            cloned_root["id"] = new_id
            cloned_root["notion_block_id"] = new_id
            cloned_root["parent_id"] = new_parent_id
            cloned_flat.append(cloned_root)

            grandchildren = children_map.get(source_id, [])
            if grandchildren:
                cloned_flat.extend(
                    _batch_clone_children(grandchildren, new_id, children_map)
                )
            
            # Component 3: Clone orphan Notion children (quotes, manual notes) not in state
            # We check if the block has children in Notion that weren't tracked as tasks.
            try:
                actual_notion_children = get_page_blocks(source_id)
                # Filter for children not present in state (children_map)
                state_child_ids = {str(t.get("notion_block_id") or t.get("id") or "") for t in grandchildren}
                orphans = [c for c in actual_notion_children if str(c.get("id")) not in state_child_ids]
                
                if orphans:
                    from notion_client import append_children
                    orphan_payloads = [_rebuild_notion_block_payload(o) for o in orphans]
                    append_children(_normalize_uuid(new_id), orphan_payloads)
            except Exception as e:
                print(f"Warning: Failed to clone orphan children for {source_id} -> {new_id}: {e}")
        return cloned_flat

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

    for i, target_root in enumerate(after_roots):
        if i < len(current_physical_order) and current_physical_order[i] == target_root:
            continue

        children_map = {}
        for task in state:
            tid = _task_id(task)
            pid = str(task.get("parent_id") or "")
            if pid and tid:
                children_map.setdefault(pid, []).append(task)
        
        task_by_id = {_task_id(t): t for t in state if _task_id(t)}
        target_task = task_by_id.get(target_root)
        if not target_task:
            continue
            
        parent_id = str(target_task.get("parent_id") or "")
        if not parent_id:
             parent_id = _default_parent_id()
        
        old_id = target_root
        prev_id = after_roots[i-1] if i > 0 else None
        
        position = "start" if prev_id is None else None
        
        block_title_prt = str(target_task.get("original_notion_title", target_task.get("title", "")))[:20]
        sys.stdout.buffer.write(f"  -> Moving block '{block_title_prt}' to physical position {i}\n".encode('utf-8'))
        
        try:
            cloned_flat = _batch_clone_children([target_task], parent_id, children_map, after_id=prev_id, position=position)
            new_id = cloned_flat[0]["id"]
            delete_block(_normalize_uuid(old_id))
            
            after_roots[i] = new_id
            
            if old_id in current_physical_order:
                current_physical_order.remove(old_id)
            current_physical_order.insert(i, new_id)
            
            old_subtree_ids = _collect_subtree_ids(old_id, children_map)
            
            insert_idx = next((idx for idx, t in enumerate(state) if _task_id(t) == old_id), len(state))
            remaining = [t for t in state if _task_id(t) not in old_subtree_ids]
            state = remaining[:insert_idx] + cloned_flat + remaining[insert_idx:]
        except Exception as e:
            sys.stdout.buffer.write(f"  -> Failed moving block '{block_title_prt}': {e}\n".encode('utf-8'))

    sys.stdout.buffer.write(f"Physical Root Rank Reordering complete.\n".encode('utf-8'))
    for parent_id in parent_ids:
        try:
            _archive_duplicate_direct_children_by_title(parent_id, preferred_ids=after_roots)
        except Exception as e:
            print(f"Warning: Failed duplicate root cleanup for {parent_id}: {e}")
    return state
