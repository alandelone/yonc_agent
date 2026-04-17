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


def cmd_timeliner() -> None:
    from timeliner_sync import sync_timeliner

    sync_timeliner()


def cmd_timeliner_diff() -> None:
    from timeliner_diff import print_date_diff_all

    print_date_diff_all()


def cmd_focus(move_to: int = None, synctime: bool = False) -> None:
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

    # Build a provisional task_index_map (without focus) to detect user-moved emoji
    _, provisional_map = build_dashboard_blocks(merged, structured_cfg)

    # Detect focus from current LIVETODAY page (before clearing)
    detected = detect_focus_from_livetoday(LIVETODAY_PAGE_ID, provisional_map)

    # Compare with stored focus state
    log = load_focus_log()
    prev_focus = log.get("current_focus")
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
        # Emoji gone from LIVETODAY but log says we had focus — keep it
        focus_block_id = prev_focus.get("block_id")

    # If no focus at all after daily reset, default to first task (index 1)
    if focus_block_id is None and provisional_map:
        focus_block_id = provisional_map.get(1)

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
        cmd_focus(move_to=args.move, synctime=args.synctime)
    elif args.command == "track":
        cmd_track()
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
    subparsers.add_parser("track", help="Track focus + update dashboard")

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
