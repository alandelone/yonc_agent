import json
import time
from config_reader import load_config
from sync_engine import push_tags_to_notion
from dotenv import load_dotenv

load_dotenv()

def resolve_notion_inconsistencies():
    print("Loading Notion configuration...")
    cfg = load_config()
    
    print("Loading current state data...")
    with open("data/current_state.json", "r", encoding="utf-8") as f:
        state = json.load(f)
        
    print(f"Loaded {len(state)} tasks.")
    print("Bypassing the 'skip' logic to force all tasks to format correctly...")
    
    for task in state:
        if task.get("type") in ["todo", "bullet"]:
            task["has_tag_style"] = False
            task["synced_tags"] = False
            
    print("Pushing corrected tags to Notion. This might take a while depending on task volume...")
    
    # Run the sync engine
    push_tags_to_notion(state, cfg)
    
    print("\n✅ All tasks have been successfully reformatted and synced!")

if __name__ == "__main__":
    resolve_notion_inconsistencies()
