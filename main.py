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
    
    from sync_engine import push_tags_to_notion
    print("Pushing tags back to Notion...")
    push_tags_to_notion(enriched, config_dict)
    
    save_state(enriched, STATE_FILE)
    print("Tagging complete. LLM outputs have been pushed back to Notion.")

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
                if "✅" not in title_words and len(title_words) > 5:
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

def cmd_poll():
    """Start polling loop"""
    print(f"Starting polling loop. Interval: {POLL_INTERVAL_SECONDS}s")
    try:
        while True:
            cmd_sync()
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nPolling stopped.")

def main():
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="Notion Task Management System")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    subparsers.add_parser("sync", help="Pull Notion → update JSON → push back")
    subparsers.add_parser("tag", help="Run emoji tagging pipeline")
    subparsers.add_parser("split", help="Run task decomposition pipeline")
    subparsers.add_parser("poll", help="Start polling loop")
    subparsers.add_parser("show-config", help="Print parsed YoncTask_config")
    
    args = parser.parse_args()
    
    if args.command == "sync":
        cmd_sync()
    elif args.command == "tag":
        cmd_tag()
    elif args.command == "split":
        cmd_split()
    elif args.command == "poll":
        cmd_poll()
    elif args.command == "show-config":
        cmd_show_config()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
