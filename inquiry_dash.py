"""
STATE 1 - Agentic Inquiry & Task Matrix unified panel.

Combines cron-dash and energy-aware task suggestions into one command:
  python main.py inquiry --level 3.3
  python main.py inquiry --tired
"""

import json
import sys
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config_reader import load_config, structure_yonctask_config
from cron_manager import (
    get_cron_options_desc,
    get_upcoming_crons,
    load_skip_list,
)
from state_manager import STATE_FILE, load_state


PROJECT_ROOT = Path(__file__).resolve().parent
INQUIRY_EXPORT_FILE = PROJECT_ROOT.parent / "yonc_inquiry_codes.json"


def _status_label(item: dict[str, Any]) -> str:
    if item.get("skipped"):
        return "skip"
    if item.get("done"):
        return "done"
    return "pending"


def _with_codes(items: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    coded: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        entry = dict(item)
        entry["code"] = f"{prefix}{index}"
        entry["arrangement_index"] = index
        coded.append(entry)
    return coded


def _compact_cron_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": item["code"],
        "arrangement_index": item.get("arrangement_index"),
        "description": item.get("description", ""),
        "name_in_db": item.get("name_in_db", ""),
        "cron_type": item.get("cron_type", ""),
        "status": _status_label(item),
        "options_desc": item.get("options_desc", ""),
        "start_hour": item.get("start_hour"),
        "end_hour": item.get("end_hour"),
        "section": item.get("section"),
        "raw": item.get("raw", ""),
    }


def _compact_task_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": item["code"],
        "arrangement_index": item.get("arrangement_index"),
        "description": item.get("title", ""),
        "title": item.get("title", ""),
        "mode_name": item.get("mode_name", ""),
        "mode_level": item.get("mode_level", ""),
        "source": item.get("source", "suggest"),
    }


def _write_inquiry_export(
    *,
    today_label: str,
    now_label: str,
    energy_label: str,
    level: float | None,
    tired: bool,
    cron_items: list[dict[str, Any]],
    task_items: list[dict[str, Any]],
) -> Path:
    export = {
        "cron_section": {
            item["code"]: _compact_cron_item(item)
            for item in cron_items
        },
        "tasklist_section": {
            item["code"]: _compact_task_item(item)
            for item in task_items
        },
        "_meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "date": today_label,
            "time": now_label,
            "energy": {
                "label": energy_label,
                "level": level,
                "tired": tired,
            },
            "code_rules": {
                "cron_section": "Cron tasks are addressed as C1, C2, C3 in display order.",
                "tasklist_section": "Tasklist/suggest tasks are addressed as T1, T2, T3 in display order.",
            },
        },
    }
    INQUIRY_EXPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with INQUIRY_EXPORT_FILE.open("w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return INQUIRY_EXPORT_FILE


def _build_cron_items(time_str: str | None = None) -> list[dict[str, Any]]:
    crons = get_upcoming_crons(time_str=time_str)
    skipped_set = load_skip_list()

    items: list[dict[str, Any]] = []
    for c in crons:
        entry = dict(c)
        entry["skipped"] = c["name_in_db"] in skipped_set
        entry["options_desc"] = get_cron_options_desc(c["name_in_db"])
        items.append(entry)

    return items


def _build_suggest_items(max_level: float) -> list[dict[str, Any]]:
    raw_cfg = load_config()
    structured_cfg = structure_yonctask_config(raw_cfg)
    state = load_state(STATE_FILE)

    if not state:
        return []

    all_modes = structured_cfg.get("modes", [])
    matched_mode_names: set[str] = set()
    for mode in all_modes:
        mode_level = mode.get("level", 0)
        if mode_level <= max_level:
            matched_mode_names.add(mode["mode_name"])

    if not matched_mode_names:
        return []

    l4_tasks = [
        task for task in state
        if task.get("wbs_level") == 4
        and (task.get("tags") or {}).get("Modes")
        and task.get("generated_selection_processed", False)
        and not task.get("checked")
        and str(task.get("status", "")).lower() not in ["done", "completed"]
    ]

    known_modes = [mode["mode_name"] for mode in all_modes]
    items: list[dict[str, Any]] = []
    for task in l4_tasks:
        mode_val = (task.get("tags") or {}).get("Modes", "")
        for mode_name in known_modes:
            if mode_name in mode_val and mode_name in matched_mode_names:
                mode_level = next(
                    (mode["level"] for mode in all_modes if mode["mode_name"] == mode_name),
                    "?",
                )
                title = task.get("original_notion_title", task.get("title", ""))
                items.append({
                    "title": title,
                    "mode_name": mode_name,
                    "mode_level": mode_level,
                    "source": "suggest",
                })
                break

    return items


def cmd_inquiry(
    level: float | None = None,
    tired: bool = False,
    time_str: str | None = None,
) -> None:
    """STATE 1 unified panel: cron-dash plus energy-aware task suggestions."""
    now_label = time_str or datetime.now().strftime("%H:%M")
    today_label = date.today().isoformat()

    if tired:
        energy_label = "Tired"
    elif level is not None:
        energy_label = f"Normal (Lv{level})"
    else:
        energy_label = "Normal"

    cron_items = _with_codes(_build_cron_items(time_str=time_str), "C")
    pending_crons = [
        cron for cron in cron_items
        if not cron["done"] and not cron["skipped"]
    ]
    total_crons = len(cron_items)

    suggest_items: list[dict[str, Any]] = []
    if not tired and level is not None:
        suggest_items = _with_codes(_build_suggest_items(max_level=level), "T")

    export_path = _write_inquiry_export(
        today_label=today_label,
        now_label=now_label,
        energy_label=energy_label,
        level=level,
        tired=tired,
        cron_items=cron_items,
        task_items=suggest_items,
    )

    lines: list[str] = [
        f"INQUIRY | {today_label} {now_label} | Energy: {energy_label}",
        "=" * 60,
    ]

    if cron_items:
        lines.append(f"\nCron section ({len(pending_crons)} pending / {total_crons} total)")
        lines.append("-" * 55)
        for cron in cron_items:
            if cron["skipped"]:
                status = "SKIP "
            elif cron["done"]:
                status = "DONE "
            else:
                status = "     "

            desc = cron.get("description", "")
            desc_part = desc[:40] if desc else ""
            opts = cron.get("options_desc", "")
            opts_part = f"  {opts}" if opts else ""
            type_label = f"({cron.get('cron_type', 'unknown')}) "
            line = f"  {cron['code']:>3}. {status}{cron['name_in_db']} {type_label}- {desc_part}{opts_part}"
            lines.append(line)
    else:
        lines.append("\nCron section: no cron tasks in the current time window.")

    if suggest_items:
        lines.append(f"\nTasklist section (<= Lv{level}, {len(suggest_items)} tasks)")
        lines.append("-" * 55)

        by_mode: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        for item in suggest_items:
            by_mode.setdefault(item["mode_name"], []).append(item)

        for mode_name, tasks in by_mode.items():
            mode_level = tasks[0]["mode_level"]
            lines.append(f"\n  -- {mode_name} (Lv{mode_level}, {len(tasks)} tasks) --")
            for task in tasks:
                lines.append(f"  {task['code']:>3}. {task['title']}")
    elif not tired and level is not None:
        lines.append(f"\nTasklist section: no available suggested tasks (<= Lv{level}).")

    if tired:
        lines.append("\nLow energy: finish required cron tasks first, then rest.")

    pending_types = set(cron.get("cron_type", "") for cron in pending_crons)
    if pending_types:
        if len(pending_types) == 1:
            cron_type = list(pending_types)[0]
            if cron_type == "alert":
                lines.append("\n[AGENT GUIDELINE]: Just alert the user. If user acknowledges, run `daily cron-post`.")
            elif cron_type == "trace":
                lines.append("\n[AGENT GUIDELINE]: Ask the user (Q>A). If user confirms, run `daily cron-post`.")
            elif cron_type == "traceXlt":
                lines.append("\n[AGENT GUIDELINE]: This is a recurring check. Ask the user's status. Record their answer via `daily cron-post`.")
            else:
                lines.append(f"\n[AGENT GUIDELINE]: Handle the pending {cron_type} task and run `daily cron-post`.")
        else:
            lines.append("\n[AGENT GUIDELINE]: You have multiple types. Alert the user for `alert`, ask for `trace`/`traceXlt` status, then use `daily cron-post` when they reply.")

    lines.append(
        f"\n[AGENT GUIDELINE]: Read `{export_path}` once after this command. "
        "Use C# for cron_section items and T# for tasklist_section items when discussing or acting on tasks."
    )
    lines.append(f"[JSON EXPORT]: {export_path}")
    lines.append("")

    output = "\n".join(lines)
    sys.stdout.buffer.write(output.encode("utf-8"))
