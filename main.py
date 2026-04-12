import argparse
import json
import logging
import time

from config import POLL_INTERVAL_SECONDS
from config_reader import load_config, structure_yonctask_config
from flow_pipeline import run_flow, run_l1, run_l2, run_l3
from state_manager import STATE_FILE, flatten_tree, load_state, merge_states, save_state
from sync_engine import sync_from_notion
from task_reader import fetch_and_build_task_tree


def configure_cli_logging(level_name: str = "INFO") -> None:
    import sys

    level = getattr(logging, str(level_name).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
        force=True,
    )


def cmd_show_config() -> None:
    raw_cfg = load_config()
    cfg = structure_yonctask_config(raw_cfg)
    import sys

    output = json.dumps(cfg, indent=2, ensure_ascii=False)
    sys.stdout.buffer.write(output.encode("utf-8") + b"\n")


def cmd_sync() -> None:
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


def cmd_focus(move_to: int = None) -> None:
    import sys
    from focus_tracker import (
        FOCUS_EMOJI,
        find_focus_task,
        list_focusable_tasks,
        load_focus_log,
        move_focus_emoji,
        record_focus_event,
        save_focus_log,
    )

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

        focus_info = find_focus_task(notion_tree)
        if focus_info and focus_info["block_id"] == target["block_id"]:
            sys.stdout.buffer.write(f"Already focused: {target['title']}\n".encode("utf-8"))
            return

        if focus_info:
            log = load_focus_log()
            log = record_focus_event(log, focus_info["block_id"], focus_info["title"], "end")
            log = record_focus_event(log, target["block_id"], target["title"], "start")
            save_focus_log(log)
            move_focus_emoji(focus_info["block_id"], target["block_id"])
            sys.stdout.buffer.write(f"Focus moved to [{move_to}] {target['title']}\n".encode("utf-8"))
        else:
            from focus_tracker import _append_focus_to_block

            _append_focus_to_block(target["block_id"])
            log = load_focus_log()
            log = record_focus_event(log, target["block_id"], target["title"], "start")
            save_focus_log(log)
            sys.stdout.buffer.write(f"Focus set to [{move_to}] {target['title']}\n".encode("utf-8"))
        return

    sys.stdout.buffer.write(f"\nTask List ({FOCUS_EMOJI} = current focus)\n".encode("utf-8"))
    sys.stdout.buffer.write(("-" * 50).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    for task in tasks:
        marker = f" {FOCUS_EMOJI}" if task["has_focus"] else ""
        line = f"  {task['index']:3d}. {task['title']}{marker}\n"
        sys.stdout.buffer.write(line.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.write("Usage: python main.py focus --move <N>\n".encode("utf-8"))


def cmd_track() -> None:
    import sys
    from config import DFORGE_LINESV2_PAGE_ID, LIVETODAY_PAGE_ID
    from dashboard import write_dashboard
    from focus_tracker import FOCUS_EMOJI, track_focus

    print("Fetching tasks from Notion...")
    notion_tree = fetch_and_build_task_tree()
    if not notion_tree:
        print("No tasks found in Notion.")
        return

    current_focus = track_focus(notion_tree, DFORGE_LINESV2_PAGE_ID)
    if current_focus:
        sys.stdout.buffer.write(f"Current focus: {current_focus['title']}\n".encode("utf-8"))
        sys.stdout.buffer.write(f"Started at: {current_focus['started_at']}\n".encode("utf-8"))
    else:
        sys.stdout.buffer.write(f"No task contains focus marker {FOCUS_EMOJI}\n".encode("utf-8"))

    print("Updating dashboard...")
    raw_cfg = load_config()
    structured_cfg = structure_yonctask_config(raw_cfg)
    working_state = load_state(STATE_FILE)
    merged = merge_states(notion_tree, working_state)
    block_count = write_dashboard(LIVETODAY_PAGE_ID, merged, structured_cfg)
    print(f"Dashboard updated: {block_count} blocks written.")


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
    focus_parser = subparsers.add_parser("focus", help="Show task list with focus position / move focus")
    focus_parser.add_argument("--move", type=int, default=None, help="Move focus to task number N")
    subparsers.add_parser("track", help="Track focus + update dashboard")

    args = parser.parse_args()
    configure_cli_logging(args.log_level)

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
        cmd_focus(move_to=args.move)
    elif args.command == "track":
        cmd_track()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
