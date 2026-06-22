import json
import flow_pipeline
from state_manager import merge_states, flatten_tree
from task_reader import fetch_and_build_task_tree
from sync_engine import sync_from_notion

print("Fetching tree...")
tree = fetch_and_build_task_tree()
print("Merging states...")
state = merge_states(tree, sync_from_notion(flatten_tree(tree)))

target = None
for t in state:
    if "SolarMan 控制面板" in t.get("title", ""):
        target = t
        break

print("Target found:", target is not None)

if target:
    theme_text = flow_pipeline._normalize_scope_text(flow_pipeline._pick_theme_key(target))
    title_text = flow_pipeline._normalize_scope_text(" ".join([
        str(target.get("title", "")), 
        str(target.get("original_notion_title", "")), 
        str(target.get("context_heading", ""))
    ]))
    
    print("Theme:", theme_text.encode("ascii", "ignore").decode())
    print("Title:", title_text.encode("ascii", "ignore").decode())
    
    print("Fetching timeliner...")
    entries = flow_pipeline.fetch_and_parse_timeliner()
    for e in entries:
        t_anchor = flow_pipeline._normalize_scope_text(flow_pipeline._timeliner_entry_theme_anchor(e))
        t_keys = flow_pipeline._timeliner_entry_title_match_keys(e)
        if "solarman" in t_anchor or "apparatus" in str(t_keys):
            print("Checking entry:")
            print("  Anchor:", t_anchor)
            print("  Keys:", t_keys)
            
            if t_anchor in theme_text and any(k in title_text for k in t_keys):
                print("  => MATCHED!")
            else:
                print("  => NOT MATCHED")
