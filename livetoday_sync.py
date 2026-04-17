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
    for block in blocks:
        block_type = block.get("type", "")
        if block_type != "to_do":
            continue
            
        type_content = block.get(block_type, {})
        is_checked_on_dashboard = type_content.get("checked", False)
        
        # We only care about pushing checks. (Un-checking from dashboard is ignored for safety).
        if not is_checked_on_dashboard:
            continue
            
        # Parse the [N] out of the title to map back to original block id
        rich_text = type_content.get("rich_text", [])
        if not rich_text:
            continue
            
        # Extract plain text
        text = "".join(t.get("text", {}).get("content", "") for t in rich_text).strip()
        idx_match = re.match(r"^\[(\d+)\]\s*(.*)", text)
        if not idx_match:
            continue
            
        task_num_str = idx_match.group(1)
        original_block_id = livetoday_map.get(task_num_str)
        
        if original_block_id:
            local_task = local_status_map.get(original_block_id)
            if not local_task:
                continue
                
            # Check if it was already marked done locally (to avoid redundant API calls)
            status = local_task.get("status", "todo")
            is_done_locally = status in ("done", "completed") or bool(local_task.get("checked"))
            
            if not is_done_locally:
                # Issue update to the LIVEV2 Notion block
                print(f"Detected newly checked task on LIVETODAY for [{task_num_str}]. Syncing back to LIVEV2...")
                try:
                    # Update block. Notion permits changing simple block types (e.g. bulleted -> to_do) during update_block,
                    # so passing `to_do: {checked: True}` acts as both a type coercion and a status update.
                    update_block(original_block_id, {"to_do": {"checked": True}})
                    updated_count += 1
                except Exception as e:
                    print(f"Failed to push check state to LIVEV2 block {original_block_id}: {e}")

    if updated_count > 0:
        print(f"Successfully synced {updated_count} checks from LIVETODAY to LIVEV2.")
