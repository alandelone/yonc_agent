"""
Phase Manager：交互式 CLI 工具，用于为 Depth=1 的大模块任务分配阶段 emoji。

使用方式：
  python main.py phase          # 进入交互模式
  python main.py phase --list   # 仅查看待分配的任务

阶段 emoji 对照表：
  0️⃣ = Phase 0 (前置准备)
  1️⃣ = Phase 1 (第一阶段)
  2️⃣ = Phase 2 (第二阶段)
  ...
  9️⃣ = Phase 9

人类也可以直接在 Notion 任务标题中手动输入 emoji（如 1️⃣）来设定阶段。
"""

import sys
from typing import Any, Dict, List, Optional

from state_evaluator import (
    BlockState,
    PHASE_EMOJIS,
    detect_phase_emoji,
    evaluate_block_state,
)
from block_info_reader import build_state_indexes
from state_manager import STATE_FILE, load_state


def _task_id(task: Dict[str, Any]) -> str:
    return str(task.get("notion_block_id") or task.get("id") or "")


def _task_title(task: Dict[str, Any]) -> str:
    return str(task.get("original_notion_title") or task.get("title") or "").strip()


def _find_phasing_wait_tasks(
    state: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    找到所有处于 PHASING_WAIT 状态的任务，按其所属的根项目 (WBS Lv1) 分组。

    返回: {project_title: [task1, task2, ...]}
    """
    task_by_id, children_by_parent = build_state_indexes(state)

    # 找出所有 PHASING_WAIT 的任务
    waiting_tasks: List[Dict[str, Any]] = []
    for task in state:
        block_state = evaluate_block_state(task, children_by_parent)
        if block_state == BlockState.PHASING_WAIT:
            waiting_tasks.append(task)

    # 按 parent_id（即 WBS Lv1 项目）分组
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for task in waiting_tasks:
        parent_id = str(task.get("parent_id") or "")
        parent = task_by_id.get(parent_id)
        project_title = _task_title(parent) if parent else "(未知项目)"
        project_key = f"{parent_id}|{project_title}"
        grouped.setdefault(project_key, []).append(task)

    return grouped


def list_phasing_tasks() -> None:
    """显示所有等待 Phase 分配的任务列表。"""
    state = load_state(STATE_FILE)
    if not state:
        sys.stdout.buffer.write(b"No task state found. Run 'flow' first.\n")
        return

    grouped = _find_phasing_wait_tasks(state)
    if not grouped:
        sys.stdout.buffer.write(b"\nNo tasks waiting for Phase assignment.\n")
        sys.stdout.buffer.write(
            b"All Depth=1 blocks already have phase emojis or don't need them.\n\n"
        )
        return

    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.write(
        "待分配阶段的任务 (PHASING_WAIT)\n".encode("utf-8")
    )
    sys.stdout.buffer.write(("=" * 60 + "\n").encode("utf-8"))

    project_num = 0
    for project_key, tasks in grouped.items():
        project_num += 1
        _, project_title = project_key.split("|", 1)
        header = f"\n  [{project_num}] {project_title} ({len(tasks)} tasks)\n"
        sys.stdout.buffer.write(header.encode("utf-8"))
        sys.stdout.buffer.write(("  " + "-" * 56 + "\n").encode("utf-8"))

        for i, task in enumerate(tasks, 1):
            title = _task_title(task)[:50]
            line = f"      {i}. {title}\n"
            sys.stdout.buffer.write(line.encode("utf-8"))

    sys.stdout.buffer.write(b"\n")
    # 展示 emoji 对照表
    sys.stdout.buffer.write(
        "Phase emoji 对照: ".encode("utf-8")
    )
    emoji_ref = " ".join(f"{i}={e}" for i, e in enumerate(PHASE_EMOJIS[:7]))
    sys.stdout.buffer.write(f"{emoji_ref}\n\n".encode("utf-8"))


def interactive_phase_assignment() -> None:
    """
    交互式 Phase 分配流程：
    1. 列出所有项目及其待分配的子模块
    2. 用户选择项目编号
    3. 用户输入一串数字为每个子模块分配 Phase（如 "1 1 2 3"）
    4. 将 Phase emoji 写入 Notion 任务标题
    """
    state = load_state(STATE_FILE)
    if not state:
        sys.stdout.buffer.write(b"No task state found. Run 'flow' first.\n")
        return

    grouped = _find_phasing_wait_tasks(state)
    if not grouped:
        sys.stdout.buffer.write(b"\nNo tasks waiting for Phase assignment.\n\n")
        return

    # 建立有序列表
    project_list = list(grouped.items())

    # 展示所有项目
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.write(
        "[Active Projects with unphased tasks]\n".encode("utf-8")
    )
    sys.stdout.buffer.write(("=" * 60 + "\n").encode("utf-8"))

    for idx, (project_key, tasks) in enumerate(project_list, 1):
        _, project_title = project_key.split("|", 1)
        line = f"  [{idx}] {project_title[:50]}  ({len(tasks)} tasks)\n"
        sys.stdout.buffer.write(line.encode("utf-8"))

    sys.stdout.buffer.write(b"\n")

    # 用户选择项目
    try:
        raw_input = input("> Which project? (enter number, or 'q' to quit): ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.stdout.buffer.write(b"\nCancelled.\n")
        return

    if raw_input.lower() in ("q", "quit", "exit"):
        return

    try:
        project_idx = int(raw_input) - 1
        if project_idx < 0 or project_idx >= len(project_list):
            raise ValueError
    except ValueError:
        sys.stdout.buffer.write(
            f"Invalid choice: '{raw_input}'. Must be 1-{len(project_list)}.\n".encode("utf-8")
        )
        return

    project_key, tasks = project_list[project_idx]
    _, project_title = project_key.split("|", 1)

    # 展示任务列表
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.write(
        f"[Tasks in '{project_title[:40]}']\n".encode("utf-8")
    )
    sys.stdout.buffer.write(("-" * 60 + "\n").encode("utf-8"))

    for i, task in enumerate(tasks, 1):
        title = _task_title(task)[:55]
        line = f"  {i}. {title}\n"
        sys.stdout.buffer.write(line.encode("utf-8"))

    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.write(
        f"Assign phases (space-separated digits 0-9, e.g., '1 1 2 3' for {len(tasks)} tasks)\n".encode("utf-8")
    )

    # 用户输入阶段号
    try:
        phase_input = input("> Phases: ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.stdout.buffer.write(b"\nCancelled.\n")
        return

    if not phase_input:
        sys.stdout.buffer.write(b"No input. Cancelled.\n")
        return

    # 解析输入：支持 "1 1 2 3" 或 "1123" 两种格式
    if " " in phase_input:
        parts = phase_input.split()
    else:
        parts = list(phase_input)

    # 验证：必须全是数字，且数量匹配
    if len(parts) != len(tasks):
        sys.stdout.buffer.write(
            f"Error: expected {len(tasks)} numbers but got {len(parts)}.\n".encode("utf-8")
        )
        return

    phase_numbers: List[int] = []
    for p in parts:
        if not p.isdigit() or int(p) > 9:
            sys.stdout.buffer.write(
                f"Error: '{p}' is not a valid phase number (0-9).\n".encode("utf-8")
            )
            return
        phase_numbers.append(int(p))

    # 写入 Notion
    from notion_client import update_block

    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.write(
        "Result:\n".encode("utf-8")
    )

    for task, phase_num in zip(tasks, phase_numbers):
        tid = _task_id(task)
        original_title = _task_title(task)
        emoji = PHASE_EMOJIS[phase_num]

        # 构建新标题：在最前面插入 Phase emoji
        new_title = f"{emoji} {original_title}"

        # 确定 block_type
        block_type = task.get("notion_type") or task.get("type") or ""
        if block_type == "todo":
            block_type = "to_do"
        elif block_type == "bullet":
            block_type = "bulleted_list_item"

        # 构建 Notion 更新 payload
        rich_text = [{"type": "text", "text": {"content": new_title}}]
        content_payload = {block_type: {"rich_text": rich_text}}
        if block_type == "to_do":
            content_payload[block_type]["checked"] = bool(task.get("checked"))

        try:
            update_block(tid, content_payload)
            display = f"  [Phase {phase_num}] {emoji} {original_title[:45]}\n"
            sys.stdout.buffer.write(display.encode("utf-8"))
        except Exception as e:
            err_msg = f"  ❌ Failed to update {tid}: {e}\n"
            sys.stdout.buffer.write(err_msg.encode("utf-8"))

    sys.stdout.buffer.write(b"\nPhase assignment complete!\n")
    sys.stdout.buffer.write(
        b"Run 'python main.py flow' to continue processing.\n\n"
    )
