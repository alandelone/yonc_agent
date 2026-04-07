"""
焦点追踪器模块。
通过 💪🏿💪🏿💪🏿 emoji 标记当前聚焦任务，
记录时间戳实现工时追踪，支持每日自动重置。
"""
import json
import os
from datetime import datetime, date
from typing import Dict, List, Any, Optional

from notion_client import get_block, update_block, get_page_blocks
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


def move_focus_emoji(from_block_id: str, to_block_id: str) -> None:
    """
    通过 Notion API 将 💪🏿💪🏿💪🏿 从一个 block 移动到另一个 block。
    1. 读取源 block 的 rich_text，移除末尾的 focus emoji
    2. 读取目标 block 的 rich_text，在末尾追加 focus emoji
    """
    # 处理源 block：移除 emoji
    _remove_focus_from_block(from_block_id)
    # 处理目标 block：追加 emoji
    _append_focus_to_block(to_block_id)


def _remove_focus_from_block(block_id: str) -> None:
    """从指定 block 的文本末尾移除 FOCUS_EMOJI。"""
    block = get_block(block_id)
    block_type = block.get("type", "")
    type_content = block.get(block_type, {})
    rich_text = type_content.get("rich_text", [])

    if not rich_text:
        return

    # 在最后一个 rich_text 片段中移除 emoji
    last_segment = rich_text[-1].copy()
    text_content = last_segment.get("text", {}).get("content", "")
    cleaned = text_content.replace(FOCUS_EMOJI, "").rstrip()
    last_segment["text"] = {**last_segment.get("text", {}), "content": cleaned}

    # 如果清理后为空，移除该片段
    new_rich_text = rich_text[:-1]
    if cleaned:
        new_rich_text.append(last_segment)

    payload = {
        block_type: {
            "rich_text": new_rich_text
        }
    }
    update_block(block_id, payload)


def _append_focus_to_block(block_id: str) -> None:
    """在指定 block 的文本末尾追加 FOCUS_EMOJI。"""
    block = get_block(block_id)
    block_type = block.get("type", "")
    type_content = block.get(block_type, {})
    rich_text = type_content.get("rich_text", [])

    # 追加一个新的 text 片段
    rich_text.append({
        "type": "text",
        "text": {"content": f" {FOCUS_EMOJI}"},
        "annotations": {
            "bold": False, "italic": False, "strikethrough": False,
            "underline": False, "code": False, "color": "default"
        }
    })

    payload = {
        block_type: {
            "rich_text": rich_text
        }
    }
    update_block(block_id, payload)


def reset_focus_daily(task_tree: List[Dict[str, Any]], page_id: str) -> bool:
    """
    每日自动重置：检测日期变化后将 💪🏿💪🏿💪🏿 移回页面底部空白 paragraph。
    返回 True 如果执行了重置，False 如果未触发。
    """
    log = load_focus_log()
    today_str = date.today().isoformat()

    if log.get("last_reset_date") == today_str:
        return False  # 今天已经重置过

    # 找到当前 focus 位置
    focus_info = find_focus_task(task_tree)
    if focus_info:
        # 移除当前位置的 emoji
        _remove_focus_from_block(focus_info["block_id"])

        # 如果有正在进行的 focus 记录，结束它
        if log.get("current_focus"):
            log["current_focus"]["ended_at"] = datetime.now().astimezone().isoformat()
            log["history"].append(log["current_focus"])
            log["current_focus"] = None

    # 找到页面底部最后一个空白 paragraph block
    blocks = get_page_blocks(page_id)
    last_empty_paragraph_id = _find_last_empty_paragraph(blocks)

    if last_empty_paragraph_id:
        _append_focus_to_block(last_empty_paragraph_id)

    log["last_reset_date"] = today_str
    save_focus_log(log)
    return True


def _find_last_empty_paragraph(blocks: List[Dict[str, Any]]) -> Optional[str]:
    """从 blocks 列表中找到最后一个空白 paragraph block 的 ID。"""
    last_empty_id = None
    for block in blocks:
        block_type = block.get("type", "")
        if block_type == "paragraph":
            type_content = block.get("paragraph", {})
            rich_text = type_content.get("rich_text", [])
            text = parse_rich_text(rich_text).strip()
            if not text:
                last_empty_id = block.get("id")
    return last_empty_id


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


def track_focus(task_tree: List[Dict[str, Any]], page_id: str) -> Optional[Dict[str, Any]]:
    """
    主追踪函数：
    1. 加载日志
    2. 检查并执行每日重置
    3. 检测焦点是否发生变化
    4. 记录时间戳
    5. 保存日志
    返回当前焦点信息。
    """
    log = load_focus_log()
    today_str = date.today().isoformat()

    # 每日自动重置
    if log.get("last_reset_date") != today_str:
        reset_focus_daily(task_tree, page_id)
        # 重置后重新加载日志和任务树（树可能已经变化）
        log = load_focus_log()

    # 在当前树中查找 focus
    focus_info = find_focus_task(task_tree)

    if not focus_info:
        # 没有找到 focus emoji，可能被重置到了空行
        return log.get("current_focus")

    current_block_id = focus_info["block_id"]
    current_title = focus_info["title"].replace(FOCUS_EMOJI, "").strip()

    prev_focus = log.get("current_focus")

    if prev_focus is None:
        # 首次追踪：记录 start
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
    from config import DFORGE_LINESV2_PAGE_ID

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
