import json

# Simulated constants
DONE_MARK = "✅"
known_prefix_emojis = ["🚨", "🏭", "🟧", "🔶"]  # simplistic version

def process_task(task):
    block_type = task.get("type", "to_do")
    original_title = task.get("original_notion_title", "")
    tags = task.get("tags", {})
    wbs_level = task.get("wbs_level")
    checked = task.get("checked")
    is_generated = task.get("is_generated", False)
    generated_selection_processed = task.get("generated_selection_processed", False)
    
    # selection_mode logic
    _sibling_checked_count = 1 # assume
    selection_mode = (
        block_type == "to_do"
        and is_generated
        and not generated_selection_processed
        and _sibling_checked_count >= 1
    )
    
    needs_generated_prefix_restore = is_generated and not generated_selection_processed and "🤖💬🔜" not in original_title
    needs_generated_prefix_strip = is_generated and generated_selection_processed and "🤖💬🔜" in original_title
    
    print(f"Task: {task.get('title')}")
    print(f"is_generated: {is_generated}")
    print(f"generated_selection_processed: {generated_selection_processed}")
    print(f"needs_generated_prefix_strip: {needs_generated_prefix_strip}")
    
    if (
        is_generated
        and not False # is_pending_selection_change
        and not False
        and not False
        and not needs_generated_prefix_restore
        and not needs_generated_prefix_strip
        and not False
    ):
        print("-> BYPASSED!")
    else:
        print("-> NOT bypassed, will process styling.")

with open('data/tasklist_state.json', encoding='utf-8') as f:
    data = json.load(f)

for t in data:
    if '方法论证 Report' in t.get('title', ''):
        process_task(t)
