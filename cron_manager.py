"""
DailyState Cron 管理模块。

从 YONCTASK_CONFIG 的 Cron section 解析定时任务，
提供 Dash(列表)、Query(查询)、Post(打卡) 三个核心能力。

Cron 条目格式:
  {hour}.{section} | {type} | {name_in_db} | {description}
  {start_hour}-{end_hour}.{section} | {type} | {name_in_db} | {description}
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from config import DAILYSTATE_DB_ID

PROJECT_ROOT = Path(__file__).resolve().parent
CACHE_FILE = PROJECT_ROOT / "data" / "cron_cache.json"
CACHE_MAX_AGE_SECONDS = 86400  # 缓存有效期: 1 天


# ═══════════════════════════════════════════════════════════
# 1. Cron 解析与缓存
# ═══════════════════════════════════════════════════════════

def parse_cron_entries(raw_cron_list: list[str]) -> list[dict]:
    """将 YONCTASK_CONFIG Cron section 的原始字符串解析为结构化列表。

    支持两种 hour 格式:
      - 单时间: `8.1`   → start_hour=8, end_hour=None
      - 区间:   `9-18.3` → start_hour=9, end_hour=18

    Returns:
        [{
            "start_hour": 8,
            "end_hour": None,
            "section": 1,
            "cron_type": "trace",
            "name_in_db": "晨仪:💊",
            "description": "Eat Medi, Supplement",
            "raw": "8.1 | trace | 晨仪:💊 | Eat Medi, Supplement"
        }]
    """
    entries: list[dict] = []

    # 匹配 hour 部分: `8.1` 或 `9-18.3` 或 `9,12,15,18.1`
    hour_pattern = re.compile(
        r"^\s*(?P<start>\d+)(?:(?P<sep>[-|,])(?P<end>[\d,]+))?\.(?P<section>\d+)\s*$"
    )

    for raw_line in raw_cron_list:
        parts = [p.strip() for p in raw_line.split("|")]
        if len(parts) < 4:
            continue  # 格式不完整，跳过

        hour_str, cron_type, name_in_db, description = (
            parts[0],
            parts[1],
            parts[2],
            "|".join(parts[3:]),  # description 可能包含 | 字符
        )

        m = hour_pattern.match(hour_str)
        if not m:
            continue

        start_hour = int(m.group("start"))
        sep = m.group("sep")
        if sep == "-":
            end_hour = int(m.group("end"))
        elif sep == ",":
            end_hour = [int(x.strip()) for x in m.group("end").split(",") if x.strip()]
        else:
            end_hour = None
        section = int(m.group("section"))

        entries.append({
            "start_hour": start_hour,
            "end_hour": end_hour,
            "section": section,
            "cron_type": cron_type.strip(),
            "name_in_db": name_in_db.strip(),
            "description": description.strip(),
            "raw": raw_line.strip(),
        })

    return entries


def _is_cache_valid() -> bool:
    """检查缓存文件是否存在且未过期(< 1 天)。"""
    if not CACHE_FILE.exists():
        return False
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        cached_ts = data.get("cached_at", "")
        cached_dt = datetime.fromisoformat(cached_ts)
        age = (datetime.now() - cached_dt).total_seconds()
        return age < CACHE_MAX_AGE_SECONDS
    except (json.JSONDecodeError, ValueError, KeyError):
        return False


def save_cron_cache(entries: list[dict]) -> None:
    """将解析后的 Cron 列表保存到本地 JSON 缓存。"""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cached_at": datetime.now().isoformat(timespec="seconds"),
        "entries": entries,
    }
    CACHE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_cron_cache() -> list[dict]:
    """从缓存加载 Cron 列表；若缓存过期则重新从 Notion 拉取并刷新缓存。"""
    if _is_cache_valid():
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data.get("entries", [])

    # 缓存过期或不存在 → 重新拉取
    from config_reader import load_config

    raw_cfg = load_config()
    raw_cron = raw_cfg.get("Cron", [])
    entries = parse_cron_entries(raw_cron)
    save_cron_cache(entries)
    return entries


# ═══════════════════════════════════════════════════════════
# 2. Schema 缓存（属性类型 + multi_select 选项）
# ═══════════════════════════════════════════════════════════

_schema_cache: dict[str, Any] | None = None


def _get_schema() -> dict[str, Any]:
    """获取 DailyState DB schema（进程内缓存）。"""
    global _schema_cache
    if _schema_cache is None:
        from notion_db_utils import get_database_schema
        _schema_cache = get_database_schema(DAILYSTATE_DB_ID)
    return _schema_cache


def _get_prop_type(name_in_db: str) -> str | None:
    """查找 DB 属性类型；找不到返回 None。"""
    schema = _get_schema()
    prop = schema.get(name_in_db)
    if prop:
        return prop.get("type")
    return None


# ═══════════════════════════════════════════════════════════
# 3. Dash — 当前时间窗口内的 Cron 列表
# ═══════════════════════════════════════════════════════════

def _read_daily_prop(name_in_db: str, target_date: str | None = None) -> Any:
    """读取今日 DailyState 的单个属性值。"""
    from notion_db_utils import query_page_by_date, extract_all_properties

    today = target_date or date.today().isoformat()
    page = query_page_by_date(DAILYSTATE_DB_ID, today)
    if not page:
        return None
    props = extract_all_properties(page)
    return props.get(name_in_db)


def _is_cron_done(name_in_db: str, prop_type: str | None, current_value: Any) -> bool:
    """根据属性类型判断该 Cron 是否已完成。

    - checkbox: True = done
    - number: > 0 = done
    - multi_select: 有选项 = done
    - rich_text: 非空 = done
    """
    if prop_type == "checkbox":
        return bool(current_value)
    elif prop_type == "number":
        return current_value is not None and current_value > 0
    elif prop_type == "multi_select":
        return bool(current_value)  # 非空列表
    elif prop_type == "rich_text":
        return bool(current_value and str(current_value).strip())
    # 无法判断 → 视为未完成
    return False


def get_upcoming_crons(
    time_str: str | None = None,
    window_hours: float = 1.5,
) -> list[dict]:
    """返回当前时间窗口内的 Cron 列表（含完成状态）。

    过滤逻辑:
      - 只显示已到时间的任务 (cron_start_hour <= now_hour)
      - 且在过去 window_hours 时间窗口内 (now_hour - cron_start_hour <= window_hours)
      - 对于有 end_hour 的任务 (traceXlt / Trighear): 若 now > end_hour 则不显示
      - 查询 DailyState DB 判断是否已完成

    Args:
        time_str: 覆盖当前时间 (格式 "HH:MM")，用于调试
        window_hours: 时间窗口大小 (默认 1.5h)

    Returns:
        已排序的 Cron 列表，每项含 done / prop_type 字段
    """
    entries = load_cron_cache()

    # 解析当前时间
    if time_str:
        parts = time_str.split(":")
        now_hour = int(parts[0]) + int(parts[1]) / 60.0 if len(parts) == 2 else float(parts[0])
    else:
        now = datetime.now()
        now_hour = now.hour + now.minute / 60.0

    # 第一轮: 时间过滤
    filtered: list[dict] = []
    for e in entries:
        start_h = e["start_hour"]
        end_h = e["end_hour"]
        cron_type = e.get("cron_type", "").lower()

        # 隐藏 Trighear 类型的任务 (它只在特定条件下被查询，不在常规面板中显示)
        if cron_type == "trighear":
            continue

        is_valid = False
        
        # 1. 检查 start_hour 窗口
        if start_h <= now_hour and (now_hour - start_h) <= window_hours:
            is_valid = True
            
        # 2. 如果不满足 start_hour，检查 end_hour
        elif isinstance(end_h, list):
            # 对于多触发点的列表：[12, 15, 18]，只要满足任意一个即可
            for h in end_h:
                if h <= now_hour and (now_hour - h) <= window_hours:
                    is_valid = True
                    break
        elif end_h is not None:
            # 对于范围区间：9-18，只要当前时间在区间结束之前，且已过开始时间，则一直保留
            if start_h <= now_hour <= end_h:
                is_valid = True

        if not is_valid:
            continue

        filtered.append(e.copy())

    if not filtered:
        return []

    # 第二轮: 查询 DailyState 完成状态（批量读取一次 page）
    from notion_db_utils import query_page_by_date, extract_all_properties

    today = date.today().isoformat()
    page = query_page_by_date(DAILYSTATE_DB_ID, today)
    all_props = extract_all_properties(page) if page else {}

    for e in filtered:
        name = e["name_in_db"]
        prop_type = _get_prop_type(name)
        current_value = all_props.get(name)

        e["prop_type"] = prop_type
        e["current_value"] = current_value
        e["done"] = _is_cron_done(name, prop_type, current_value)

    # 按 start_hour + section 排序
    filtered.sort(key=lambda x: (x["start_hour"], x["section"]))
    return filtered


def format_dash_output(crons: list[dict], time_str: str | None = None) -> str:
    """将 Dash 结果格式化为 LLM 友好的结构化文本。"""
    now_label = time_str or datetime.now().strftime("%H:%M")
    today_label = date.today().isoformat()

    undone = [c for c in crons if not c["done"]]
    lines = [
        f"CRON_DASH | {today_label} {now_label} | {len(undone)} pending / {len(crons)} total",
        "─" * 55,
    ]

    for c in crons:
        status = "[DONE]  " if c["done"] else "[UNDONE]"
        type_info = c["cron_type"]
        prop_info = f", {c['prop_type']}" if c.get("prop_type") else ""
        hour_label = f"{c['start_hour']:02d}:00"
        if c["end_hour"] is not None:
            if isinstance(c["end_hour"], list):
                end_str = ",".join(str(x) for x in c["end_hour"])
                hour_label = f"{c['start_hour']:02d},{end_str}"
            else:
                hour_label = f"{c['start_hour']:02d}-{c['end_hour']:02d}"
        # 描述字段: 截取前 40 字符避免过长
        desc = c.get("description", "")
        desc_part = f"  — {desc[:40]}" if desc else ""
        lines.append(
            f"  {status} {c['name_in_db']}  ({type_info}{prop_info})  @{hour_label}{desc_part}"
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 4. Query — 按名称或类型查询 Cron 详情
# ═══════════════════════════════════════════════════════════

def query_cron(
    cron_name: str | None = None,
    cron_type: str | None = None,
) -> str:
    """按 name_in_db 或 cron_type 查询 Cron 详细信息。

    如果按 type 查询且有多条结果，用分隔线隔开。
    description 中的 \\n 会换行显示。
    """
    entries = load_cron_cache()

    # 过滤
    matched: list[dict] = []
    if cron_name:
        matched = [e for e in entries if e["name_in_db"] == cron_name]
    elif cron_type:
        matched = [
            e for e in entries
            if e["cron_type"].lower() == cron_type.lower()
        ]
    else:
        matched = entries

    if not matched:
        target = cron_name or cron_type or "(all)"
        return f"No cron found for: {target}"

    blocks: list[str] = []
    for e in matched:
        hour_label = f"{e['start_hour']:02d}:00"
        if e["end_hour"] is not None:
            if isinstance(e["end_hour"], list):
                end_str = ",".join(str(x) for x in e["end_hour"])
                hour_label = f"{e['start_hour']:02d}:00, {end_str} (points)"
            else:
                hour_label = f"{e['start_hour']:02d}:00 - {e['end_hour']:02d}:00"

        prop_type = _get_prop_type(e["name_in_db"])
        prop_info = f"  db_type: {prop_type}" if prop_type else "  db_type: (none)"

        # description 的 \n 原文换行
        desc = e["description"].replace("\\n", "\n")

        block = (
            f"CRON: {e['name_in_db']}\n"
            f"  time: {hour_label}\n"
            f"  type: {e['cron_type']}\n"
            f"{prop_info}\n"
            f"  description: {desc}"
        )
        blocks.append(block)

    return ("\n" + "─" * 40 + "\n").join(blocks)


# ═══════════════════════════════════════════════════════════
# 5. Post — 打卡 / 更新 Cron 属性
# ═══════════════════════════════════════════════════════════

def _extract_multiselect_task_names(options: list[dict]) -> list[str]:
    """从 multi_select 选项中提取不重复的任务名。

    选项格式: "{num} X {task_name}" → 提取 task_name
    """
    names: set[str] = set()
    pattern = re.compile(r"^\d+\s*X\s*(.+)$")
    for opt in options:
        m = pattern.match(opt.get("name", ""))
        if m:
            names.add(m.group(1).strip())
    return sorted(names)


def _increment_multiselect(
    current_tags: list[str],
    target_names: list[str],
) -> list[str]:
    """multi_select 计数递增逻辑。

    当前值: ["1 X 断水", "2 X 30 X pc练习"]
    target_names: ["断水"]
    结果: ["2 X 断水", "2 X 30 X pc练习"]

    规则: 找到匹配 target_name 的 tag，将其 num+1；
          若 target_name 不在当前列表中，新增 "1 X {name}"。
    """
    pattern = re.compile(r"^(\d+)\s*X\s*(.+)$")

    # 索引现有 tags: task_name → (index, current_num)
    tag_map: dict[str, tuple[int, int]] = {}
    for i, tag in enumerate(current_tags):
        m = pattern.match(tag)
        if m:
            num = int(m.group(1))
            name = m.group(2).strip()
            tag_map[name] = (i, num)

    result = list(current_tags)

    for target in target_names:
        if target in tag_map:
            idx, old_num = tag_map[target]
            result[idx] = f"{old_num + 1} X {target}"
        else:
            result.append(f"1 X {target}")

    return result


def post_cron(
    name_in_db: str,
    value: str | None = None,
) -> str:
    """根据 DB 属性类型自动执行打卡/更新操作。

    无 value:
      - checkbox → 设为 True
      - number → 当前值 +1
      - rich_text → 返回提示需要输入 value
      - multi_select → 返回可选任务名列表

    有 value:
      - checkbox → 忽略 value，设为 True
      - number → 写入 value
      - rich_text → 写入 value
      - multi_select → 匹配 task_name 并递增计数
    """
    from notion_db_utils import (
        build_property_payload,
        extract_all_properties,
        get_database_schema,
        query_page_by_date,
        update_page_properties,
    )

    prop_type = _get_prop_type(name_in_db)
    if prop_type is None:
        return f"❌ Property '{name_in_db}' not found in DailyState DB."

    # 获取今日 page
    today = date.today().isoformat()
    page = query_page_by_date(DAILYSTATE_DB_ID, today)
    if not page:
        return f"❌ No DailyState page found for {today}."

    page_id = page["id"]
    all_props = extract_all_properties(page)
    current_value = all_props.get(name_in_db)

    # ── checkbox ──
    if prop_type == "checkbox":
        payload = build_property_payload(name_in_db, "checkbox", True)
        update_page_properties(page_id, payload)
        return f"✅ {name_in_db} (checkbox) = True"

    # ── number ──
    if prop_type == "number":
        if value is not None:
            # 有 value → 直接写入
            num_val = float(value) if "." in value else int(value)
            payload = build_property_payload(name_in_db, "number", num_val)
            update_page_properties(page_id, payload)
            return f"✅ {name_in_db} (number) = {num_val}"
        else:
            # 无 value → 当前值 +1
            old = current_value if current_value is not None else 0
            new_val = old + 1
            payload = build_property_payload(name_in_db, "number", new_val)
            update_page_properties(page_id, payload)
            return f"✅ {name_in_db} (number) = {old} → {new_val}"

    # ── rich_text ──
    if prop_type == "rich_text":
        if value is not None:
            payload = build_property_payload(name_in_db, "rich_text", value)
            update_page_properties(page_id, payload)
            return f"✅ {name_in_db} (rich_text) = \"{value}\""
        else:
            return f"📝 {name_in_db} (rich_text) requires --value. Current: \"{current_value or ''}\""

    # ── multi_select ──
    if prop_type == "multi_select":
        schema = _get_schema()
        options = schema.get(name_in_db, {}).get("multi_select", {}).get("options", [])
        available_names = _extract_multiselect_task_names(options)

        if value is not None:
            # 解析 value（可能逗号分隔: "断水,30腹式呼吸"）
            target_names = [v.strip() for v in value.split(",") if v.strip()]

            # 验证目标名称是否存在于可选列表
            invalid = [n for n in target_names if n not in available_names]
            if invalid:
                return (
                    f"❌ Unknown task name(s): {invalid}\n"
                    f"📋 Available: {available_names}"
                )

            current_tags = current_value if isinstance(current_value, list) else []
            new_tags = _increment_multiselect(current_tags, target_names)
            payload = build_property_payload(name_in_db, "multi_select", new_tags)
            update_page_properties(page_id, payload)
            return (
                f"✅ {name_in_db} (multi_select) updated\n"
                f"   before: {current_tags}\n"
                f"   after:  {new_tags}"
            )
        else:
            # 无 value → 返回可选列表
            current_tags = current_value if isinstance(current_value, list) else []
            lines = [
                f"📋 {name_in_db} (multi_select) — select task name(s):",
                f"   current: {current_tags}",
                f"   available:",
            ]
            for n in available_names:
                lines.append(f"     - {n}")
            return "\n".join(lines)

    return f"❌ Unsupported property type: {prop_type}"
