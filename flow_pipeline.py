import copy
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Set, Tuple

from block_info_reader import build_split_context, build_state_indexes
from config_reader import clean_task_title, load_config, structure_yonctask_config
from llm_pipeline import mode_tasktype_pass, priority_pass, split_task, theme_pass, wbs_pass
from state_manager import STATE_FILE, flatten_tree, merge_states, save_state
from sync_engine import push_root_order_to_notion, push_subtasks_to_notion, push_tags_to_notion, reparent_theme_containers, sync_from_notion
from task_reader import fetch_and_build_task_tree
from timeliner_reader import fetch_and_parse_timeliner
from timeliner_state import TIMELINER_STATE_FILE

LOGGER = logging.getLogger(__name__)


def _log_stage(stage: str, message: str) -> None:
    LOGGER.info("[%s] %s", stage, message)


def _task_id(task: Dict[str, Any]) -> str:
    return str(task.get("notion_block_id") or task.get("id") or "")


def _task_title(task: Dict[str, Any]) -> str:
    return str(task.get("original_notion_title") or task.get("title") or "").strip()


def _preview(text: str, limit: int = 48) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 3)] + "..."


def _split_dedupe_key(title: str, structured_cfg: Dict[str, Any]) -> str:
    """Normalize human-styled and generated split titles for duplicate checks."""
    text = str(title or "")
    text = re.sub(r"~~(.*?)~~", r"\1", text)
    text = text.replace("**", "").replace("*", "").replace("`", "")
    text = clean_task_title(text, structured_cfg)
    text = re.split(r"\s*[:：]\s*", text, maxsplit=1)[0]
    text = re.sub(r"^[^\w\s\x00-\x7F]+", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _extract_wbs_level(task: Dict[str, Any]) -> int | None:
    level = task.get("wbs_level")
    if isinstance(level, str) and level.isdigit():
        level = int(level)
    return level if isinstance(level, int) else None


def _extract_priority(task: Dict[str, Any]) -> str:
    tags = task.get("tags") or {}
    return str(tags.get("Priority", "")).strip()


def _snapshot_scoped_values(
    state: List[Dict[str, Any]],
    scoped_ids: Set[str],
    extractor,
) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {}
    for task in state:
        tid = _task_id(task)
        if not tid or tid not in scoped_ids:
            continue
        snapshot[tid] = extractor(task)
    return snapshot


def _format_change_samples(
    changed: List[Tuple[str, Any, Any, str]],
    max_items: int = 5,
) -> str:
    if not changed:
        return "none"
    parts: List[str] = []
    for tid, before_v, after_v, title in changed[:max_items]:
        parts.append(f"{tid[:8]} '{_preview(title, 30)}': {before_v or '-'} -> {after_v or '-'}")
    return "; ".join(parts)


def _log_wbs_change_details(
    stage: str,
    before_state: List[Dict[str, Any]],
    after_state: List[Dict[str, Any]],
    scoped_ids: Set[str],
) -> None:
    before_map = _snapshot_scoped_values(before_state, scoped_ids, _extract_wbs_level)
    after_map = _snapshot_scoped_values(after_state, scoped_ids, _extract_wbs_level)
    after_by_id = {_task_id(t): t for t in after_state if _task_id(t)}

    changed: List[Tuple[str, Any, Any, str]] = []
    manual_changed = 0
    auto_changed = 0
    for tid, after_level in after_map.items():
        before_level = before_map.get(tid)
        if before_level == after_level:
            continue
        task = after_by_id.get(tid, {})
        changed.append((tid, before_level, after_level, _task_title(task)))
        source = str(task.get("wbs_source", "")).strip().lower()
        if source == "manual":
            manual_changed += 1
        else:
            auto_changed += 1

    _log_stage(
        stage,
        (
            f"WBS pass complete: {len(changed)}/{len(scoped_ids)} scoped tasks changed "
            f"(manual={manual_changed}, auto={auto_changed})"
        ),
    )
    _log_stage(stage, f"WBS samples: {_format_change_samples(changed)}")


def _log_priority_change_details(
    stage: str,
    before_state: List[Dict[str, Any]],
    after_state: List[Dict[str, Any]],
    scoped_ids: Set[str],
) -> None:
    before_map = _snapshot_scoped_values(before_state, scoped_ids, _extract_priority)
    after_map = _snapshot_scoped_values(after_state, scoped_ids, _extract_priority)
    after_by_id = {_task_id(t): t for t in after_state if _task_id(t)}

    changed: List[Tuple[str, Any, Any, str]] = []
    forced_last_changed = 0
    for tid, after_priority in after_map.items():
        before_priority = before_map.get(tid, "")
        if before_priority == after_priority:
            continue
        task = after_by_id.get(tid, {})
        changed.append((tid, before_priority, after_priority, _task_title(task)))
        if bool(task.get("timeliner_is_subproject")):
            forced_last_changed += 1

    _log_stage(
        stage,
        (
            f"Priority pass complete: {len(changed)}/{len(scoped_ids)} scoped tasks changed "
            f"(subproject-forced={forced_last_changed})"
        ),
    )
    _log_stage(stage, f"Priority samples: {_format_change_samples(changed)}")


def _build_root_sequence(state: List[Dict[str, Any]]) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
    if not state:
        return [], {}
    task_by_id, _ = build_state_indexes(state)
    seen: Set[str] = set()
    roots: List[str] = []
    for task in state:
        rid = _root_id(task, task_by_id)
        if not rid or rid in seen:
            continue
        seen.add(rid)
        roots.append(rid)
    return roots, task_by_id


def _log_reorder_details(
    stage: str,
    before_state: List[Dict[str, Any]],
    after_state: List[Dict[str, Any]],
) -> None:
    before_roots, _ = _build_root_sequence(before_state)
    after_roots, after_by_id = _build_root_sequence(after_state)
    before_pos = {rid: idx for idx, rid in enumerate(before_roots)}
    moved = sum(1 for idx, rid in enumerate(after_roots) if before_pos.get(rid, idx) != idx)

    previews: List[str] = []
    for rid in after_roots[:5]:
        root_task = after_by_id.get(rid, {})
        rank = root_task.get("timeliner_rank")
        rank_display = rank if isinstance(rank, int) else "-"
        previews.append(f"{rank_display}:{_preview(_task_title(root_task), 26)}")

    _log_stage(
        stage,
        f"Root rank reorder complete: moved {moved}/{len(after_roots)} root tasks",
    )
    _log_stage(stage, f"Root order preview: {' | '.join(previews) if previews else 'none'}")


def _normalize_scope_text(text: str) -> str:
    cleaned = str(text or "").strip().lower()
    cleaned = re.sub(r"^\[.*?\]\s*", "", cleaned).strip()
    cleaned = cleaned.replace("`", "").replace("*", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _has_cached_timeliner_scope() -> bool:
    """
    Return True when timeliner_state.json exists, is newer than 10 minutes,
    and has at least one scoped entry.
    """
    if not os.path.exists(TIMELINER_STATE_FILE):
        return False

    try:
        import time
        import json

        mtime = os.path.getmtime(TIMELINER_STATE_FILE)
        if time.time() - mtime > 600:
            return False

        with open(TIMELINER_STATE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return False

    if not isinstance(payload, dict):
        return False

    main_projects = payload.get("main_projects", {})
    sub_projects = payload.get("sub_projects", {})
    return bool(main_projects) or bool(sub_projects)


def _bootstrap_timeliner_state_if_needed(stage: str) -> None:
    """
    Ensure flow scope has stable TIMELINER cache. If absent/empty, run timeliner sync once.
    """
    if _has_cached_timeliner_scope():
        _log_stage(stage, "TIMELINER cache found and fresh (timeliner_state.json)")
        return

    _log_stage(
        stage,
        (
            "TIMELINER cache missing, expired (>10 mins), or empty; running timeliner bootstrap "
            "(same as `python main.py timeliner`)"
        ),
    )
    try:
        from timeliner_sync import sync_timeliner

        sync_timeliner()
    except Exception as exc:
        # Keep flow resilient; build_timeliner_scope still has live-Notion fallback.
        _log_stage(stage, f"TIMELINER bootstrap failed: {exc}")
        return

    if _has_cached_timeliner_scope():
        _log_stage(stage, "TIMELINER bootstrap complete; cache is now ready")
    else:
        _log_stage(stage, "TIMELINER bootstrap completed but cache is still empty")


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

    # Build per-entry matching anchors:
    #   theme_anchor — the project or subproject that should appear in a task's theme field
    #   subtheme_key — the colour_subtheme that should appear in a task's title
    # Both must match for a task to be scoped (preserves the Theme+Title rule).
    ScopeEntry = Dict[str, Any]  # type alias for clarity
    scope_entries: List[ScopeEntry] = []
    seen_subtheme: Set[str] = set()
    ordered_keys: List[str] = []  # ordered list of colour_subtheme keys (for rank)

    for entry in entries:
        if isinstance(entry, dict):
            raw_subtheme = entry.get("colour_subtheme", "")
            raw_subproject = entry.get("subproject", "")
            raw_project = entry.get("project", "")
            raw_priority = entry.get("priority")
            raw_scope_section = entry.get("scope_section", "")
        else:
            raw_subtheme = getattr(entry, "colour_subtheme", "")
            raw_subproject = getattr(entry, "subproject", "")
            raw_project = getattr(entry, "project", "")
            raw_priority = getattr(entry, "priority", None)
            raw_scope_section = getattr(entry, "scope_section", "")

        sub_key = _normalize_scope_text(raw_subtheme)
        if not sub_key:
            continue
        # theme_anchor: prefer subproject, fall back to project
        subproject_txt = str(raw_subproject or "").strip()
        project_txt = str(raw_project or "").strip()
        anchor_raw = subproject_txt or project_txt
        theme_anchor = _normalize_scope_text(anchor_raw)
        scope_entries.append(
            {
                "subtheme_key": sub_key,
                "theme_anchor": theme_anchor,
                "is_subproject": bool(subproject_txt),
                "priority": raw_priority,
                "scope_section": str(raw_scope_section or "").strip().lower(),
            }
        )
        if sub_key not in seen_subtheme:
            seen_subtheme.add(sub_key)
            ordered_keys.append(sub_key)

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
        matched_is_subproject = None
        matched_priority = None
        matched_scope_section = ""
        for rank, se in enumerate(scope_entries):
            sub_key = se["subtheme_key"]
            theme_anchor = se["theme_anchor"]

            # title_ok: colour_subtheme must appear in the task title
            title_ok = bool(sub_key and sub_key in title_text)

            # theme_ok: entry's project/subproject must appear in task's theme field.
            # If no anchor is available, fall back to sub_key (original behaviour).
            if theme_anchor:
                theme_ok = bool(theme_anchor in theme_text)
            else:
                theme_ok = bool(sub_key and sub_key in theme_text)

            if theme_ok and title_ok:
                matched_rank = rank
                matched_key = sub_key
                matched_is_subproject = bool(se.get("is_subproject"))
                matched_priority = se.get("priority")
                matched_scope_section = str(se.get("scope_section", "")).strip().lower()
                break

        if matched_rank is None:
            task["timeliner_key"] = None
            task["timeliner_rank"] = None
            task["timeliner_is_subproject"] = False
            task["timeliner_priority"] = None
            task["timeliner_section"] = ""
            continue

        task["timeliner_key"] = matched_key
        task["timeliner_rank"] = matched_rank
        task["timeliner_is_subproject"] = bool(matched_is_subproject)
        task["timeliner_priority"] = matched_priority
        task["timeliner_section"] = matched_scope_section
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
    
    # 1. 优先使用精确的显示标签 (theme_display_label)，它通常存储了子主题名
    display = str(task.get("theme_display_label", "")).strip()
    if display:
        for main_theme, data in themes.items():
            # 匹配主主题或子主题，以获取正确的颜色配置
            if display == main_theme or display in data.get("sub_themes", []):
                return display, data.get("color", "default")
    
    # 2. 回退：尝试从 Notion 标签中解析
    tags = task.get("tags") or {}
    theme_val = str(tags.get("Task Theme with colour", "")).strip()
    theme_key = str(theme_val).split()[0].strip() if theme_val else ""
    if theme_key in themes:
        return theme_key, themes[theme_key].get("color", "default")

    # 3. 最后回退：如果 display 存在但未匹配到配置，仍返回它（保持名称一致性）
    if display:
        return display, "default"

    return None, "default"



def _register_generated_subtasks(
    state: List[Dict[str, Any]],
    parent_task: Dict[str, Any],
    created_subtasks: List[Dict[str, str]],
) -> None:
    if not created_subtasks:
        return

    parent_id = str(parent_task.get("notion_block_id") or parent_task.get("id") or "")
    if not parent_id:
        return

    existing_ids = {
        str(t.get("notion_block_id") or t.get("id") or "")
        for t in state
    }
    parent_depth = parent_task.get("depth")
    try:
        child_depth = int(parent_depth) + 1 if parent_depth is not None else 0
    except (TypeError, ValueError):
        child_depth = 0

    parent_title = str(parent_task.get("title", "")).strip()
    parent_context = str(parent_task.get("context_heading", "")).strip()

    for created in created_subtasks:
        child_id = str(created.get("id", "")).strip()
        raw_title = str(created.get("title", "")).strip()
        if not child_id or child_id in existing_ids:
            continue

        combined_title = f"{parent_title} {raw_title}".strip() if parent_title else raw_title
        new_task = {
            "id": child_id,
            "notion_block_id": child_id,
            "title": combined_title,
            "original_notion_title": raw_title,
            "context_heading": parent_context,
            "parent_id": parent_id,
            "depth": child_depth,
            "wbs_level": None,
            "type": "todo",
            "notion_type": "to_do",
            "annotations": {},
            "checked": False,
            "has_tag_style": False,
            "created_by_id": "",
            "last_edited_by_id": "",
            "is_generated": True,
            "origin": "generated",
            "timeliner_key": None,
            "timeliner_rank": None,
            "wbs_source": None,
            "split_stage": "none",
            "split_batch_id": None,
            "reviewed_once": False,
            "generated_selection_processed": False,
            "tags": {},
            "status": "todo",
            "metrics": {
                "estimated_time_h": None,
                "actual_time_taken_h": None,
                "interruption_count": 0,
            },
            "synced_tags": False,
        }
        state.append(new_task)
        existing_ids.add(child_id)


def _split_scoped_tasks(
    state: List[Dict[str, Any]],
    structured_cfg: Dict[str, Any],
    scoped_ids: Set[str],
) -> Tuple[int, int]:
    if not scoped_ids:
        return 0, 0

    parent_task_count = 0
    subtask_count = 0
    task_by_id, children_by_parent = build_state_indexes(state)
    for task in list(state):
        task_id = str(task.get("notion_block_id") or task.get("id") or "")
        if task_id not in scoped_ids:
            continue

        split_stage = str(task.get("split_stage", "none")).lower()
        if split_stage in ["suggested", "processed"]:
            continue

        raw_title = task.get("original_notion_title", task.get("title", ""))
        if task.get("checked") or "💯✅" in raw_title:
            continue

        if task.get("is_generated") and not task.get("generated_selection_processed"):
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
        if not any(c.isalnum() for c in clean_title):
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
            _split_dedupe_key(c.get("original_notion_title", c.get("title", "")), structured_cfg)
            for c in existing_children
            if _split_dedupe_key(c.get("original_notion_title", c.get("title", "")), structured_cfg)
        }
        deduped = []
        for s in suggested:
            key = _split_dedupe_key(str(s or ""), structured_cfg)
            if not key or key in existing_titles:
                continue
            existing_titles.add(key)
            deduped.append(str(s).strip())

        if not deduped:
            continue

        parent_theme, parent_theme_color = _resolve_parent_theme_for_split(task, structured_cfg)
        created_subtasks = push_subtasks_to_notion(task_id, deduped, parent_theme, parent_theme_color)
        _register_generated_subtasks(state, task, created_subtasks)
        task["split_stage"] = "suggested"
        task["split_batch_id"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        parent_task_count += 1
        subtask_count += len(deduped)

    return parent_task_count, subtask_count


def run_l1() -> List[Dict[str, Any]]:
    _log_stage("L1", "Starting L1 flow")
    config_dict, _, _, state = _load_merged_state()
    if not state:
        _log_stage("L1", "No tasks found in Notion")
        print("No tasks found in Notion.")
        return []

    _log_stage("L1", f"Loaded {len(state)} merged tasks")
    state = theme_pass(state, config_dict)
    _log_stage("L1", "Theme pass complete")
    state = reparent_theme_containers(state, config_dict)
    _log_stage("L1", "Theme container reparenting complete")
    push_tags_to_notion(state, config_dict)
    _log_stage("L1", "Tag push to Notion complete")

    state = [task for task in state if not task.get("deleted")]
    save_state(state, STATE_FILE)
    _log_stage("L1", f"Saved {len(state)} tasks to state")
    print("L1 flow complete.")
    return state


def run_l2() -> List[Dict[str, Any]]:
    _log_stage("L2", "Starting L2 flow")
    _bootstrap_timeliner_state_if_needed("L2")
    config_dict, structured_cfg, _, state = _load_merged_state()
    if not state:
        _log_stage("L2", "No tasks found in Notion")
        print("No tasks found in Notion.")
        return []

    _log_stage("L2", f"Loaded {len(state)} merged tasks")
    state = theme_pass(state, config_dict)
    _log_stage("L2", "Theme pass complete")
    state = reparent_theme_containers(state, config_dict)
    _log_stage("L2", "Theme container reparenting complete")
    scoped_ids, rank_by_task_id, _ = build_timeliner_scope(state)
    _log_stage("L2", f"Scoped {len(scoped_ids)} tasks from TIMELINER")

    before_wbs = copy.deepcopy(state)
    state = wbs_pass(state, config_dict, scoped_ids=scoped_ids)
    _log_wbs_change_details("L2", before_wbs, state, scoped_ids)

    before_priority = copy.deepcopy(state)
    state = priority_pass(state, config_dict, scoped_ids=scoped_ids, rank_by_task_id=rank_by_task_id)
    _log_priority_change_details("L2", before_priority, state, scoped_ids)

    before_reorder = copy.deepcopy(state)
    state = _reorder_state_by_root_rank(state)
    _log_reorder_details("L2", before_reorder, state)
    state = push_root_order_to_notion(before_reorder, state)

    # Push tag formatting first; split suggestions are generated after this push,
    # so newly created unchecked suggestions are not reviewed in the same run.
    push_tags_to_notion(state, config_dict)
    _log_stage("L2", "Tag push to Notion complete")
    state = [task for task in state if not task.get("deleted")]

    # Re-gather scoped IDs because physical reordering and tag pushing may have cloned
    # blocks in Notion, assigning them new IDs that are no longer in the original `scoped_ids`.
    current_scoped_ids = {
        str(task.get("notion_block_id") or task.get("id") or "")
        for task in state
        if task.get("timeliner_rank") is not None
    }

    split_parent_count, split_subtask_count = _split_scoped_tasks(state, structured_cfg, current_scoped_ids)
    _log_stage(
        "L2",
        f"Split suggestion pass complete: {split_subtask_count} subtasks across {split_parent_count} parent tasks",
    )
    save_state(state, STATE_FILE)
    _log_stage("L2", f"Saved {len(state)} tasks to state")
    print("L2 flow complete.")
    return state


def run_l3() -> List[Dict[str, Any]]:
    _log_stage("L3", "Starting L3 flow")
    config_dict, _, _, state = _load_merged_state()
    if not state:
        _log_stage("L3", "No tasks found in Notion")
        print("No tasks found in Notion.")
        return []

    _log_stage("L3", f"Loaded {len(state)} merged tasks")
    state = theme_pass(state, config_dict)
    _log_stage("L3", "Theme pass complete")
    state = reparent_theme_containers(state, config_dict)
    _log_stage("L3", "Theme container reparenting complete")
    scoped_ids, rank_by_task_id, _ = build_timeliner_scope(state)
    _log_stage("L3", f"Scoped {len(scoped_ids)} tasks from TIMELINER")

    before_wbs = copy.deepcopy(state)
    state = wbs_pass(state, config_dict, scoped_ids=scoped_ids)
    _log_wbs_change_details("L3", before_wbs, state, scoped_ids)

    before_priority = copy.deepcopy(state)
    state = priority_pass(state, config_dict, scoped_ids=scoped_ids, rank_by_task_id=rank_by_task_id)
    _log_priority_change_details("L3", before_priority, state, scoped_ids)

    state = mode_tasktype_pass(state, config_dict, scoped_ids=scoped_ids)
    _log_stage("L3", "Mode/TaskType pass complete")

    before_reorder = copy.deepcopy(state)
    state = _reorder_state_by_root_rank(state)
    _log_reorder_details("L3", before_reorder, state)
    state = push_root_order_to_notion(before_reorder, state)

    push_tags_to_notion(state, config_dict)
    _log_stage("L3", "Tag push to Notion complete")
    state = [task for task in state if not task.get("deleted")]
    save_state(state, STATE_FILE)
    _log_stage("L3", f"Saved {len(state)} tasks to state")
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
    before_reorder = copy.deepcopy(state)
    state = _reorder_state_by_root_rank(state)
    state = push_root_order_to_notion(before_reorder, state)

    push_tags_to_notion(state, config_dict)
    state = [task for task in state if not task.get("deleted")]

    _split_scoped_tasks(state, structured_cfg, scoped_ids)
    save_state(state, STATE_FILE)
    print("Full flow complete.")
    return state
