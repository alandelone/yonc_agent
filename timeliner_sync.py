from typing import List, Dict, Any, Tuple, Optional, Set
from collections import defaultdict
from datetime import datetime, date

from timeliner_reader import fetch_and_parse_timeliner, TimelineEntry, TIMELINER_PAGE_ID
from timeliner_state import (
    load_latest_audit_dates,
    save_timeliner_state,
    record_date_change,
    resolve_status_emoji,
    get_extension_count,
    build_scope_key,
)
from notion_client import update_block
from state_manager import load_state, STATE_FILE
from completion import DONE_PREFIX


def calculate_metrics_by_subtheme(flat_tasks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Returns a dict mapping subtheme -> {'completed': int, 'total': int, 'time': float}."""
    stats = defaultdict(lambda: {"completed": 0, "total": 0, "time": 0.0})

    # Pre-compute children mapping to identify leaf nodes quickly
    children_of = defaultdict(list)
    for task in flat_tasks:
        if task.get("type", "") in ["heading_2", "heading_3"]:
            continue
        pid = task.get("parent_id")
        if pid:
            children_of[pid].append(task.get("id"))

    for task in flat_tasks:
        if task.get("type", "") in ["heading_2", "heading_3"]:
            continue

        tags = task.get("tags", {})
        theme_str = tags.get("Task Theme with colour", "")
        if not theme_str:
            continue

        tid = task.get("id")
        is_leaf = len(children_of[tid]) == 0
        if not is_leaf:
            continue

        is_done = False
        if DONE_PREFIX in task.get("original_notion_title", "") or DONE_PREFIX in task.get("title", ""):
            is_done = True
        elif task.get("checked") is True or task.get("status") in ["done", "completed"]:
            is_done = True

        stats[theme_str]["total"] += 1
        if is_done:
            stats[theme_str]["completed"] += 1

        time_h = 0.0
        metrics = task.get("metrics", {})
        est = metrics.get("estimated_time_h")
        if est is not None:
            time_h = float(est)
        else:
            wbs_level = task.get("wbs_level")
            if wbs_level == 1:
                time_h = 20.0
            elif wbs_level == 2:
                time_h = 10.0
            elif wbs_level == 3:
                time_h = 4.0
            elif wbs_level is not None and wbs_level >= 4:
                time_h = 1.0

        stats[theme_str]["time"] += time_h

    return dict(stats)


def get_theme_metrics(subtheme: str, theme_stats: Dict[str, Dict[str, Any]]) -> Tuple[int, float]:
    """Find matching theme in stats and return (percentage 0-100, total_time)."""
    total_completed = 0
    total_tasks = 0
    total_time = 0.0

    for theme_str, metrics in theme_stats.items():
        if subtheme in theme_str:
            total_completed += metrics["completed"]
            total_tasks += metrics["total"]
            total_time += metrics["time"]

    pct = 0
    if total_tasks > 0:
        pct = int((total_completed / total_tasks) * 100)
    
    return pct, round(total_time, 1)


def _with_strike(is_100: bool, extra: Dict[str, Any] = None) -> Dict[str, Any]:
    ann = {"strikethrough": is_100}
    if extra:
        ann.update(extra)
    return ann


def _with_forced_color(is_100: bool, extra: Dict[str, Any], color: str) -> Dict[str, Any]:
    ann = _with_strike(is_100, extra)
    ann["color"] = color
    return ann


def _norm_annotations(ann: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(ann, dict):
        return {}
    return {
        "bold": bool(ann.get("bold", False)),
        "italic": bool(ann.get("italic", False)),
        "strikethrough": bool(ann.get("strikethrough", False)),
        "underline": bool(ann.get("underline", False)),
        "code": bool(ann.get("code", False)),
        "color": ann.get("color", "default"),
    }


def _pick_theme_label(entry: TimelineEntry) -> str:
    generic = {"main project", "main projects", "project", "projects"}
    for candidate in [entry.subproject, entry.project]:
        c = (candidate or "").strip()
        if c and c.lower() not in generic:
            return c
    return "科研人"


def _build_task_theme_label_index(flat_tasks: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Build a lookup: task title -> preferred theme/subtheme label.
    Priority:
    1) theme_display_label (subtheme)
    2) first token of tags['Task Theme with colour'] (main theme)
    """
    idx: Dict[str, str] = {}
    for task in flat_tasks:
        original_title = str(task.get("original_notion_title", "") or "").strip()
        full_title = str(task.get("title", "") or "").strip()
        if not original_title and not full_title:
            continue

        tags = task.get("tags", {}) if isinstance(task.get("tags"), dict) else {}
        label = str(task.get("theme_display_label", "") or "").strip()
        if not label:
            theme_val = str(tags.get("Task Theme with colour", "") or "").strip()
            if theme_val:
                label = theme_val.split(" ", 1)[0].strip()
        if not label:
            continue

        for key in {original_title, full_title}:
            if key:
                idx.setdefault(key.lower(), label)
    return idx


def _build_theme_original_title_index(flat_tasks: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """
    Build lookup: theme label -> set of original task titles (without theme prefix).
    """
    idx: Dict[str, Set[str]] = defaultdict(set)
    for task in flat_tasks:
        tags = task.get("tags", {}) if isinstance(task.get("tags"), dict) else {}
        label = str(task.get("theme_display_label", "") or "").strip()
        if not label:
            theme_val = str(tags.get("Task Theme with colour", "") or "").strip()
            if theme_val:
                label = theme_val.split(" ", 1)[0].strip()
        if not label:
            continue

        original_title = str(task.get("original_notion_title", "") or "").strip()
        full_title = str(task.get("title", "") or "").strip()
        if original_title:
            idx[label.lower()].add(original_title)
        if full_title:
            if full_title.lower().startswith((label + " ").lower()):
                idx[label.lower()].add(full_title[len(label):].strip())
            else:
                idx[label.lower()].add(full_title)
    return idx


def _resolve_task_label_for_entry(
    entry: TimelineEntry,
    theme_label: str,
    original_title_index: Dict[str, Set[str]],
) -> str:
    task_label = str(entry.colour_subtheme or "").strip()
    if not task_label:
        return task_label

    label = str(theme_label or entry.project or "").strip()
    if not label:
        return task_label

    candidates = list(original_title_index.get(label.lower(), set()))
    if not candidates:
        return task_label

    for c in candidates:
        if c.lower() == task_label.lower():
            return c

    contains = [c for c in candidates if task_label.lower() in c.lower()]
    if len(contains) == 1:
        return contains[0]

    suffix = [c for c in candidates if c.lower().endswith(" " + task_label.lower())]
    if len(suffix) == 1:
        return suffix[0]

    return task_label


def _resolve_theme_label_for_entry(entry: TimelineEntry, idx: Dict[str, str]) -> str:
    key = str(entry.colour_subtheme or "").strip().lower()
    if key and key in idx:
        return idx[key]
    return _pick_theme_label(entry)


def _extract_style_profile(existing_rt: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    profile = {
        "status": {},
        "badge": {"bold": True, "code": True},
        "task": {},
        "takes": {},
        "dates": {"code": True},
        "percent": {},
        "settle": {},
        "mention": {},
        "date_value": {},
        "but": {},
    }
    if not existing_rt:
        return profile

    text_items = [rt for rt in existing_rt if rt.get("type") == "text"]

    if text_items:
        profile["status"] = _norm_annotations(text_items[0].get("annotations", {}))

    for i, rt in enumerate(text_items):
        txt = (rt.get("plain_text", "") or "").strip()
        ann = _norm_annotations(rt.get("annotations", {}))
        if not txt:
            continue
        if "Takes" in txt:
            profile["takes"] = ann
            # Use the immediate previous text segment as task style when available.
            if i > 0 and not profile.get("task"):
                prev_ann = _norm_annotations(text_items[i - 1].get("annotations", {}))
                if prev_ann:
                    profile["task"] = prev_ann
        if "dates" in txt:
            profile["dates"] = ann
        if "||" in txt or "%" in txt:
            profile["percent"] = ann
        if "Settle by" in txt:
            profile["settle"] = ann
        # Old format may store date as plain text (not mention); keep its style for mention fallback.
        if (
            not profile.get("date_value")
            and (
                txt.startswith("@")
                or "-" in txt
                or "," in txt
            )
        ):
            profile["date_value"] = ann
        if "but" in txt or "🔜" in txt:
            profile["but"] = ann
        if ann.get("code") and ann.get("bold"):
            profile["badge"] = ann

    for rt in existing_rt:
        if rt.get("type") == "mention" and rt.get("mention", {}).get("type") == "date":
            profile["mention"] = _norm_annotations(rt.get("annotations", {}))
            break

    if not profile.get("mention"):
        profile["mention"] = profile.get("date_value") or profile.get("settle") or {}

    return profile


def _compute_remaining_work_days(settle_date: str) -> Optional[int]:
    """
    Calculate remaining days from today to settle date.
    Positive: days left, zero: due today, negative: overdue.
    """
    s = str(settle_date or "").strip()
    if not s:
        return None
    try:
        target = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (target - date.today()).days


def build_timeliner_rich_text(
    entry: TimelineEntry,
    new_percent: int,
    new_status_emoji: str,
    existing_rt: List[Dict[str, Any]],
    theme_label: str,
    resolved_task_label: str = "",
) -> List[Dict[str, Any]]:
    """
    Format:
    🟢**`theme/subtheme`** task Takes `🏁dates {time}h`  || {percent}%
    **Settle by** @mention_date, but 🔜 {remaining} day
    """
    is_100 = new_percent == 100
    badge_label = (theme_label or "").strip()
    if not badge_label:
        badge_label = (entry.project or "").strip() or _pick_theme_label(entry)
    sub_project = (entry.subproject or "").strip()
    has_distinct_sub_project = bool(sub_project and sub_project.lower() != badge_label.lower())
    task_label = str(resolved_task_label or entry.colour_subtheme or "").strip()

    style = _extract_style_profile(existing_rt)

    rt: List[Dict[str, Any]] = []

    rt.append({
        "type": "text",
        "text": {"content": f"{new_status_emoji}"},
        "annotations": _with_strike(is_100, style.get("status")),
    })

    rt.append({
        "type": "text",
        "text": {"content": badge_label},
        "annotations": _with_strike(is_100, style.get("badge")),
    })

    if has_distinct_sub_project:
        rt.append({
            "type": "text",
            "text": {"content": " / "},
            "annotations": _with_strike(is_100, style.get("task")),
        })
        rt.append({
            "type": "text",
            "text": {"content": sub_project},
            "annotations": _with_strike(
                is_100,
                {"italic": True, **(style.get("task") or {})},
            ),
        })

    rt.append({
        "type": "text",
        "text": {"content": f" {task_label} "},
        "annotations": _with_strike(is_100, style.get("task")),
    })

    rt.append({
        "type": "text",
        "text": {"content": "Takes"},
        "annotations": _with_strike(is_100, style.get("takes")),
    })

    rt.append({
        "type": "text",
        "text": {"content": " "},
        "annotations": _with_strike(is_100, style.get("task")),
    })

    time_suffix = "h"
    if entry.time_expected_h is not None:
        val = entry.time_expected_h
        time_str = f"{int(val)}" if val == int(val) else f"{val:.1f}"
        time_suffix = f"{time_str}h"

    rt.append({
        "type": "text",
        "text": {"content": f"🏁dates {time_suffix}"},
        "annotations": _with_forced_color(
            is_100,
            {"code": True, **(style.get("dates") or {})},
            "red",
        ),
    })

    rt.append({
        "type": "text",
        "text": {"content": f"  || {new_percent}%\n"},
        "annotations": _with_strike(is_100, style.get("percent")),
    })

    rt.append({
        "type": "text",
        "text": {"content": "Settle by"},
        "annotations": _with_strike(is_100, style.get("settle")),
    })

    rt.append({
        "type": "text",
        "text": {"content": " "},
        "annotations": _with_strike(is_100, style.get("settle")),
    })

    rt.append({
        "type": "mention",
        "mention": {
            "type": "date",
            "date": {
                "start": entry.settle_date,
                "end": None,
            },
        },
        "annotations": _with_forced_color(
            is_100,
            style.get("mention") or style.get("settle"),
            "gray",
        ),
    })

    if is_100:
        remaining_days = 0
    else:
        remaining_days = _compute_remaining_work_days(entry.settle_date)
        if remaining_days is None:
            remaining_days = entry.remaining_work_days
    remaining_txt = f", but 🔜 {remaining_days} day" if remaining_days is not None else ", but 🔜 day"
    rt.append({
        "type": "text",
        "text": {"content": remaining_txt},
        "annotations": _with_strike(is_100, style.get("but") or style.get("settle")),
    })

    return rt


def sync_timeliner() -> None:
    print(f"Fetching timeline entries from Notion page {TIMELINER_PAGE_ID}...")
    entries = fetch_and_parse_timeliner(force_live=True)
    if not entries:
        print("No timeline entries found.")
        return

    print("Loading task tree state for progress and expected time calculation...")
    flat_tasks = load_state(STATE_FILE)
    theme_stats = calculate_metrics_by_subtheme(flat_tasks)
    theme_label_index = _build_task_theme_label_index(flat_tasks)
    original_title_index = _build_theme_original_title_index(flat_tasks)

    print("Loading timeliner date audit baselines...")
    audit_scope_dates, audit_subtheme_dates = load_latest_audit_dates()

    updated_state = {}
    enforce_format = True
    date_changed_by_block: Dict[str, bool] = {}

    # Phase 1: detect date changes from audit history only.
    for entry in entries:
        st = str(entry.colour_subtheme or "").strip()
        if not st:
            continue

        project = str(entry.project or "").strip()
        subproject = str(entry.subproject or "").strip()
        scope_key = build_scope_key(st, project=project, subproject=subproject)
        scope_label = " / ".join([x for x in [project, subproject, st] if x]) or st
        new_date = str(entry.settle_date or "").strip()

        if entry.in_heading_scope:
            old_date = str(audit_scope_dates.get(scope_key, "") or "").strip()
        else:
            old_date = str(audit_subtheme_dates.get(st, "") or "").strip()

        if old_date and new_date and old_date != new_date:
            print(f"Date changed for {scope_label}: {old_date} -> {new_date}")
            record_date_change(
                entry.block_id,
                st,
                old_date,
                new_date,
                project=project,
                subproject=subproject,
            )
            date_changed_by_block[entry.block_id] = True

        # First observation does not create audit records, but should be used as
        # in-memory baseline for later entries in the same run.
        if new_date:
            if entry.in_heading_scope:
                audit_scope_dates[scope_key] = new_date
            else:
                audit_subtheme_dates[st] = new_date

    # Phase 2: always process all entries for formatting/status/percent updates.
    for entry in entries:
        changed = bool(date_changed_by_block.get(entry.block_id, False))
        st = str(entry.colour_subtheme or "").strip()
        project = str(entry.project or "").strip()
        subproject = str(entry.subproject or "").strip()
        scope_key = build_scope_key(st, project=project, subproject=subproject)
        scope_label = " / ".join([x for x in [project, subproject, st] if x]) or st

        if entry.in_heading_scope:
            updated_state[scope_key] = entry.settle_date

        ext_project = project if entry.in_heading_scope else ""
        ext_subproject = subproject if entry.in_heading_scope else ""
        ext_count = get_extension_count(st, project=ext_project, subproject=ext_subproject)
        new_status_emoji = resolve_status_emoji(ext_count)
        if new_status_emoji != entry.status_emoji:
            changed = True

        theme_label = _resolve_theme_label_for_entry(entry, theme_label_index)
        new_percent, new_time = get_theme_metrics(theme_label, theme_stats)
        if new_percent != entry.percent:
            changed = True
            
        if new_time != entry.time_expected_h:
            entry.time_expected_h = new_time
            changed = True

        if changed or enforce_format:
            print(
                f"Pushing updates for {scope_label} (Percent: {new_percent}%, Status: {new_status_emoji}) "
                f"to block {entry.block_id} on page {TIMELINER_PAGE_ID}..."
            )
            try:
                from notion_client import BASE_URL, NOTION_HEADERS
                import requests

                resp = requests.get(f"{BASE_URL}/blocks/{entry.block_id}", headers=NOTION_HEADERS)
                resp.raise_for_status()
                block_json = resp.json()
                b_type = block_json.get("type")
                existing_rt = block_json.get(b_type, {}).get("rich_text", [])
                resolved_task_label = _resolve_task_label_for_entry(entry, theme_label, original_title_index)

                rt = build_timeliner_rich_text(
                    entry=entry,
                    new_percent=new_percent,
                    new_status_emoji=new_status_emoji,
                    existing_rt=existing_rt,
                    theme_label=theme_label,
                    resolved_task_label=resolved_task_label,
                )
                payload = {b_type: {"rich_text": rt}}
                update_block(entry.block_id, payload)
            except Exception as e:
                print(f"Failed to update block {entry.block_id}: {e}")

    save_timeliner_state(updated_state, priority_scope_order=list(updated_state.keys()))
    print("TIMELINER sync complete.")
