"""
Live Dashboard 模块。
将任务树按 Modes 和 Task Type 分组，
生成 Notion blocks 写入 live今目 页面。
格式为 LLM 可读 + 全局编号。
"""
from typing import Dict, List, Any, Optional

from notion_client import get_page_blocks, delete_block, append_children


def group_tasks_by_mode(
    flat_state: List[Dict[str, Any]],
    structured_cfg: Dict[str, Any]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    按 Modes 分组任务。
    使用 tags["Modes"] 中的值匹配 config 中的 mode_name。
    没有 mode tag 的任务归入 "Unassigned"。
    """
    # 从 config 获取所有已定义的 mode 名称
    known_modes = [m["mode_name"] for m in structured_cfg.get("modes", [])]
    groups: Dict[str, List[Dict[str, Any]]] = {}

    for task in flat_state:
        tags = task.get("tags") or {}
        mode_val = tags.get("Modes", "")

        matched_mode = None
        if mode_val:
            # 在 mode_val 中查找已知的 mode_name
            for mode_name in known_modes:
                if mode_name in mode_val:
                    matched_mode = mode_name
                    break

        key = matched_mode or "Unassigned"
        if key not in groups:
            groups[key] = []
        groups[key].append(task)

    return groups


def group_tasks_by_task_type(
    flat_state: List[Dict[str, Any]],
    structured_cfg: Dict[str, Any]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    按 Task Type 分组任务。
    使用 tags["Task Type"] 中的值匹配 config 中的 task_types。
    没有 type tag 的任务归入 "Unassigned"。
    """
    known_types = structured_cfg.get("task_types", {})
    groups: Dict[str, List[Dict[str, Any]]] = {}

    for task in flat_state:
        tags = task.get("tags") or {}
        type_val = tags.get("Task Type", "")

        matched_type = None
        if type_val:
            for type_emoji, type_info in known_types.items():
                if type_emoji in type_val:
                    # 用 emoji + 中文名 作为分组键
                    name_cn = type_info.get("name_cn", type_info.get("description", ""))
                    matched_type = f"{type_emoji} {name_cn}".strip()
                    break

        key = matched_type or "Unassigned"
        if key not in groups:
            groups[key] = []
        groups[key].append(task)

    return groups


def get_theme_tag(task: Dict[str, Any]) -> str:
    """
    从任务 tags 中提取主题名，用于子分组显示。
    返回主题名或空字符串。
    """
    tags = task.get("tags") or {}
    theme_val = tags.get("Task Theme with colour", "")
    if theme_val:
        # 取第一个空格前的主题名
        return theme_val.split()[0] if theme_val else ""
    return ""


def _subgroup_by_theme(
    tasks: List[Dict[str, Any]],
    counter: int
) -> tuple[List[Dict[str, Any]], int]:
    """
    将一组任务按主题子分组，生成 Notion blocks。
    counter 是全局任务编号计数器。
    返回 (blocks, 更新后的 counter)。
    """
    # 按主题分组
    theme_groups: Dict[str, List[Dict[str, Any]]] = {}
    for task in tasks:
        theme = get_theme_tag(task) or "Other"
        if theme not in theme_groups:
            theme_groups[theme] = []
        theme_groups[theme].append(task)

    blocks = []
    for theme_name, theme_tasks in theme_groups.items():
        # 主题作为缩进的子标题（斜体 paragraph）
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"  ├─ {theme_name}"},
                    "annotations": {"italic": True, "color": "gray"}
                }]
            }
        })

        # 该主题下的编号任务
        for task in theme_tasks:
            title = task.get("original_notion_title", task.get("title", ""))
            blocks.append({
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": f"[{counter}] {title}"}
                    }]
                }
            })
            counter += 1

    return blocks, counter


def build_dashboard_blocks(
    flat_state: List[Dict[str, Any]],
    structured_cfg: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    生成完整的 Dashboard Notion blocks 列表。
    格式：
      ### By Modes            (heading_2, blue_background)
        💻Focus               (paragraph, bold, blue_background)
          [1] task title       (numbered_list_item)
      ### By Task Type        (heading_2, blue_background)
        🔍 测试               (paragraph, bold, blue_background)
          [N] task title       (numbered_list_item)
    任务全局编号。
    """
    blocks = []
    counter = 1  # 全局任务编号

    # ── Section 1: By Modes ──────────────────────────────
    blocks.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "By Modes"}}],
            "color": "blue_background"
        }
    })

    mode_groups = group_tasks_by_mode(flat_state, structured_cfg)

    # 先按 config 中的 mode 顺序排列，Unassigned 放最后
    mode_order = [m["mode_name"] for m in structured_cfg.get("modes", [])]
    sorted_mode_keys = [k for k in mode_order if k in mode_groups]
    if "Unassigned" in mode_groups:
        sorted_mode_keys.append("Unassigned")
    # 包含 config 中没有但 tag 中出现的 mode
    for k in mode_groups:
        if k not in sorted_mode_keys:
            sorted_mode_keys.append(k)

    for mode_name in sorted_mode_keys:
        tasks = mode_groups[mode_name]
        # Mode 名称子标题
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"{mode_name} ({len(tasks)} tasks)"},
                    "annotations": {"bold": True}
                }],
                "color": "blue_background"
            }
        })
        # 按主题子分组生成任务 blocks
        sub_blocks, counter = _subgroup_by_theme(tasks, counter)
        blocks.extend(sub_blocks)

    # ── Section 2: By Task Type ──────────────────────────
    blocks.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "By Task Type"}}],
            "color": "blue_background"
        }
    })

    type_groups = group_tasks_by_task_type(flat_state, structured_cfg)

    # Unassigned 放最后
    sorted_type_keys = [k for k in type_groups if k != "Unassigned"]
    if "Unassigned" in type_groups:
        sorted_type_keys.append("Unassigned")

    for type_name in sorted_type_keys:
        tasks = type_groups[type_name]
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"{type_name} ({len(tasks)} tasks)"},
                    "annotations": {"bold": True}
                }],
                "color": "blue_background"
            }
        })
        sub_blocks, counter = _subgroup_by_theme(tasks, counter)
        blocks.extend(sub_blocks)

    return blocks


def clear_dashboard_page(page_id: str) -> int:
    """
    清空 live今目 页面上的所有子 blocks，为重写做准备。
    返回删除的 block 数量。
    """
    blocks = get_page_blocks(page_id)
    deleted_count = 0
    for block in blocks:
        try:
            delete_block(block["id"])
            deleted_count += 1
        except Exception as e:
            print(f"删除 block {block.get('id')} 失败: {e}")
    return deleted_count


def write_dashboard(
    page_id: str,
    flat_state: List[Dict[str, Any]],
    structured_cfg: Dict[str, Any]
) -> int:
    """
    向 live今目 页面写入分组 Dashboard。
    1. 清空现有内容
    2. 构建 blocks
    3. 批量追加到页面
    返回写入的 block 数量。

    注意：Notion API 单次 append_children 最多 100 个 blocks，
    超过时需要分批写入。
    """
    # 清空页面
    clear_dashboard_page(page_id)

    # 构建 blocks
    blocks = build_dashboard_blocks(flat_state, structured_cfg)

    if not blocks:
        return 0

    # Notion API 限制：单次最多 100 个 children
    batch_size = 100
    total_written = 0

    for i in range(0, len(blocks), batch_size):
        batch = blocks[i:i + batch_size]
        try:
            append_children(page_id, batch)
            total_written += len(batch)
        except Exception as e:
            print(f"写入 dashboard blocks 失败 (batch {i // batch_size}): {e}")
            break

    return total_written


if __name__ == "__main__":
    import sys
    import json
    sys.stdout.reconfigure(encoding="utf-8")
    from config_reader import load_config, structure_yonctask_config
    from state_manager import load_state, STATE_FILE

    raw_cfg = load_config()
    structured_cfg = structure_yonctask_config(raw_cfg)
    state = load_state(STATE_FILE)

    blocks = build_dashboard_blocks(state, structured_cfg)
    print(f"生成 {len(blocks)} 个 blocks")
    print(json.dumps(blocks[:5], indent=2, ensure_ascii=False))
