"""
焦点追踪器模块。
通过 💪🏿💪🏿💪🏿 emoji 标记当前聚焦任务，
记录时间戳实现工时追踪，支持每日自动重置。

焦点 emoji 显示在 LIVETODAY dashboard 页面上，
通过 task_index_map 映射回 Lines V2 的原始 block_id。
"""
import json
import os
import re
from datetime import datetime, date
from typing import Dict, List, Any, Optional, Tuple

from notion_client import get_page_blocks
from config_reader import parse_rich_text

# 聚焦 emoji 常量
FOCUS_EMOJI = "💪🏿💪🏿💪🏿"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
FOCUS_LOG_FILE = os.path.join(DATA_DIR, "focus_log.json")


def _default_focus_log() -> Dict[str, Any]:
    """返回空的焦点日志默认结构。"""
    return {
        "current_focus": None,
        "history": [],
        "last_reset_date": None
    }


def load_focus_log() -> Dict[str, Any]:
    """读取焦点日志，文件不存在时返回默认结构。"""
    if not os.path.exists(FOCUS_LOG_FILE):
        return _default_focus_log()
    try:
        with open(FOCUS_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return _default_focus_log()


def save_focus_log(log: Dict[str, Any]) -> None:
    """写入焦点日志到 JSON 文件。"""
    with open(FOCUS_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def find_focus_task(task_tree: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    递归扫描任务树，找到 title 末尾包含 FOCUS_EMOJI 的节点。
    返回 {"block_id": str, "title": str, "node": dict} 或 None。
    """
    for node in task_tree:
        title = node.get("title", "")
        if FOCUS_EMOJI in title:
            return {
                "block_id": node.get("id", ""),
                "title": title,
                "node": node
            }
        # 递归搜索子节点
        children = node.get("children", [])
        if children:
            result = find_focus_task(children)
            if result:
                return result
    return None


def list_focusable_tasks(task_tree: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将任务树扁平化为编号列表，仅包含可聚焦的任务节点
    （排除 paragraph / heading 类型的结构性节点）。
    返回: [{"index": 1, "block_id": "...", "title": "...", "has_focus": bool}, ...]
    """
    focusable = []
    # 排除的结构性 block 类型
    skip_types = {"paragraph", "heading_1", "heading_2", "heading_3"}

    def _collect(nodes: List[Dict[str, Any]]) -> None:
        for node in nodes:
            block_type = node.get("type", "")
            title = node.get("title", "").strip()
            if block_type not in skip_types and title:
                has_focus = FOCUS_EMOJI in title
                # 显示时去掉 focus emoji，保持干净
                display_title = title.replace(FOCUS_EMOJI, "").strip()
                focusable.append({
                    "index": len(focusable) + 1,
                    "block_id": node.get("id", ""),
                    "title": display_title,
                    "has_focus": has_focus
                })
            children = node.get("children", [])
            if children:
                _collect(children)

    _collect(task_tree)
    return focusable


def detect_focus_from_livetoday(
    page_id: str,
    task_index_map: Dict[int, str]
) -> Optional[Dict[str, Any]]:
    """
    读取 LIVETODAY 页面 blocks，检测用户放置 💪🏿💪🏿💪🏿 的位置。

    支持两种放置方式:
      Pattern A (inline): emoji 追加在任务标题末尾
        例: "[3] Some Task 💪🏿💪🏿💪🏿"
      Pattern B (child block): emoji 作为独立 block 放在任务下方
        例: "[3] Some Task"
             "💪🏿💪🏿💪🏿"

    返回 {"block_id": str, "title": str, "index": int} 或 None。
    block_id 是通过 task_index_map 映射回的 Lines V2 原始 block_id。
    """
    blocks = get_page_blocks(page_id)
    if not blocks:
        return None

    last_task_index = None  # 最近一个 [N] 任务 block 的索引号
    last_task_title = None  # 最近一个 [N] 任务 block 的标题

    for block in blocks:
        block_type = block.get("type", "")
        type_content = block.get(block_type, {})
        rich_text = type_content.get("rich_text", [])
        text = parse_rich_text(rich_text).strip()

        # 尝试解析 [N] 前缀
        idx_match = re.match(r"^\[(\d+)\]\s*(.*)", text)

        if idx_match:
            task_num = int(idx_match.group(1))
            task_title = idx_match.group(2).strip()

            # Pattern A: emoji 在任务标题末尾（inline）
            if FOCUS_EMOJI in task_title:
                clean_title = task_title.replace(FOCUS_EMOJI, "").strip()
                original_block_id = task_index_map.get(task_num)
                if original_block_id:
                    return {
                        "block_id": original_block_id,
                        "title": clean_title,
                        "index": task_num
                    }

            # 记录当前任务作为 "最近的任务" 供 Pattern B 使用
            last_task_index = task_num
            last_task_title = task_title
        else:
            # Pattern B: 独立 block 仅包含 focus emoji
            stripped = text.replace(" ", "").strip()
            if FOCUS_EMOJI in stripped and last_task_index is not None:
                original_block_id = task_index_map.get(last_task_index)
                if original_block_id:
                    return {
                        "block_id": original_block_id,
                        "title": (last_task_title or "").replace(FOCUS_EMOJI, "").strip(),
                        "index": last_task_index
                    }

    return None


def reset_focus_daily(log: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """
    每日自动重置：检测日期变化后清除当前焦点。
    焦点返回"默认位置"（index 1）由 dashboard 重写时处理。

    返回 (更新后的 log, 是否执行了重置)。
    """
    today_str = date.today().isoformat()

    if log.get("last_reset_date") == today_str:
        return log, False  # 今天已经重置过

    # 如果有正在进行的 focus 记录，结束它
    if log.get("current_focus"):
        log["current_focus"]["ended_at"] = datetime.now().astimezone().isoformat()
        log["history"].append(log["current_focus"])
        log["current_focus"] = None

    log["last_reset_date"] = today_str
    return log, True


def record_focus_event(
    log: Dict[str, Any],
    block_id: str,
    title: str,
    event_type: str
) -> Dict[str, Any]:
    """
    在内存中的 log dict 上记录焦点事件。
    event_type: "start" 或 "end"
    返回修改后的 log。
    """
    now = datetime.now().astimezone().isoformat()

    if event_type == "start":
        log["current_focus"] = {
            "block_id": block_id,
            "title": title,
            "started_at": now
        }
    elif event_type == "end":
        if log.get("current_focus"):
            log["current_focus"]["ended_at"] = now
            log["history"].append(log["current_focus"])
            log["current_focus"] = None

    return log


def track_focus(
    page_id: str,
    task_index_map: Dict[int, str],
    task_titles: Optional[Dict[str, str]] = None
) -> Optional[Dict[str, Any]]:
    """
    主追踪函数：
    1. 加载日志
    2. 检查并执行每日重置
    3. 从 LIVETODAY 检测焦点是否发生变化
    4. 记录时间戳
    5. 保存日志
    返回当前焦点信息。

    task_titles: 可选的 block_id → title 映射，用于 reset 后设置默认焦点显示名。
    """
    log = load_focus_log()

    # 每日自动重置
    log, did_reset = reset_focus_daily(log)
    if did_reset:
        save_focus_log(log)

    # 从 LIVETODAY 检测当前焦点
    focus_info = detect_focus_from_livetoday(page_id, task_index_map)

    if not focus_info:
        # 没有找到 focus emoji
        return log.get("current_focus")

    current_block_id = focus_info["block_id"]
    current_title = focus_info["title"]

    prev_focus = log.get("current_focus")

    if prev_focus is None:
        # 首次追踪或重置后：记录 start
        log = record_focus_event(log, current_block_id, current_title, "start")
    elif prev_focus.get("block_id") != current_block_id:
        # 焦点发生切换：结束旧的，开始新的
        log = record_focus_event(log, prev_focus["block_id"], prev_focus["title"], "end")
        log = record_focus_event(log, current_block_id, current_title, "start")
    # else: 焦点未变化，无需操作

    save_focus_log(log)
    return log.get("current_focus")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    from task_reader import fetch_and_build_task_tree

    tree = fetch_and_build_task_tree()
    focus = find_focus_task(tree)
    if focus:
        print(f"当前焦点: {focus['title']}")
    else:
        print("未找到 💪🏿💪🏿💪🏿 标记")

    tasks = list_focusable_tasks(tree)
    print(f"\n可聚焦任务数: {len(tasks)}")
    for t in tasks[:10]:
        marker = " 💪🏿💪🏿💪🏿" if t["has_focus"] else ""
        print(f"  {t['index']:3d}. {t['title']}{marker}")
