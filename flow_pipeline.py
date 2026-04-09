import copy
import re
from datetime import datetime
from typing import Any, Dict, List, Set, Tuple

from block_info_reader import build_split_context, build_state_indexes
from config_reader import clean_task_title, load_config, structure_yonctask_config
from llm_pipeline import mode_tasktype_pass, priority_pass, split_task, theme_pass, wbs_pass
from state_manager import STATE_FILE, flatten_tree, merge_states, save_state
from sync_engine import push_subtasks_to_notion, push_tags_to_notion, reparent_theme_containers, sync_from_notion
from task_reader import fetch_and_build_task_tree
from timeliner_reader import fetch_and_parse_timeliner


def _normalize_scope_text(text: str) -> str:
    cleaned = str(text or "").strip().lower()
    cleaned = re.sub(r"^\[.*?\]\s*", "", cleaned).strip()
    cleaned = cleaned.replace("`", "").replace("*", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _load_merged_state() -> Tuple[Dict[str, List[Any]], Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    config_dict = load_config()
    structured_cfg = structure_yonctask_config(config_dict)

    notion_tree = fetch_and_build_task_tree()
    if not notion_tree:
        return config_dict, structured_cfg, notion_tree, []

    flat_notion = flatten_tree(notion_tree)
    working_state = sync_from_notion(flat_notion)
    merged_state = merge_states(notion_tree, working_state)
    return config_dict, structured_cfg, notion_tree, merged_state


def _pick_theme_key(task: Dict[str, Any]) -> str:
    tags = task.get("tags") or {}
    theme_val = str(tags.get("Task Theme with colour", "")).strip()
    if theme_val:
        return theme_val
    display = str(task.get("theme_display_label", "")).strip()
    if display:
        return display
    return str(task.get("context_heading", "")).strip()


def build_timeliner_scope(state: List[Dict[str, Any]]) -> Tuple[Set[str], Dict[str, int], List[str]]:
    entries = fetch_and_parse_timeliner()
    ordered_keys: List[str] = []
    seen: Set[str] = set()
    for entry in entries:
        raw = _normalize_scope_text(entry.colour_subtheme)
        if raw and raw not in seen:
            seen.add(raw)
            ordered_keys.append(raw)

    scoped_ids: Set[str] = set()
    rank_by_task_id: Dict[str, int] = {}

    for task in state:
        task_id = str(task.get("notion_block_id") or task.get("id") or "")
        if not task_id:
            continue

        theme_text = _normalize_scope_text(_pick_theme_key(task))
        title_text = _normalize_scope_text(
            " ".join(
                [
                    str(task.get("title", "")),
                    str(task.get("original_notion_title", "")),
                    str(task.get("context_heading", "")),
                ]
            )
        )

        matched_rank = None
        matched_key = None
        for rank, key in enumerate(ordered_keys):
            theme_ok = bool(key and key in theme_text)
            title_ok = bool(key and key in title_text)
            # Rule fixed by user: Theme+Title must BOTH match.
            if theme_ok and title_ok:
                matched_rank = rank
                matched_key = key
                break

        if matched_rank is None:
            task["timeliner_key"] = None
            task["timeliner_rank"] = None
            continue

        task["timeliner_key"] = matched_key
        task["timeliner_rank"] = matched_rank
        scoped_ids.add(task_id)
        rank_by_task_id[task_id] = matched_rank

    return scoped_ids, rank_by_task_id, ordered_keys


def _root_id(task: Dict[str, Any], task_by_id: Dict[str, Dict[str, Any]]) -> str:
    current_id = str(task.get("notion_block_id") or task.get("id") or "")
    current = task
    visited: Set[str] = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        parent_id = str(current.get("parent_id") or "")
        parent = task_by_id.get(parent_id)
        if not parent:
            return current_id
        current = parent
        current_id = str(parent.get("notion_block_id") or parent.get("id") or "")
    return str(task.get("notion_block_id") or task.get("id") or "")


def _reorder_state_by_root_rank(state: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not state:
        return state

    task_by_id, _ = build_state_indexes(state)
    indexed = list(enumerate(state))

    root_min_rank: Dict[str, int] = {}
    root_first_index: Dict[str, int] = {}
    for idx, task in indexed:
        rid = _root_id(task, task_by_id)
        rank = task.get("timeliner_rank")
        rank_val = int(rank) if isinstance(rank, int) or (isinstance(rank, str) and rank.isdigit()) else 10**9
        root_min_rank[rid] = min(rank_val, root_min_rank.get(rid, 10**9))
        root_first_index.setdefault(rid, idx)

    sorted_roots = sorted(root_first_index.keys(), key=lambda rid: (root_min_rank.get(rid, 10**9), root_first_index[rid]))
    root_order = {rid: pos for pos, rid in enumerate(sorted_roots)}

    return [
        task
        for _, task in sorted(
            indexed,
            key=lambda pair: (
                root_order.get(_root_id(pair[1], task_by_id), 10**9),
                pair[0],
            ),
        )
    ]


def _resolve_parent_theme_for_split(task: Dict[str, Any], structured_cfg: Dict[str, Any]) -> Tuple[str | None, str]:
    themes = structured_cfg.get("themes", {})
    tags = task.get("tags") or {}
    theme_val = str(tags.get("Task Theme with colour", "")).strip()
    theme_key = str(theme_val).split()[0].strip() if theme_val else ""
    if theme_key in themes:
        return theme_key, themes[theme_key].get("color", "default")

    display = str(task.get("theme_display_label", "")).strip()
    if display in themes:
        return display, themes[display].get("color", "default")

    return None, "default"


def _split_scoped_tasks(
    state: List[Dict[str, Any]],
    structured_cfg: Dict[str, Any],
    scoped_ids: Set[str],
) -> None:
    if not scoped_ids:
        return

    task_by_id, children_by_parent = build_state_indexes(state)
    for task in state:
        task_id = str(task.get("notion_block_id") or task.get("id") or "")
        if task_id not in scoped_ids:
            continue

        if str(task.get("split_stage", "none")) == "suggested":
            continue

        if task.get("is_generated"):
            continue

        notion_type = task.get("notion_type") or task.get("type")
        if notion_type not in ["bulleted_list_item", "bullet", "toggle"]:
            continue

        wbs_level = task.get("wbs_level")
        try:
            wbs_level = int(wbs_level) if wbs_level is not None else None
        except (TypeError, ValueError):
            wbs_level = None

        if not isinstance(wbs_level, int) or wbs_level >= 4:
            continue

        raw_title = task.get("original_notion_title", task.get("title", ""))
        clean_title = clean_task_title(raw_title, structured_cfg)
        if len(clean_title) < 5:
            continue

        context_payload = build_split_context(state, task)
        try:
            suggested = split_task(clean_title, context=context_payload)
        except Exception as exc:
            print(f"Failed to split task {task_id}: {exc}")
            continue

        if not suggested:
            continue

        existing_children = children_by_parent.get(task_id, [])
        existing_titles = {
            str(c.get("original_notion_title", c.get("title", ""))).strip().lower()
            for c in existing_children
            if str(c.get("original_notion_title", c.get("title", ""))).strip()
        }
        deduped = []
        for s in suggested:
            key = str(s or "").strip().lower()
            if not key or key in existing_titles:
                continue
            existing_titles.add(key)
            deduped.append(str(s).strip())

        if not deduped:
            continue

        parent_theme, parent_theme_color = _resolve_parent_theme_for_split(task, structured_cfg)
        push_subtasks_to_notion(task_id, deduped, parent_theme, parent_theme_color)
        task["split_stage"] = "suggested"
        task["split_batch_id"] = datetime.utcnow().isoformat() + "Z"


def run_l1() -> List[Dict[str, Any]]:
    config_dict, _, _, state = _load_merged_state()
    if not state:
        print("No tasks found in Notion.")
        return []

    state = theme_pass(state, config_dict)
    state = reparent_theme_containers(state, config_dict)
    push_tags_to_notion(state, config_dict)

    state = [task for task in state if not task.get("deleted")]
    save_state(state, STATE_FILE)
    print("L1 flow complete.")
    return state


def run_l2() -> List[Dict[str, Any]]:
    config_dict, structured_cfg, _, state = _load_merged_state()
    if not state:
        print("No tasks found in Notion.")
        return []

    state = theme_pass(state, config_dict)
    state = reparent_theme_containers(state, config_dict)
    scoped_ids, rank_by_task_id, _ = build_timeliner_scope(state)

    state = wbs_pass(state, config_dict, scoped_ids=scoped_ids)
    state = priority_pass(state, config_dict, scoped_ids=scoped_ids, rank_by_task_id=rank_by_task_id)
    state = _reorder_state_by_root_rank(state)

    # Push tag formatting first; split suggestions are generated after this push,
    # so newly created unchecked suggestions are not reviewed in the same run.
    push_tags_to_notion(state, config_dict)
    state = [task for task in state if not task.get("deleted")]

    _split_scoped_tasks(state, structured_cfg, scoped_ids)
    save_state(state, STATE_FILE)
    print("L2 flow complete.")
    return state


def run_l3() -> List[Dict[str, Any]]:
    config_dict, _, _, state = _load_merged_state()
    if not state:
        print("No tasks found in Notion.")
        return []

    state = theme_pass(state, config_dict)
    state = reparent_theme_containers(state, config_dict)
    scoped_ids, rank_by_task_id, _ = build_timeliner_scope(state)

    state = wbs_pass(state, config_dict, scoped_ids=scoped_ids)
    state = priority_pass(state, config_dict, scoped_ids=scoped_ids, rank_by_task_id=rank_by_task_id)
    state = mode_tasktype_pass(state, config_dict, scoped_ids=scoped_ids)
    state = _reorder_state_by_root_rank(state)

    push_tags_to_notion(state, config_dict)
    state = [task for task in state if not task.get("deleted")]
    save_state(state, STATE_FILE)
    print("L3 flow complete.")
    return state


def run_flow() -> List[Dict[str, Any]]:
    config_dict, structured_cfg, _, state = _load_merged_state()
    if not state:
        print("No tasks found in Notion.")
        return []

    state = theme_pass(state, config_dict)
    state = reparent_theme_containers(state, config_dict)

    scoped_ids, rank_by_task_id, _ = build_timeliner_scope(state)
    state = wbs_pass(state, config_dict, scoped_ids=scoped_ids)
    state = priority_pass(state, config_dict, scoped_ids=scoped_ids, rank_by_task_id=rank_by_task_id)
    state = mode_tasktype_pass(state, config_dict, scoped_ids=scoped_ids)
    state = _reorder_state_by_root_rank(state)

    push_tags_to_notion(state, config_dict)
    state = [task for task in state if not task.get("deleted")]

    _split_scoped_tasks(state, structured_cfg, scoped_ids)
    save_state(state, STATE_FILE)
    print("Full flow complete.")
    return state

