import argparse
import time
import json
from config_reader import load_config, structure_yonctask_config
from task_reader import fetch_and_build_task_tree
from state_manager import flatten_tree, save_state, load_state, STATE_FILE, CURRENT_STATE_FILE, merge_states
from sync_engine import sync_from_notion
from llm_pipeline import enrich_state_with_llm
from config import POLL_INTERVAL_SECONDS

def cmd_show_config():
    """Print parsed YoncTask_config"""
    raw_cfg = load_config()
    cfg = structure_yonctask_config(raw_cfg)
    import sys
    output = json.dumps(cfg, indent=2, ensure_ascii=False)
    sys.stdout.buffer.write(output.encode('utf-8') + b'\n')

def cmd_sync():
    """Pull Notion → update JSON → push back (Logic placeholder)"""
    print("Fetching tasks from Notion...")
    notion_tree = fetch_and_build_task_tree()
    flat_notion = flatten_tree(notion_tree)
    
    print("Syncing states...")
    # Update current_state map and identify conflicts
    working_state = sync_from_notion(flat_notion)
    
    # Merge remote structure with local LLM-applied fields
    merged_state = merge_states(notion_tree, working_state)
    
    save_state(merged_state, STATE_FILE)
    print("Sync complete.")

def cmd_push_sync():
    """Pull Notion → update JSON → apply deterministic tag correction → push tags without LLM"""
    print("Fetching tasks from Notion...")
    config_dict = load_config()
    notion_tree = fetch_and_build_task_tree()
    if not notion_tree:
        print("No tasks found in Notion.")
        return
    flat_notion = flatten_tree(notion_tree)
    
    print("Syncing states...")
    working_state = sync_from_notion(flat_notion)
    merged_state = merge_states(notion_tree, working_state)

    print("Applying rule-based tag correction (Theme/WBS) without LLM...")
    merged_state = enrich_state_with_llm(merged_state, config_dict, allow_llm=False)
    
    from sync_engine import reparent_theme_containers, push_tags_to_notion
    print("Reparenting theme/sub-theme containers...")
    merged_state = reparent_theme_containers(merged_state, config_dict)
    print("Pushing tags back to Notion directly...")
    push_tags_to_notion(merged_state, config_dict)
    
    merged_state = [t for t in merged_state if not t.get("deleted")]
    save_state(merged_state, STATE_FILE)
    print("Push Sync complete.")

def cmd_tag():
    """Run emoji tagging pipeline"""
    config_dict = load_config()
    # Always refresh from Notion to catch newly generated checkboxes
    notion_tree = fetch_and_build_task_tree()
    if not notion_tree:
        print("No tasks found in Notion. Try running 'sync' first.")
        return
    flat_notion = flatten_tree(notion_tree)
    working_state = sync_from_notion(flat_notion)
    state = merge_states(notion_tree, working_state)
        
    print("Running tagging pipeline through LLM...")
    enriched = enrich_state_with_llm(state, config_dict)
    
    from sync_engine import reparent_theme_containers, push_tags_to_notion
    print("Reparenting theme/sub-theme containers...")
    enriched = reparent_theme_containers(enriched, config_dict)
    print("Pushing tags back to Notion...")
    push_tags_to_notion(enriched, config_dict)
    
    # Drop locally deleted generated selector tasks from persisted state
    enriched = [t for t in enriched if not t.get("deleted")]
    save_state(enriched, STATE_FILE)
    print("Tagging complete. LLM outputs have been pushed back to Notion.")

def cmd_reparent_dry():
    """Dry-run: 展示 reparent_theme_containers 将要执行的操作，不修改 Notion"""
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print("Fetching tasks from Notion (dry-run mode)...")
    config_dict = load_config()
    notion_tree = fetch_and_build_task_tree()
    if not notion_tree:
        print("No tasks found in Notion.")
        return
    flat_notion = flatten_tree(notion_tree)
    working_state = sync_from_notion(flat_notion)
    merged_state = merge_states(notion_tree, working_state)

    print("Applying rule-based tag correction (no LLM)...")
    merged_state = enrich_state_with_llm(merged_state, config_dict, allow_llm=False)

    from sync_engine import reparent_theme_containers
    print("\n" + "=" * 60)
    print("  REPARENT DRY-RUN: 以下操作将在实际执行时发生")
    print("=" * 60 + "\n")
    result_state = reparent_theme_containers(merged_state, config_dict, dry_run=True)
    print(f"\n结果: {len(merged_state)} -> {len(result_state)} 个任务节点")
    print("\n运行 'python main.py push-sync' 以实际执行。")

def cmd_split():
    """Run task decomposition pipeline"""
    from task_reader import fetch_and_build_task_tree
    from llm_pipeline import split_task
    from sync_engine import push_subtasks_to_notion
    from config_reader import load_config, structure_yonctask_config, clean_task_title
    import sys
    import re

    raw_cfg = load_config()
    structured_cfg = structure_yonctask_config(raw_cfg)
    themes = structured_cfg.get("themes", {})

    # 使用树结构而非扁平 state，保留 children 信息以正确判断叶子节点
    notion_tree = fetch_and_build_task_tree()
    if not notion_tree:
        print("No tasks found in Notion. Try running 'sync' first.")
        return

    print("Splitting abstract tasks into physical to-dos...")

    def _split_all(nodes):
        """递归所有节点：处理所有节点，不再略过已有子节点的父节点"""
        for node in nodes:
            if node.get("type") == "bulleted_list_item":
                title_words = node.get("title", "")
                if "✅" not in title_words and len(title_words) > 5 and not (node.get("has_tag_style") and node.get("children")):
                    clean_title = clean_task_title(title_words, structured_cfg)
                    
                    # Extract parent theme
                    parent_theme = None
                    parent_theme_color = "default"
                    
                    # Check for explicit theme name in title
                    for t_name, t_data in themes.items():
                        if t_name in title_words:
                            parent_theme = t_name
                            parent_theme_color = t_data.get("color", "default")
                            break
                            
                    # If not found explicitly, look for sub-theme patterns or fallback to context heading
                    if not parent_theme:
                        context_heading = node.get("context_heading", "")
                        for t_name, t_data in themes.items():
                            if context_heading == t_name or context_heading in t_data.get("sub_themes", []):
                                parent_theme = t_name
                                parent_theme_color = t_data.get("color", "default")
                                break
                    
                    sys.stdout.buffer.write(f"Splitting: {title_words}\n".encode('utf-8'))
                    try:
                        # Pass clean_title to the LLM, but maintain context if possible by printing the full title
                        subtasks = split_task(clean_title)
                        if subtasks:
                            block_id = node.get("id")
                            push_subtasks_to_notion(block_id, subtasks, parent_theme, parent_theme_color)

                    except Exception as e:
                        print(f"Failed to split: {e}")
            
            # 继续递归处理子节点
            if node.get("children"):
                _split_all(node["children"])

    _split_all(notion_tree)

def cmd_cycle(dry_run: bool = False, skip_split: bool = False):
    """Run the full 4-phase processing cycle (format → wbs → split → enrich)."""
    from pipeline.runner import CycleRunner
    CycleRunner(dry_run=dry_run, skip_split=skip_split).run()


def cmd_poll():
    """Start polling loop"""
    print(f"Starting polling loop. Interval: {POLL_INTERVAL_SECONDS}s")
    try:
        while True:
            cmd_sync()
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nPolling stopped.")

def cmd_timeliner():
    """Run TIMELINER page sync and update"""
    from timeliner_sync import sync_timeliner
    sync_timeliner()

def cmd_timeliner_diff():
    """Print git-diff style timeline date changes"""
    from timeliner_diff import print_date_diff_all
    print_date_diff_all()

def cmd_focus(move_to: int = None):
    """显示编号任务列表或移动焦点 emoji"""
    import sys
    from focus_tracker import (
        list_focusable_tasks, find_focus_task,
        move_focus_emoji, track_focus, load_focus_log, save_focus_log,
        record_focus_event, FOCUS_EMOJI
    )

    notion_tree = fetch_and_build_task_tree()
    if not notion_tree:
        print("No tasks found in Notion.")
        return

    tasks = list_focusable_tasks(notion_tree)

    if move_to is not None:
        # 移动焦点到指定编号
        target = next((t for t in tasks if t["index"] == move_to), None)
        if not target:
            print(f"错误: 编号 {move_to} 不存在。有效范围: 1-{len(tasks)}")
            return

        focus_info = find_focus_task(notion_tree)
        if focus_info:
            if focus_info["block_id"] == target["block_id"]:
                sys.stdout.buffer.write(f"💪🏿💪🏿💪🏿 已经在该任务上: {target['title']}\n".encode('utf-8'))
                return
            # 记录旧焦点结束 + 新焦点开始
            log = load_focus_log()
            log = record_focus_event(log, focus_info["block_id"], focus_info["title"], "end")
            log = record_focus_event(log, target["block_id"], target["title"], "start")
            save_focus_log(log)
            # 在 Notion 中移动 emoji
            move_focus_emoji(focus_info["block_id"], target["block_id"])
            sys.stdout.buffer.write(f"✅ 焦点已移动到 [{move_to}] {target['title']}\n".encode('utf-8'))
        else:
            # 当前没有焦点，直接放到目标任务
            from focus_tracker import _append_focus_to_block
            _append_focus_to_block(target["block_id"])
            log = load_focus_log()
            log = record_focus_event(log, target["block_id"], target["title"], "start")
            save_focus_log(log)
            sys.stdout.buffer.write(f"✅ 焦点已设置到 [{move_to}] {target['title']}\n".encode('utf-8'))
        return

    # 默认：显示编号任务列表
    sys.stdout.buffer.write(f"\n📋 Task List ({FOCUS_EMOJI} = current focus)\n".encode('utf-8'))
    sys.stdout.buffer.write("─" .encode('utf-8') * 50 + b"\n")

    for t in tasks:
        marker = f" {FOCUS_EMOJI}" if t["has_focus"] else ""
        line = f"  {t['index']:3d}. {t['title']}{marker}\n"
        sys.stdout.buffer.write(line.encode('utf-8'))

    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.write("💡 Usage: python main.py focus --move <N>\n".encode('utf-8'))
    sys.stdout.buffer.write("   Example: python main.py focus --move 4\n".encode('utf-8'))


def cmd_track():
    """追踪当前焦点并更新 live今目 Dashboard"""
    import sys
    from focus_tracker import track_focus, FOCUS_EMOJI
    from dashboard import write_dashboard
    from config import LIVETODAY_PAGE_ID, DFORGE_LINESV2_PAGE_ID

    print("Fetching tasks from Notion...")
    notion_tree = fetch_and_build_task_tree()
    if not notion_tree:
        print("No tasks found in Notion.")
        return

    # 追踪焦点变化
    current_focus = track_focus(notion_tree, DFORGE_LINESV2_PAGE_ID)
    if current_focus:
        sys.stdout.buffer.write(f"🎯 当前焦点: {current_focus['title']}\n".encode('utf-8'))
        sys.stdout.buffer.write(f"   开始时间: {current_focus['started_at']}\n".encode('utf-8'))
    else:
        sys.stdout.buffer.write(f"⚠️ 未找到 {FOCUS_EMOJI} 标记的任务\n".encode('utf-8'))

    # 更新 live今目 Dashboard
    print("Updating live今目 dashboard...")
    raw_cfg = load_config()
    structured_cfg = structure_yonctask_config(raw_cfg)
    flat_state = flatten_tree(notion_tree)
    # 合并本地状态中的 tags 信息
    working_state = load_state(STATE_FILE)
    merged = merge_states(notion_tree, working_state)

    block_count = write_dashboard(LIVETODAY_PAGE_ID, merged, structured_cfg)
    print(f"Dashboard updated: {block_count} blocks written to live今目 page.")
    print("Track complete.")

def main():
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="Notion Task Management System")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    subparsers.add_parser("sync", help="Pull Notion → update JSON → push back")
    subparsers.add_parser("push-sync", help="Pull Notion → update JSON → rule-correct tags (Theme/WBS) → push without LLM")
    subparsers.add_parser("tag", help="Run emoji tagging pipeline")
    subparsers.add_parser("split", help="Run task decomposition pipeline")
    subparsers.add_parser("poll", help="Start polling loop")
    subparsers.add_parser("show-config", help="Print parsed YoncTask_config")
    subparsers.add_parser("timeliner", help="Sync TIMELINER page with progress from task tree")
    subparsers.add_parser("timeliner-diff", help="Show git-diff style date change history")
    focus_parser = subparsers.add_parser("focus", help="Show task list with focus position / move focus")
    focus_parser.add_argument("--move", type=int, default=None, help="Move focus to task number N")
    subparsers.add_parser("track", help="Track focus + update live今目 dashboard")
    subparsers.add_parser("reparent-dry", help="Dry-run: show what reparent would do without modifying Notion")
    cycle_parser = subparsers.add_parser(
        "cycle",
        help="Run full 4-phase cycle: format-check → WBS tag → split → enrich → push"
    )
    cycle_parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and process without writing anything to Notion or disk"
    )
    cycle_parser.add_argument(
        "--no-split", action="store_true",
        help="Skip Phase 3 interactive task splitting"
    )
    
    args = parser.parse_args()
    
    if args.command == "sync":
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
    elif args.command == "reparent-dry":
        cmd_reparent_dry()
    elif args.command == "cycle":
        cmd_cycle(dry_run=args.dry_run, skip_split=args.no_split)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
