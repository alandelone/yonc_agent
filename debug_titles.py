import sys
sys.stdout.reconfigure(encoding='utf-8')

from state_manager import load_state, STATE_FILE
flat_tasks = load_state(STATE_FILE)

print("=== Task Titles from LINEV2 ===")
for t in flat_tasks:
    title = str(t.get("original_notion_title", ""))
    if not title:
        title = str(t.get("title", ""))
    
    if "solarman" in title.lower() or "thesis" in title.lower() or "logic" in title.lower():
        print(f"- {title}")
