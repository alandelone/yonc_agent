import argparse
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterator

from config import POLL_INTERVAL_SECONDS
from config_reader import load_config, structure_yonctask_config
from flow_pipeline import run_flow, run_l1, run_l2, run_l3
from state_manager import STATE_FILE, flatten_tree, load_state, merge_states, save_state
from sync_engine import sync_from_notion
from task_reader import fetch_and_build_task_tree
from dashboard import group_tasks_by_mode

PROJECT_ROOT = Path(__file__).resolve().parent
FLOW_TRACE_COMMANDS = {"flow", "flow-l1", "flow-l2", "flow-l3", "push-sync", "split", "tag"}


class TeeBuffer:
    def __init__(self, streams):
        self._streams = streams

    def write(self, data: bytes):
        text = data.decode("utf-8", errors="replace")
        for stream in self._streams:
            if hasattr(stream, "buffer") and callable(getattr(stream.buffer, "write", None)):
                stream.buffer.write(data)
            else:
                stream.write(text)
        return len(data)

    def flush(self):
        for stream in self._streams:
            stream.flush()

class TeeStream:
    """Write console output to multiple streams (terminal + trace logs)."""

    def __init__(self, *streams) -> None:
        self._streams = streams
        self.buffer = TeeBuffer(streams)

    @property
    def encoding(self):
        return getattr(self._streams[0], "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self._streams[0], "errors", "strict")

    def write(self, data):
        for stream in self._streams:
            stream.write(data)
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()

    def isatty(self) -> bool:
        return any(getattr(stream, "isatty", lambda: False)() for stream in self._streams)


def _logs_root_dir() -> Path:
    return PROJECT_ROOT / "data" / "logs"


def _sanitize_command_name(command_name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(command_name or "flow").strip().lower())
    return safe.strip("-") or "flow"


def _is_flow_trace_command(command_name: str | None) -> bool:
    return str(command_name or "").strip().lower() in FLOW_TRACE_COMMANDS


def _write_trace_header(handle, command_name: str, args: list[str]) -> None:
    started = datetime.now().isoformat(timespec="seconds")
    handle.write(f"=== Flow Trace Start ({started}) ===\n")
    handle.write(f"command: {command_name}\n")
    handle.write(f"argv: {' '.join(args)}\n")
    handle.write(f"pid: {os.getpid()}\n")
    handle.write(f"cwd: {Path.cwd()}\n")
    handle.write("\n")
    handle.flush()


@contextmanager
def capture_flow_trace(command_name: str, argv: list[str]) -> Iterator[Path]:
    import sys

    trace_dir = _logs_root_dir() / "flow_runs"
    trace_dir.mkdir(parents=True, exist_ok=True)

    command_safe = _sanitize_command_name(command_name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_log_path = trace_dir / f"{command_safe}_{timestamp}_{os.getpid()}.log"
    latest_log_path = trace_dir / "flow_latest.log"

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    with run_log_path.open("a", encoding="utf-8") as run_log, latest_log_path.open(
        "w", encoding="utf-8"
    ) as latest_log:
        _write_trace_header(run_log, command_name, argv)
        _write_trace_header(latest_log, command_name, argv)

        tee_stdout = TeeStream(original_stdout, run_log, latest_log)
        tee_stderr = TeeStream(original_stderr, run_log, latest_log)
        sys.stdout = tee_stdout
        sys.stderr = tee_stderr

        root_logger = logging.getLogger()
        rebound_handlers: list[tuple[logging.StreamHandler, object]] = []
        for handler in root_logger.handlers:
            if type(handler) is logging.StreamHandler:
                current_stream = getattr(handler, "stream", None)
                if current_stream is original_stdout:
                    handler.setStream(tee_stdout)
                    rebound_handlers.append((handler, original_stdout))
                elif current_stream is original_stderr:
                    handler.setStream(tee_stderr)
                    rebound_handlers.append((handler, original_stderr))
        try:
            print(f"[trace] Flow output is being saved to: {run_log_path}")
            print(f"[trace] Latest flow trace shortcut: {latest_log_path}")
            yield run_log_path
            print(f"[trace] Flow run completed at {datetime.now().isoformat(timespec='seconds')}")
        finally:
            for handler, stream in rebound_handlers:
                handler.setStream(stream)
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def configure_cli_logging(level_name: str = "INFO", command_name: str | None = None) -> Path:
    import sys

    level = getattr(logging, str(level_name).upper(), logging.INFO)
    log_dir = _logs_root_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    app_log_path = log_dir / "yonc_agent.log"

    handlers = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            app_log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        ),
    ]

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )
    if command_name:
        logging.getLogger(__name__).info(
            "CLI command '%s' started (pid=%s, cwd=%s)",
            command_name,
            os.getpid(),
            Path.cwd(),
        )
    return app_log_path


def cmd_show_config() -> None:
    raw_cfg = load_config()
    cfg = structure_yonctask_config(raw_cfg)
    import sys

    output = json.dumps(cfg, indent=2, ensure_ascii=False)
    sys.stdout.buffer.write(output.encode("utf-8") + b"\n")


def cmd_sync() -> None:
    from livetoday_sync import sync_livetoday_checks_to_livev2

    print("Checking for dashboard updates...")
    sync_livetoday_checks_to_livev2()

    print("Fetching tasks from Notion...")
    notion_tree = fetch_and_build_task_tree()
    flat_notion = flatten_tree(notion_tree)

    print("Syncing states...")
    working_state = sync_from_notion(flat_notion)
    merged_state = merge_states(notion_tree, working_state)
    save_state(merged_state, STATE_FILE)
    print("Sync complete.")


def cmd_push_sync() -> None:
    print("Legacy wrapper: push-sync -> flow-l1")
    run_l1()


def cmd_split() -> None:
    print("Legacy wrapper: split -> flow-l2")
    run_l2()


def cmd_tag() -> None:
    print("Legacy wrapper: tag -> flow-l3")
    run_l3()


def cmd_flow() -> None:
    run_flow()


def cmd_flow_l1() -> None:
    print("Running flow-l1 (L1 stage)...")
    run_l1()


def cmd_flow_l2() -> None:
    print("Running flow-l2 (L2 stage)...")
    run_l2()


def cmd_flow_l3() -> None:
    print("Running flow-l3 (L3 stage)...")
    run_l3()


def cmd_poll() -> None:
    print(f"Starting polling loop. Interval: {POLL_INTERVAL_SECONDS}s")
    try:
        while True:
            cmd_sync()
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nPolling stopped.")


def cmd_suggest(level: float = None, max_level: float = None) -> None:
    """根据能量等级过滤 dashboard 任务列表，输出编号建议清单。"""
    import sys

    raw_cfg = load_config()
    structured_cfg = structure_yonctask_config(raw_cfg)
    state = load_state(STATE_FILE)

    if not state:
        print("No task state found. Run 'sync' or 'track' first.")
        return

    # 从 config modes 中查找匹配能量等级的 mode 名称
    all_modes = structured_cfg.get("modes", [])

    if level is None and max_level is None:
        # 没有指定任何 level，展示可用的能量等级列表然后退出
        sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.write("Available energy levels (from YONCTASK_CONFIG Modes):\n".encode("utf-8"))
        sys.stdout.buffer.write(("─" * 60 + "\n").encode("utf-8"))
        for m in sorted(all_modes, key=lambda x: x.get("level", 0), reverse=True):
            line = f"  Lv{m['level']:<5}  {m['mode_name']:<15}  {m.get('description', '')}\n"
            sys.stdout.buffer.write(line.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.write(
            "Usage: python main.py suggest --level <N> | --max-level <N>\n".encode("utf-8")
        )
        return

    # 确定匹配的 mode 名称集合
    matched_mode_names: set[str] = set()
    for m in all_modes:
        m_level = m.get("level", 0)
        if level is not None and m_level == level:
            matched_mode_names.add(m["mode_name"])
        elif max_level is not None and m_level <= max_level:
            matched_mode_names.add(m["mode_name"])

    if not matched_mode_names:
        target = level if level is not None else max_level
        print(f"No modes found for energy level {target}. Use 'suggest' without args to see available levels.")
        return

    # 过滤 L4 已分配且 processed 的任务（与 dashboard 同一口径）
    l4_tasks = [
        t for t in state
        if t.get("wbs_level") == 4
        and (t.get("tags") or {}).get("Modes")
        and t.get("generated_selection_processed", False)
        and not t.get("checked")
        and str(t.get("status", "")).lower() not in ["done", "completed"]
    ]

    # 通过 mode_name 匹配任务 tag
    known_modes = [m_obj["mode_name"] for m_obj in all_modes]
    filtered_tasks = []
    for t in l4_tasks:
        mode_val = (t.get("tags") or {}).get("Modes", "")
        for mode_name in known_modes:
            if mode_name in mode_val and mode_name in matched_mode_names:
                filtered_tasks.append((t, mode_name))
                break

    if not filtered_tasks:
        label = f"Lv{level}" if level is not None else f"≤Lv{max_level}"
        print(f"No active tasks found for energy level {label}.")
        return

    # 按 mode 分组输出
    from collections import OrderedDict
    by_mode: OrderedDict[str, list] = OrderedDict()
    for t, mode_name in filtered_tasks:
        by_mode.setdefault(mode_name, []).append(t)

    label = f"Lv{level}" if level is not None else f"≤Lv{max_level}"
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.write(f"Suggested tasks for energy {label}  ({len(filtered_tasks)} tasks)\n".encode("utf-8"))
    sys.stdout.buffer.write(("═" * 60 + "\n").encode("utf-8"))

    counter = 1
    for mode_name, tasks in by_mode.items():
        # 找到该 mode 的 level
        mode_level = next((m["level"] for m in all_modes if m["mode_name"] == mode_name), "?")
        header = f"\n  ── {mode_name} (Lv{mode_level}, {len(tasks)} tasks) ──\n"
        sys.stdout.buffer.write(header.encode("utf-8"))
        for t in tasks:
            title = t.get("original_notion_title", t.get("title", ""))
            line = f"    {counter:3d}. {title}\n"
            sys.stdout.buffer.write(line.encode("utf-8"))
            counter += 1

    sys.stdout.buffer.write(b"\n")


def cmd_daily(
    mode: str = "read",
    prop_name: str = None,
    value: str = None,
    date_str: str = None,
    time_str: str = None,
    cron_name: str = None,
    cron_type: str = None,
) -> None:
    """Read/write properties on the DailyState database.

    Modes:
      read       – show today's (or --date) page properties
      write      – update a property on today's page
      schema     – show database schema with multi_select options
      cron-dash  – list upcoming crons within 1.5h time window
      cron-query – query cron details by name or type
      cron-post  – check/update a cron property
    """
    import sys
    from datetime import date as date_cls
    from config import DAILYSTATE_DB_ID
    from notion_db_utils import (
        extract_all_properties,
        get_database_schema,
        query_page_by_date,
        build_property_payload,
        update_page_properties,
    )

    target_date = date_str or date_cls.today().isoformat()

    # ── cron-dash mode ──
    if mode == "cron-dash":
        from cron_manager import get_upcoming_crons, format_dash_output

        crons = get_upcoming_crons(time_str=time_str)
        if not crons:
            sys.stdout.buffer.write(b"No pending crons in the current time window.\n")
            return
        output = format_dash_output(crons, time_str=time_str)
        sys.stdout.buffer.write((output + "\n").encode("utf-8"))
        return

    # ── cron-query mode ──
    if mode == "cron-query":
        from cron_manager import query_cron as _query_cron

        output = _query_cron(cron_name=cron_name, cron_type=cron_type)
        sys.stdout.buffer.write((output + "\n").encode("utf-8"))
        return

    # ── cron-post mode ──
    if mode == "cron-post":
        from cron_manager import post_cron

        if not cron_name:
            sys.stdout.buffer.write(
                b"Error: --cron-name is required for cron-post mode.\n"
            )
            return
        output = post_cron(name_in_db=cron_name, value=value)
        sys.stdout.buffer.write((output + "\n").encode("utf-8"))
        return

    # ── schema mode ──
    if mode == "schema":
        schema = get_database_schema(DAILYSTATE_DB_ID)
        sys.stdout.buffer.write(f"\n Database Schema ({len(schema)} properties)\n".encode("utf-8"))
        sys.stdout.buffer.write(("═" * 60 + "\n").encode("utf-8"))
        for name, prop in sorted(schema.items(), key=lambda x: x[0]):
            ptype = prop.get("type", "?")
            line = f"  {name:30s}  [{ptype}]"
            if ptype == "multi_select":
                options = prop.get("multi_select", {}).get("options", [])
                opt_names = [o["name"] for o in options]
                line += f"  options: {opt_names}"
            sys.stdout.buffer.write((line + "\n").encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
        return

    # ── find the target page (matches date-mention titles via plain_text) ──
    page = query_page_by_date(DAILYSTATE_DB_ID, target_date)
    if not page:
        sys.stdout.buffer.write(
            f"No page found for date: {target_date}\n".encode("utf-8")
        )
        return
    page_id = page["id"]

    # ── read mode ──
    if mode == "read":
        props = extract_all_properties(page)

        # If --prop is given, show only that single property
        if prop_name:
            if prop_name not in props:
                sys.stdout.buffer.write(
                    f"Error: property '{prop_name}' not found.\n".encode("utf-8")
                )
                sys.stdout.buffer.write(
                    f"Available: {sorted(props.keys())}\n".encode("utf-8")
                )
                return
            val = props[prop_name]
            ptype = page["properties"][prop_name].get("type", "?")
            display = val if val != "" else "(empty)"
            if isinstance(val, list):
                display = ", ".join(val) if val else "(none)"
            sys.stdout.buffer.write(
                f"{prop_name} [{ptype}] = {display}\n".encode("utf-8")
            )
            return

        # No --prop: show all properties
        sys.stdout.buffer.write(
            f"\n DailyState for {target_date}  (page: ...{page_id[-6:]})\n".encode("utf-8")
        )
        sys.stdout.buffer.write(("═" * 60 + "\n").encode("utf-8"))
        for name, val in sorted(props.items(), key=lambda x: x[0]):
            ptype = page["properties"][name].get("type", "?")
            display = val if val != "" else "(empty)"
            if isinstance(val, list):
                display = ", ".join(val) if val else "(none)"
            line = f"  {name:30s}  [{ptype:12s}]  = {display}\n"
            sys.stdout.buffer.write(line.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
        return

    # ── write mode ──
    if mode == "write":
        if not prop_name:
            sys.stdout.buffer.write(b"Error: --prop is required for write mode.\n")
            return
        if value is None:
            sys.stdout.buffer.write(b"Error: --value is required for write mode.\n")
            return

        # Auto-detect property type from schema
        schema = get_database_schema(DAILYSTATE_DB_ID)
        prop_schema = schema.get(prop_name)
        if not prop_schema:
            sys.stdout.buffer.write(
                f"Error: property '{prop_name}' not found in database.\n".encode("utf-8")
            )
            sys.stdout.buffer.write(
                f"Available: {list(schema.keys())}\n".encode("utf-8")
            )
            return

        prop_type = prop_schema.get("type")

        # Parse the string value into the correct Python type
        if prop_type == "checkbox":
            parsed = value.lower() in ("true", "1", "yes", "on")
        elif prop_type == "number":
            parsed = None if value.lower() in ("none", "null", "") else (
                float(value) if "." in value else int(value)
            )
        elif prop_type == "multi_select":
            # Accept comma-separated names: "Reading,Gym"
            parsed = [v.strip() for v in value.split(",") if v.strip()]
        elif prop_type == "rich_text":
            parsed = value
        else:
            sys.stdout.buffer.write(
                f"Error: unsupported property type '{prop_type}' for write.\n".encode("utf-8")
            )
            return

        payload = build_property_payload(prop_name, prop_type, parsed)
        update_page_properties(page_id, payload)
        sys.stdout.buffer.write(
            f"✅ Updated '{prop_name}' = {parsed}  (page: ...{page_id[-6:]})\n".encode("utf-8")
        )
        return

    sys.stdout.buffer.write(
        f"Unknown mode: '{mode}'. Use: read, write, schema, cron-dash, cron-query, cron-post\n".encode("utf-8")
    )


def cmd_timeliner() -> None:
    from timeliner_sync import sync_timeliner

    sync_timeliner()


def cmd_timeliner_diff() -> None:
    from timeliner_diff import print_date_diff_all

    print_date_diff_all()


def cmd_focus(move_to: int = None, synctime: bool = False, done: bool = False) -> None:
    import sys
    from config import LIVETODAY_PAGE_ID
    from dashboard import write_dashboard
    from focus_tracker import (
        FOCUS_EMOJI,
        list_focusable_tasks,
        load_focus_log,
        record_focus_event,
        save_focus_log,
    )

    # --synctime: sync focus_log history -> tasklist_state.json timetaken[]
    if synctime:
        from focus_time_sync import sync_focus_time_to_state

        periods, tasks = sync_focus_time_to_state()
        sys.stdout.buffer.write(
            f"Synced {periods} focus period(s) across {tasks} task(s).\n".encode("utf-8")
        )
        return

    # --done: 结束当前焦点会话 + 在 Notion 上勾选该任务
    if done:
        from focus_time_sync import sync_focus_time_to_state
        from notion_client import update_block

        log = load_focus_log()
        current = log.get("current_focus")
        if not current:
            sys.stdout.buffer.write(b"No active focus to mark as done.\n")
            return

        block_id = current["block_id"]
        title = current["title"]

        # 结束焦点计时
        log = record_focus_event(log, block_id, title, "end")
        save_focus_log(log)

        # 同步已完成的 focus 时间到 tasklist_state
        sync_focus_time_to_state()

        # 在 Notion 上勾选 to_do checkbox
        try:
            update_block(block_id, {"to_do": {"checked": True}})
        except Exception as e:
            sys.stdout.buffer.write(
                f"Warning: failed to check task in Notion: {e}\n".encode("utf-8")
            )

        # 重写 dashboard（清除 focus marker）
        notion_tree = fetch_and_build_task_tree()
        if notion_tree:
            raw_cfg = load_config()
            structured_cfg = structure_yonctask_config(raw_cfg)
            working_state = load_state(STATE_FILE)
            merged = merge_states(notion_tree, working_state)
            write_dashboard(
                LIVETODAY_PAGE_ID, merged, structured_cfg,
                focus_block_id=None
            )

        sys.stdout.buffer.write(
            f"Done: {title}\n".encode("utf-8")
        )
        return

    notion_tree = fetch_and_build_task_tree()
    if not notion_tree:
        print("No tasks found in Notion.")
        return

    tasks = list_focusable_tasks(notion_tree)

    if move_to is not None:
        target = next((t for t in tasks if t["index"] == move_to), None)
        if not target:
            print(f"Error: index {move_to} is out of range 1-{len(tasks)}")
            return

        log = load_focus_log()
        prev_focus = log.get("current_focus")

        if prev_focus and prev_focus.get("block_id") == target["block_id"]:
            sys.stdout.buffer.write(f"Already focused: {target['title']}\n".encode("utf-8"))
            return

        # End previous focus, start new one
        if prev_focus:
            log = record_focus_event(log, prev_focus["block_id"], prev_focus["title"], "end")
        log = record_focus_event(log, target["block_id"], target["title"], "start")
        save_focus_log(log)

        # Rewrite dashboard with new focus marker
        raw_cfg = load_config()
        structured_cfg = structure_yonctask_config(raw_cfg)
        working_state = load_state(STATE_FILE)
        merged = merge_states(notion_tree, working_state)
        block_count, _ = write_dashboard(
            LIVETODAY_PAGE_ID, merged, structured_cfg,
            focus_block_id=target["block_id"]
        )
        sys.stdout.buffer.write(
            f"Focus moved to [{move_to}] {target['title']} (dashboard: {block_count} blocks)\n".encode("utf-8")
        )

        # 计算预期剩余时长 = estimated_time_h - 累计 timetaken，null 默认 30min
        task_state = next(
            (t for t in working_state
             if (t.get("notion_block_id") or t.get("id", "")) == target["block_id"]),
            None
        )
        if task_state:
            metrics = task_state.get("metrics", {})
            estimated_h = metrics.get("estimated_time_h")
            timetaken = metrics.get("timetaken", [])

            total_spent_min = 0.0
            for period in timetaken:
                start_str = period.get("start")
                end_str = period.get("end")
                if start_str and end_str:
                    start_dt = datetime.fromisoformat(start_str)
                    end_dt = datetime.fromisoformat(end_str)
                    total_spent_min += (end_dt - start_dt).total_seconds() / 60

            estimated_min = (estimated_h * 60) if estimated_h is not None else 30
            remaining_min = max(0, int(estimated_min - total_spent_min))
            sys.stdout.buffer.write(
                f"duration: {remaining_min}min\n".encode("utf-8")
            )

        return

    # No args: display task list with focus indicator
    log = load_focus_log()
    current_focus_id = (log.get("current_focus") or {}).get("block_id")

    sys.stdout.buffer.write(f"\nTask List ({FOCUS_EMOJI} = current focus)\n".encode("utf-8"))
    sys.stdout.buffer.write(("-" * 50).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    for task in tasks:
        marker = f" {FOCUS_EMOJI}" if task["block_id"] == current_focus_id else ""
        line = f"  {task['index']:3d}. {task['title']}{marker}\n"
        sys.stdout.buffer.write(line.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.write(
        "Usage: python main.py focus --move <N> | --synctime\n".encode("utf-8")
    )


def cmd_track() -> None:
    import sys
    from config import LIVETODAY_PAGE_ID
    from dashboard import build_dashboard_blocks, write_dashboard
    from focus_tracker import (
        FOCUS_EMOJI,
        detect_focus_from_livetoday,
        load_focus_log,
        record_focus_event,
        save_focus_log,
        track_focus,
    )
    from livetoday_sync import sync_livetoday_checks_to_livev2

    # Sync any checked tasks from LIVETODAY → LIVEV2 BEFORE clearing the dashboard
    print("Checking for dashboard updates...")
    sync_livetoday_checks_to_livev2()

    print("Fetching tasks from Notion...")
    notion_tree = fetch_and_build_task_tree()
    if not notion_tree:
        print("No tasks found in Notion.")
        return

    # Build the task state for dashboard
    raw_cfg = load_config()
    structured_cfg = structure_yonctask_config(raw_cfg)
    working_state = load_state(STATE_FILE)
    merged = merge_states(notion_tree, working_state)
    
    from state_manager import save_state
    save_state(merged, STATE_FILE)

    # Build a provisional task_index_map (without focus) to detect user-moved emoji
    _, provisional_map = build_dashboard_blocks(merged, structured_cfg)

    # Detect focus from current LIVETODAY page (before clearing)
    detected = detect_focus_from_livetoday(LIVETODAY_PAGE_ID, provisional_map)

    # Compare with stored focus state
    log = load_focus_log()
    prev_focus = log.get("current_focus")
    
    # Auto-stop on completion feature:
    # If the user checks off the task while focusing on it, force it into the idle state.
    if detected:
        is_focused_task_done = False
        for t in merged:
            if (t.get("notion_block_id") or t.get("id", "")) == detected["block_id"]:
                if t.get("checked") or str(t.get("status", "")).lower() in ["done", "completed"]:
                    is_focused_task_done = True
                break
        if is_focused_task_done:
            detected = None

    focus_block_id = None

    if detected:
        focus_block_id = detected["block_id"]
        # If user moved the emoji on LIVETODAY, update the log
        if prev_focus is None:
            log = record_focus_event(log, detected["block_id"], detected["title"], "start")
            save_focus_log(log)
        elif prev_focus.get("block_id") != detected["block_id"]:
            log = record_focus_event(log, prev_focus["block_id"], prev_focus["title"], "end")
            log = record_focus_event(log, detected["block_id"], detected["title"], "start")
            save_focus_log(log)
    elif prev_focus:
        # User either deleted the emoji or moved it to the top idle zone.
        # End the previous session and clear the focus.
        log = record_focus_event(log, prev_focus["block_id"], prev_focus["title"], "end")
        save_focus_log(log)
        focus_block_id = None

    current_focus = log.get("current_focus")
    if current_focus:
        sys.stdout.buffer.write(f"Current focus: {current_focus['title']}\n".encode("utf-8"))
        sys.stdout.buffer.write(f"Started at: {current_focus['started_at']}\n".encode("utf-8"))
    else:
        sys.stdout.buffer.write(f"No active focus session\n".encode("utf-8"))

    # Rewrite dashboard with focus marker
    print("Updating dashboard...")
    block_count, _ = write_dashboard(
        LIVETODAY_PAGE_ID, merged, structured_cfg,
        focus_block_id=focus_block_id
    )
    print(f"Dashboard updated: {block_count} blocks written.")

    # Automatically sync completed focus time explicitly into state JSON
    from focus_time_sync import sync_focus_time_to_state
    periods, tasks = sync_focus_time_to_state()
    if periods > 0:
        print(f"Auto-synced {periods} completed focus session(s) to {tasks} task(s) timetaken metrics.")


def _dispatch_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.command == "flow":
        cmd_flow()
    elif args.command == "flow-l1":
        cmd_flow_l1()
    elif args.command == "flow-l2":
        cmd_flow_l2()
    elif args.command == "flow-l3":
        cmd_flow_l3()
    elif args.command == "sync":
        cmd_sync()
    elif args.command == "push-sync":
        cmd_push_sync()
    elif args.command == "tag":
        cmd_tag()
    elif args.command == "split":
        cmd_split()
    elif args.command == "poll":
        cmd_poll()
    elif args.command == "show-config":
        cmd_show_config()
    elif args.command == "timeliner":
        cmd_timeliner()
    elif args.command == "timeliner-diff":
        cmd_timeliner_diff()
    elif args.command == "focus":
        cmd_focus(move_to=args.move, synctime=args.synctime, done=args.done)
    elif args.command == "track":
        cmd_track()
    elif args.command == "suggest":
        cmd_suggest(level=args.level, max_level=args.max_level)
    elif args.command == "daily":
        cmd_daily(
            mode=args.mode,
            prop_name=args.prop,
            value=args.value,
            date_str=args.date,
            time_str=args.time,
            cron_name=args.cron_name,
            cron_type=args.cron_type,
        )
    else:
        parser.print_help()


def main() -> None:
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Notion Task Management System")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="CLI logging level",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("flow", help="Run full staged flow (L1 -> L2 -> L3)")
    subparsers.add_parser("flow-l1", help="Run L1 stage")
    subparsers.add_parser("flow-l2", help="Run L2 stage")
    subparsers.add_parser("flow-l3", help="Run L3 stage")

    subparsers.add_parser("sync", help="Sync state from Notion")
    subparsers.add_parser("push-sync", help="Legacy wrapper to L1 flow")
    subparsers.add_parser("tag", help="Legacy wrapper to L3 flow")
    subparsers.add_parser("split", help="Legacy wrapper to L2 flow")
    subparsers.add_parser("poll", help="Start polling loop")
    subparsers.add_parser("show-config", help="Print parsed YoncTask_config")
    subparsers.add_parser("timeliner", help="Sync TIMELINER page with progress")
    subparsers.add_parser("timeliner-diff", help="Show timeline date change history")
    focus_parser = subparsers.add_parser("focus", help="Show task list with focus position / move focus / sync time")
    focus_parser.add_argument("--move", type=int, default=None, help="Move focus to task number N")
    focus_parser.add_argument("--synctime", action="store_true", default=False, help="Sync focus_log time periods to tasklist_state timetaken[]")
    focus_parser.add_argument("--done", action="store_true", default=False, help="Mark current focus task as done (check in Notion + end session)")
    subparsers.add_parser("track", help="Track focus + update dashboard")
    suggest_parser = subparsers.add_parser("suggest", help="Show filtered task list by energy level (Mode level from config)")
    suggest_parser.add_argument("--level", type=float, default=None, help="Exact energy level to filter (e.g. 3.3, 2, 1)")
    suggest_parser.add_argument("--max-level", type=float, default=None, help="Show tasks at or below this energy level")

    daily_parser = subparsers.add_parser("daily", help="Read/write DailyState database properties & cron management")
    daily_parser.add_argument("mode", nargs="?", default="read",
                              choices=["read", "write", "schema", "cron-dash", "cron-query", "cron-post"],
                              help="Operation mode (default: read)")
    daily_parser.add_argument("--prop", type=str, default=None,
                              help="Property name to read/write")
    daily_parser.add_argument("--value", type=str, default=None,
                              help="Value to set. For multi_select use comma-separated: 'Tag1,Tag2'")
    daily_parser.add_argument("--date", type=str, default=None,
                              help="Target date (YYYY-MM-DD). Defaults to today.")
    daily_parser.add_argument("--time", type=str, default=None,
                              help="Override current time (HH:MM) for cron-dash")
    daily_parser.add_argument("--cron-name", type=str, default=None, dest="cron_name",
                              help="Cron name (name_in_db) for cron-query / cron-post")
    daily_parser.add_argument("--cron-type", type=str, default=None, dest="cron_type",
                              help="Cron type filter for cron-query (e.g. trace, traceXlt)")

    args = parser.parse_args()
    app_log_path = configure_cli_logging(args.log_level, args.command)
    logging.getLogger(__name__).info("Application log file: %s", app_log_path)

    if _is_flow_trace_command(args.command):
        with capture_flow_trace(str(args.command), sys.argv):
            _dispatch_command(args, parser)
    else:
        _dispatch_command(args, parser)


if __name__ == "__main__":
    main()
