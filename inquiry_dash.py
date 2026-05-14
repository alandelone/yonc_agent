"""
STATE 1 — Agentic Inquiry & Task Matrix 统一面板。

将 cron-dash 和 suggest 合并为单一命令输出，
根据 energy level 决定是否包含 suggest 任务。

用法:
  python main.py inquiry --level 3.3     # Normal+ energy, cron + suggest
  python main.py inquiry --tired         # Tired mode, cron only
"""

import sys
from datetime import date, datetime
from typing import Any

from config_reader import load_config, structure_yonctask_config
from cron_manager import (
    get_cron_options_desc,
    get_upcoming_crons,
    is_cron_skipped,
    load_skip_list,
)
from state_manager import STATE_FILE, load_state


def _build_cron_items(
    time_str: str | None = None,
) -> list[dict[str, Any]]:
    """获取当前时间窗口内的 cron 列表，标注 skip 状态和选项描述。

    返回每项包含:
      - name_in_db, description, done, skipped, options_desc, prop_type, ...
    """
    crons = get_upcoming_crons(time_str=time_str)
    skipped_set = load_skip_list()

    items: list[dict[str, Any]] = []
    for c in crons:
        entry = dict(c)
        entry["skipped"] = c["name_in_db"] in skipped_set
        entry["options_desc"] = get_cron_options_desc(c["name_in_db"])
        items.append(entry)

    return items


def _build_suggest_items(
    max_level: float,
) -> list[dict[str, Any]]:
    """获取 suggest 任务列表（复用 cmd_suggest 的核心过滤逻辑）。

    返回每项包含:
      - title, mode_name, mode_level
    """
    raw_cfg = load_config()
    structured_cfg = structure_yonctask_config(raw_cfg)
    state = load_state(STATE_FILE)

    if not state:
        return []

    all_modes = structured_cfg.get("modes", [])

    # 根据 max_level 收集匹配的 mode 名称
    matched_mode_names: set[str] = set()
    for m in all_modes:
        m_level = m.get("level", 0)
        if m_level <= max_level:
            matched_mode_names.add(m["mode_name"])

    if not matched_mode_names:
        return []

    # 过滤 L4 已分配且 processed 的任务
    l4_tasks = [
        t for t in state
        if t.get("wbs_level") == 4
        and (t.get("tags") or {}).get("Modes")
        and t.get("generated_selection_processed", False)
        and not t.get("checked")
        and str(t.get("status", "")).lower() not in ["done", "completed"]
    ]

    # 匹配 mode_name
    known_modes = [m_obj["mode_name"] for m_obj in all_modes]
    items: list[dict[str, Any]] = []
    for t in l4_tasks:
        mode_val = (t.get("tags") or {}).get("Modes", "")
        for mode_name in known_modes:
            if mode_name in mode_val and mode_name in matched_mode_names:
                mode_level = next(
                    (m["level"] for m in all_modes if m["mode_name"] == mode_name),
                    "?",
                )
                title = t.get("original_notion_title", t.get("title", ""))
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
    """STATE 1 统一面板: 合并 cron-dash + suggest 输出。

    Args:
        level: 能量等级数字 (e.g. 3.3)，用于过滤 suggest 任务
        tired: True 时仅输出 cron（不拉 suggest）
        time_str: 覆盖当前时间 (HH:MM)，用于调试
    """
    now_label = time_str or datetime.now().strftime("%H:%M")
    today_label = date.today().isoformat()

    # 确定 energy 标签
    if tired:
        energy_label = "Tired"
    elif level is not None:
        energy_label = f"Normal (Lv{level})"
    else:
        energy_label = "Normal"

    # ── 获取 cron 列表 ──
    cron_items = _build_cron_items(time_str=time_str)

    # 统计: 排除 done 和 skipped 的 pending 数
    pending_crons = [
        c for c in cron_items
        if not c["done"] and not c["skipped"]
    ]
    total_crons = len(cron_items)

    # ── 获取 suggest 列表（仅非 tired 模式）──
    suggest_items: list[dict[str, Any]] = []
    if not tired and level is not None:
        suggest_items = _build_suggest_items(max_level=level)

    # ── 格式化输出 ──
    lines: list[str] = [
        f"INQUIRY | {today_label} {now_label} | Energy: {energy_label}",
        "═" * 60,
    ]

    # Cron 区块
    if cron_items:
        lines.append(
            f"\n⏰ 定时任务 ({len(pending_crons)} pending / {total_crons} total)"
        )
        lines.append("─" * 55)

        counter = 1
        for c in cron_items:
            # 状态标记
            if c["skipped"]:
                status = "❌ SKIP "
            elif c["done"]:
                status = "✅ DONE "
            else:
                status = "        "

            # 描述（截取前 40 字符）
            desc = c.get("description", "")
            desc_part = desc[:40] if desc else ""

            # 选项描述（非 checkbox/text 类型追加选项）
            opts = c.get("options_desc", "")
            opts_part = f"  {opts}" if opts else ""

            type_label = f"({c.get('cron_type', 'unknown')}) "
            line = f"  {counter:3d}. {status}{c['name_in_db']} {type_label}— {desc_part}{opts_part}"
            lines.append(line)
            counter += 1
    else:
        lines.append("\n⏰ 当前时间窗口内无定时任务。")
        counter = 1

    # Suggest 区块
    if suggest_items:
        lines.append(f"\n💻 建议任务 (≤Lv{level}, {len(suggest_items)} tasks)")
        lines.append("─" * 55)

        # 按 mode 分组
        from collections import OrderedDict
        by_mode: OrderedDict[str, list] = OrderedDict()
        for item in suggest_items:
            by_mode.setdefault(item["mode_name"], []).append(item)

        for mode_name, tasks in by_mode.items():
            mode_lv = tasks[0]["mode_level"]
            lines.append(f"\n  ── {mode_name} (Lv{mode_lv}, {len(tasks)} tasks) ──")
            for t in tasks:
                # 编号延续 cron 区块的 counter
                line = f"  {counter:3d}. {t['title']}"
                lines.append(line)
                counter += 1
    elif not tired and level is not None:
        lines.append(f"\n💻 无可用建议任务 (≤Lv{level})")

    # Tired 模式底部提示
    if tired:
        lines.append("\n🛌 能量较低，建议完成定时任务后休息。")

    # ── 添加 Agent 执行指南 (Guidelines) ──
    pending_types = set(c.get("cron_type", "") for c in pending_crons)
    if pending_types:
        if len(pending_types) == 1:
            ctype = list(pending_types)[0]
            if ctype == "alert":
                lines.append("\n💡 [AGENT GUIDELINE]: Just alert the user. If user acknowledges, run `daily cron-post`.")
            elif ctype == "trace":
                lines.append("\n💡 [AGENT GUIDELINE]: Ask the user (Q>A). If user confirms, run `daily cron-post`.")
            elif ctype == "traceXlt":
                lines.append("\n💡 [AGENT GUIDELINE]: This is a recurring check. Ask the user's status. Record their answer via `daily cron-post`.")
            else:
                lines.append(f"\n💡 [AGENT GUIDELINE]: Handle the pending {ctype} task and run `daily cron-post`.")
        else:
            lines.append("\n💡 [AGENT GUIDELINE]: You have multiple types. Alert the user for `alert`, ask for `trace`/`traceXlt` status, then use `daily cron-post` when they reply.")

    lines.append("")  # 结尾空行

    output = "\n".join(lines)
    sys.stdout.buffer.write(output.encode("utf-8"))
