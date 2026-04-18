"""
Bi-directional sync module for tracking checkbox states on the LIVETODAY page
and flushing those checks back to the main LIVEV2 structure.
"""
import os
import json
import re
from typing import Dict, Any

from notion_client import get_page_blocks, update_block
from state_manager import load_state, STATE_FILE
from config import LIVETODAY_PAGE_ID

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MAP_FILE = os.path.join(DATA_DIR, "livetoday_map.json")
DASH_CHECKED_FILE = os.path.join(DATA_DIR, "dash_checked_today.json")

from datetime import date
from typing import Dict, Any, Set

def get_dash_checked_today() -> Set[str]:
    """Returns a set of block_ids that were checked on the dashboard today."""
    if not os.path.exists(DASH_CHECKED_FILE):
        return set()
    try:
        with open(DASH_CHECKED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return set()
        
    today_str = date.today().isoformat()
    return {bid for bid, d in data.items() if d == today_str}

def save_dash_checked_today(block_ids: Set[str]):
    today_str = date.today().isoformat()
    data = {bid: today_str for bid in block_ids}
    with open(DASH_CHECKED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def sync_livetoday_checks_to_livev2():
    """
    Reads the LIVETODAY page blocks, cross-references with livetoday_map.json,
    and if a task is newly checked on LIVETODAY, pushes that 'check' to the original LIVEV2 block.
    """
    if not os.path.exists(MAP_FILE):
        return
        
    try:
        with open(MAP_FILE, "r", encoding="utf-8") as f:
            livetoday_map = json.load(f)
    except Exception as e:
        print(f"Failed to load livetoday_map.json: {e}")
        return
        
    if not livetoday_map:
        return

    # Create a quick lookup for local state checking
    local_state = load_state(STATE_FILE)
    local_status_map: Dict[str, Dict[str, Any]] = {}
    for task in local_state:
        block_id = task.get("notion_block_id") or task.get("id")
        if block_id:
            local_status_map[block_id] = task

    print("Fetching LIVETODAY blocks to detect checked tasks...")
    try:
        blocks = get_page_blocks(LIVETODAY_PAGE_ID)
    except Exception as e:
        print(f"Failed to get LIVETODAY blocks: {e}")
        return

    updated_count = 0
    todays_checked = get_dash_checked_today()

    # Pass 1: Find all block IDs that are currently checked on the dashboard
    checked_on_dashboard = set()
    rendered_on_dashboard = set()

    def iterate_all_blocks(block_list):
        for b in block_list:
            yield b
            if "children_blocks" in b:
                yield from iterate_all_blocks(b["children_blocks"])

    for block in iterate_all_blocks(blocks):
        block_type = block.get("type", "")
        if block_type != "to_do":
            continue
            
        type_content = block.get(block_type, {})
        is_checked_on_dashboard = type_content.get("checked", False)
        
        # Parse the [N] out of the title to map back to original block id
        rich_text = type_content.get("rich_text", [])
        if not rich_text:
            continue
            
        text = "".join(t.get("text", {}).get("content", "") for t in rich_text).strip()
        idx_match = re.match(r"^\[(\d+)\]\s*(.*)", text)
        if not idx_match:
            continue
            
        task_num_str = idx_match.group(1)
        original_block_id = livetoday_map.get(task_num_str)
        
        if original_block_id:
            rendered_on_dashboard.add(original_block_id)
            if is_checked_on_dashboard:
                checked_on_dashboard.add(original_block_id)

    # Pass 2: Sync checks and handle unchecking
    for original_block_id in checked_on_dashboard:
        todays_checked.add(original_block_id)
        
        local_task = local_status_map.get(original_block_id)
        if not local_task:
            continue
            
        status = local_task.get("status", "todo")
        is_done_locally = status in ("done", "completed") or bool(local_task.get("checked"))
        
        if not is_done_locally:
            print(f"Detected newly checked task on LIVETODAY (id ending in ...{original_block_id[-6:]}). Syncing back to LIVEV2...")
            try:
                update_block(original_block_id, {"to_do": {"checked": True}})
                updated_count += 1
            except Exception as e:
                print(f"Failed to push check state to LIVEV2 block {original_block_id}: {e}")

    # For tasks that were checked earlier today, if they are rendered on dashboard but NONE of their instances are checked
    # it means the user explicitly unchecked them!
    for original_block_id in rendered_on_dashboard:
        if original_block_id in todays_checked and original_block_id not in checked_on_dashboard:
            todays_checked.remove(original_block_id)

    save_dash_checked_today(todays_checked)

    if updated_count > 0:
        print(f"Successfully synced {updated_count} checks from LIVETODAY to LIVEV2.")
