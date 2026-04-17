"""
焦点时间同步模块。
将 focus_log.json 中的焦点历史记录同步到
tasklist_state.json 的 metrics.timetaken[] 字段。
"""
import json
import os
from typing import Dict, List, Any, Tuple

from focus_tracker import load_focus_log
from state_manager import STATE_FILE, load_state, save_state


def sync_focus_time_to_state() -> Tuple[int, int]:
    """
    读取 focus_log.json 中已完成的焦点 session，
    写入匹配任务的 metrics.timetaken[] 中。

    去重：按 start 时间戳判断，已存在的 period 不会重复写入。

    返回 (同步的 period 数, 涉及的任务数)。
    """
    log = load_focus_log()
    history = log.get("history", [])

    if not history:
        print("No focus history to sync.")
        return 0, 0

    state = load_state(STATE_FILE)
    if not state:
        print("No tasks in state file.")
        return 0, 0

    # 按 block_id 建立索引
    task_by_id: Dict[str, Dict[str, Any]] = {}
    for task in state:
        bid = task.get("notion_block_id") or task.get("id", "")
        if bid:
            task_by_id[bid] = task

    synced_periods = 0
    synced_tasks = set()

    for entry in history:
        block_id = entry.get("block_id", "")
        started_at = entry.get("started_at")
        ended_at = entry.get("ended_at")

        if not block_id or not started_at or not ended_at:
            continue

        task = task_by_id.get(block_id)
        if not task:
            continue

        # 确保 metrics.timetaken 存在
        metrics = task.setdefault("metrics", {})
        timetaken = metrics.setdefault("timetaken", [])

        # 去重：检查 start 时间戳是否已存在
        existing_starts = set()
        for period in timetaken:
            if isinstance(period, dict):
                existing_starts.add(period.get("start", ""))
            elif isinstance(period, (list, tuple)) and len(period) >= 1:
                existing_starts.add(str(period[0]))

        if started_at in existing_starts:
            continue

        # 追加新的 period
        timetaken.append({
            "start": started_at,
            "end": ended_at
        })
        synced_periods += 1
        synced_tasks.add(block_id)

    if synced_periods > 0:
        save_state(state, STATE_FILE)

    return synced_periods, len(synced_tasks)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    periods, tasks = sync_focus_time_to_state()
    print(f"Synced {periods} focus period(s) across {tasks} task(s).")
