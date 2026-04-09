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

def _normalize_uuid(raw_id: str) -> str:
    """将 32 位无连字符的 hex ID 转换为标准 UUID 格式 (8-4-4-4-12)。
    Notion API 要求 UUID 格式，但 page ID 在 config 中可能不带连字符。
    """
    if not raw_id:
        return raw_id
    clean = raw_id.replace("-", "")
    if len(clean) == 32:
        return f"{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}"
    return raw_id

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
            # Fallback for previously prefixed rows, e.g. "鍛造Lab 鍛造Maker".
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
        # 将编号列表转为无序列表（用户要求子主题下所有内容使用 bullet 格式）
        if block_type == "numbered_list_item":
            block_type = "bulleted_list_item"
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

    def _batch_clone_children(
        source_tasks: List[Dict[str, Any]],
        new_parent_id: str,
        children_map: Dict[str, List[Dict[str, Any]]],
        after_id: str = None
    ) -> List[Dict[str, Any]]:
        """批量将 source_tasks 内容创建到 new_parent_id 下，不使用 after 参数避免 ID 重用。
        返回平展后的克隆任务列表。
        """
        if not source_tasks:
            return []

        safe_parent_id = _normalize_uuid(new_parent_id)

        # 一次性批量 append 所有 direct children（不带 after）以避免 ID 重用 bug
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

            # 递归处理该节点的子节点（同样批量不带 after）
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
            # Keep deeper hierarchy (e.g. 3dpF under 鍛造Maker) intact.
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
        # one-child grouping wrappers (e.g. "我流方矩 刚体" -> "刚体打造和训练论").
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

        # 解析容器匹配到的子主题名，用于传播给子节点的 theme_display_label
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

        # 传播 theme_display_label 到直接子节点
        # clone 后直接子节点的 parent_id == container_parent_id（容器的父级）
        if container_matched_subtheme:
            for cloned in cloned_flat:
                # 仅对直接子节点设置 label（深层子节点的 parent_id 不等于 container_parent_id）
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
    from notion_client import update_block, replace_with_toggle_item, replace_with_bullet, delete_block
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

    def _split_title_with_limit(title: str, depth: Any, tag_char_count: int) -> tuple[str, str]:
        raw_title = str(title or "").strip()
        if not raw_title:
            return ("", "")

        allowed_total = _char_limit_for_depth(depth)
        try:
            consumed_chars = int(tag_char_count)
        except (TypeError, ValueError):
            consumed_chars = 0

        allowed_title_chars = max(1, allowed_total - max(0, consumed_chars))
        if len(raw_title) <= allowed_title_chars:
            return (raw_title, "")

        # Split only on whitespace so we never cut in the middle of a word.
        split_at = raw_title.rfind(" ", 0, allowed_title_chars + 1)
        if split_at > 0:
            visible = raw_title[:split_at].rstrip()
            overflow = raw_title[split_at + 1:].lstrip()
            return (visible, overflow)

        # No earlier whitespace; keep the first whole word even if it exceeds limit.
        next_space = raw_title.find(" ", allowed_title_chars)
        if next_space != -1:
            visible = raw_title[:next_space].rstrip()
            overflow = raw_title[next_space + 1:].lstrip()
            return (visible, overflow)

        # Single-word title: keep as-is (no mid-word split).
        return (raw_title, "")

    def _append_title_segments(rich_text: List[Dict[str, Any]], visible_title: str, is_done: bool):
        base_annos = {"strikethrough": is_done, "color": "gray" if is_done else "default"}
        title_text = str(visible_title or "").strip()
        if not title_text:
            rich_text.append({
                "type": "text",
                "text": {"content": " "},
                "annotations": base_annos.copy()
            })
            return

        if ":" not in title_text:
            rich_text.append({
                "type": "text",
                "text": {"content": title_text},
                "annotations": base_annos.copy()
            })
            return

        task_part, desc_part = title_text.split(":", 1)
        task_part = task_part.strip()
        desc_part = desc_part.strip()

        if task_part:
            rich_text.append({
                "type": "text",
                "text": {"content": f"{task_part} : "},
                "annotations": base_annos.copy()
            })
        else:
            rich_text.append({
                "type": "text",
                "text": {"content": ": "},
                "annotations": base_annos.copy()
            })

        if desc_part:
            desc_annos = base_annos.copy()
            desc_annos["italic"] = True
            desc_annos["color"] = "gray"
            rich_text.append({
                "type": "text",
                "text": {"content": desc_part},
                "annotations": desc_annos
            })

    def _ordered_visible_tag_emojis(tags: Dict[str, Any]) -> List[str]:
        emojis: List[str] = []
        seen: set[str] = set()

        # Enforce visible row order: Priority -> Task Type -> other emoji tags.
        for key in ["Priority", "Task Type"]:
            if key not in tags:
                continue
            emoji = _extract_emoji(tags.get(key, ""))
            if emoji and emoji not in seen:
                seen.add(emoji)
                emojis.append(emoji)

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
    ) -> tuple[List[Dict[str, Any]], str, str]:
        emojis = _ordered_visible_tag_emojis(tags)
        if emojis:
            emojis_str = "".join(emojis)
            for e in emojis:
                clean_title = clean_title.replace(e, "").strip()
            rich_text.append({
                "type": "text",
                "text": {"content": emojis_str + " "},
                "annotations": {"strikethrough": is_done, "color": "gray" if is_done else "default"}
            })

        tag_char_count = sum(
            len(str(rt.get("text", {}).get("content", "")))
            for rt in rich_text
        )
        visible_title, overflow_title = _split_title_with_limit(
            clean_title.strip(),
            depth,
            tag_char_count
        )
        _append_title_segments(rich_text, visible_title, is_done)
        return rich_text, visible_title, overflow_title

    task_by_id: Dict[str, Dict[str, Any]] = {}
    for t in enriched_state:
        tid = str(t.get("notion_block_id") or t.get("id") or "")
        if tid:
            task_by_id[tid] = t
    
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
                
        should_convert_to_bullet = selection_mode and bool(checked) and wbs_level != 4
        should_reset_l4_to_unchecked = selection_mode and bool(checked) and wbs_level == 4
        is_pending_selection_change = should_convert_to_bullet or should_reset_l4_to_unchecked

        # Check if the row might need colon-italic styling or overflow handling
        needs_colon_formatting = ":" in original_title
        char_limit = _char_limit_for_depth(task.get("depth", 0))
        needs_overflow = len(str(original_title or "")) > char_limit

        # If it has tag style (e.g. bold/code) and begins with a theme/subtheme,
        # we bypass the rich text reconstruction and API update.
        # BUT we DO NOT bypass if it contains a colon or exceeds char limits (so they continue getting processed for overflow/styling).
        if is_already_themed and task.get("has_tag_style") and not is_pending_selection_change and not needs_colon_formatting and not needs_overflow:
            task["synced_tags"] = True
            continue
        # --------------------------------------------------------
        
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
        should_strip_theme_label_from_title = True
        
        if theme_val:
            original_theme_name = str(theme_val).split()[0]
            main_theme_name = original_theme_name
            context_heading = str(task.get("context_heading", "")).strip()
            
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
                        
            if main_theme_name in themes:
                target_color = themes[main_theme_name].get("color", "default")

            theme_str = _resolve_display_theme_label(task, main_theme_name)
            if main_theme_name in themes:
                known_sub_themes = set(themes[main_theme_name].get("sub_themes", []))
                if theme_str and theme_str != main_theme_name and theme_str not in known_sub_themes:
                    # Dynamic display labels (not part of configured sub-themes)
                    # should not erase semantically meaningful words in task title.
                    should_strip_theme_label_from_title = False

            current_theme_key = str(main_theme_name or original_theme_name or "").strip()
            parent_theme_key = ""
            parent_id = str(task.get("parent_id") or "")
            parent_task = task_by_id.get(parent_id)
            if parent_task:
                parent_tags = parent_task.get("tags") or {}
                parent_theme_val = parent_tags.get("Task Theme with colour", "")
                if parent_theme_val:
                    parent_theme_key = str(parent_theme_val).split()[0].strip()
            if parent_theme_key and current_theme_key and parent_theme_key == current_theme_key:
                # Parent already carries the same main theme, so avoid repeating it on the child row.
                theme_str = ""
                            
            # 移除所有已知主题名，防止之前错误推送的主题名残留
            for t_name in themes.keys():
                if t_name and t_name in clean_title:
                    clean_title = clean_title.replace(t_name, "").strip()
            if original_theme_name and original_theme_name in clean_title:
                clean_title = clean_title.replace(original_theme_name, "").strip()
            if should_strip_theme_label_from_title and theme_str and theme_str in clean_title:
                clean_title = clean_title.replace(theme_str, "").strip()
        
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
        # 3. ordered visible tag emojis + title render
        rich_text, _visible_title, overflow_title = _render_standard_row_tail(
            rich_text=rich_text,
            tags=tags,
            clean_title=clean_title,
            is_done=is_done,
            depth=task.get("depth", 0),
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
        if overflow_title and not is_pending_selection_change:
            parent_id = task.get("parent_id")
            if not parent_id:
                print(f"Cannot convert overflow task to toggle: missing parent_id for {block_id}")
            else:
                overflow_children = [{
                    "object": "block",
                    "type": "quote",
                    "quote": {
                        "rich_text": [{
                            "type": "text",
                            "text": {"content": overflow_title},
                            "annotations": {"italic": True, "color": "gray"}
                        }],
                        "color": "gray"
                    }
                }]
                try:
                    new_block = replace_with_toggle_item(
                        block_id,
                        parent_id,
                        rich_text,
                        color="gray" if is_done else "default",
                        children=overflow_children
                    )
                    new_block_id = new_block.get("id")
                    if new_block_id:
                        task["id"] = new_block_id
                        task["notion_block_id"] = new_block_id
                    task["notion_type"] = "toggle"
                    task["type"] = "toggle"
                    task["checked"] = None
                    task["synced_tags"] = True
                    task["title"] = new_plain_title
                    import sys
                    msg = f"Converted overflow text to toggle for {block_id}: {new_plain_title}\n"
                    sys.stdout.buffer.write(msg.encode('utf-8'))
                    continue
                except Exception as e:
                    print(f"Failed to convert overflow task to toggle for {block_id}: {e}")
        should_convert_to_bullet = selection_mode and bool(checked) and wbs_level != 4
        if should_convert_to_bullet:
            parent_id = task.get("parent_id")
            if not parent_id:
                print(f"Cannot convert to bullet: missing parent_id for {block_id}")
            else:
                try:
                    new_block = replace_with_bullet(block_id, parent_id, rich_text, color="gray" if is_done else "default")
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
                    task["notion_type"] = "bulleted_list_item"
                    task["type"] = "bullet"
                    task["checked"] = None
                    task["synced_tags"] = True
                    task["title"] = new_plain_title
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
                    msg = f"Converted checked to-do to bullet for {block_id}: {new_plain_title}\n"
                    sys.stdout.buffer.write(msg.encode('utf-8'))
                    continue
                except Exception as e:
                    print(f"Failed to convert to bullet for {block_id}: {e}")
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
