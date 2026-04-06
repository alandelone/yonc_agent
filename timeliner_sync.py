import sys
from typing import List, Dict, Any, Tuple
from collections import defaultdict
from itertools import chain

from timeliner_reader import fetch_and_parse_timeliner, TimelineEntry, TIMELINER_PAGE_ID
from timeliner_state import load_timeliner_state, save_timeliner_state, record_date_change, resolve_status_emoji, get_extension_count
from notion_client import update_block
from state_manager import load_state, STATE_FILE
from completion import DONE_PREFIX

def calculate_progress_by_subtheme(flat_tasks: List[Dict[str, Any]]) -> Dict[str, Tuple[int, int]]:
    """
    Returns a dict mapping subtheme -> (completed_count, total_count).
    Matches task using the subtheme in 'Task Theme with colour'.
    """
    stats = defaultdict(lambda: [0, 0])  # [completed, total]
    
    for task in flat_tasks:
        if task.get("type", "") == "heading_2" or task.get("type", "") == "heading_3":
            continue
            
        tags = task.get("tags", {})
        theme_str = tags.get("Task Theme with colour", "")
        if not theme_str:
            continue
            
        # extract just the noun part loosely, e.g. "我流方矩 健身" -> could contain "健身"
        # We'll just map the whole theme string, later we do substring match with TimelineEntry.colour_subtheme
        
        # Determine completion.
        is_done = False
        if DONE_PREFIX in task.get("original_notion_title", "") or DONE_PREFIX in task.get("title", ""):
            is_done = True
        elif task.get("checked") is True or task.get("status") == "done" or task.get("status") == "completed":
            is_done = True
            
        # Add to matching timeline entries (sub-theme name)
        stats[theme_str][1] += 1
        if is_done:
            stats[theme_str][0] += 1
            
    # Convert list to tuple
    return {k: (v[0], v[1]) for k, v in stats.items()}

def get_percentage(subtheme: str, theme_stats: Dict[str, Tuple[int, int]]) -> int:
    """Find matching theme in stats and return percentage 0-100."""
    total_completed = 0
    total_tasks = 0
    
    for theme_str, (comp, tot) in theme_stats.items():
        if subtheme in theme_str:
            total_completed += comp
            total_tasks += tot
            
    if total_tasks == 0:
        return 0
    return int((total_completed / total_tasks) * 100)

def build_timeliner_rich_text(entry: TimelineEntry, new_percent: int, new_status_emoji: str) -> List[Dict[str, Any]]:
    """Build the Notion rich_text payload for a timeline entry block."""
    is_100 = new_percent == 100
    
    rt = []
    rt.append({
        "type": "text",
        "text": {"content": f"{new_status_emoji} "},
        "annotations": {"strikethrough": is_100}
    })
    
    rt.append({
        "type": "text",
        "text": {"content": f"**{entry.colour_subtheme}** "},
        "annotations": {"bold": True, "strikethrough": is_100}
    })
    
    rt.append({
        "type": "text",
        "text": {"content": "Takes "},
        "annotations": {"strikethrough": is_100}
    })
    
    rt.append({
        "type": "text",
        "text": {"content": "🏁dates h"},
        "annotations": {"code": True, "strikethrough": is_100}
    })
    
    time_str = f"{entry.time_expected_h} " if entry.time_expected_h is not None else " "
    rt.append({
        "type": "text",
        "text": {"content": time_str},
        "annotations": {"strikethrough": is_100}
    })
    
    # ||xx%
    percent_str = f"||{new_percent}% "
    if is_100:
        percent_str += "💯 "
        
    rt.append({
        "type": "text",
        "text": {"content": percent_str},
        "annotations": {"strikethrough": is_100}
    })
    
    date_str = entry.settle_date  # We will just write the ISO date back for simplicity
    rt.append({
        "type": "text",
        "text": {"content": f"Settle by {date_str}"},
        "annotations": {"strikethrough": is_100}
    })
    
    if entry.remaining_work_days is not None:
        rt.append({
            "type": "text",
            "text": {"content": f", but 🔜 {entry.remaining_work_days}"},
            "annotations": {"strikethrough": is_100}
        })
        
    return rt

def sync_timeliner() -> None:
    print("Fetching timeline entries from Notion...")
    entries = fetch_and_parse_timeliner()
    if not entries:
        print("No timeline entries found.")
        return
        
    print("Loading task tree state for progress calculation...")
    flat_tasks = load_state(STATE_FILE)
    theme_stats = calculate_progress_by_subtheme(flat_tasks)
    
    print("Loading timeliner date state...")
    saved_state = load_timeliner_state()
    
    updated_state = {}
    
    for entry in entries:
        changed = False
        st = entry.colour_subtheme
        new_date = entry.settle_date
        
        # 1. Date Audit & Status
        old_date = saved_state.get(st)
        if old_date and old_date != new_date:
            print(f"Date changed for {st}: {old_date} -> {new_date}")
            record_date_change(entry.block_id, st, old_date, new_date)
            changed = True
            
        updated_state[st] = new_date
        
        ext_count = get_extension_count(st)
        new_status_emoji = resolve_status_emoji(ext_count)
        if new_status_emoji != entry.status_emoji:
            changed = True
            
        # 2. Progress Calc
        new_percent = get_percentage(st, theme_stats)
        if new_percent != entry.percent:
            changed = True
            
        # 3. Push to Notion if anything changed, or just to align format
        # actually, always push if progress updated or status emoji differs
        if changed:
            print(f"Pushing updates for {st} (Percent: {new_percent}%, Status: {new_status_emoji})...")
            rt = build_timeliner_rich_text(entry, new_percent, new_status_emoji)
            try:
                # determine block type from Notion API, probably bulleted_list_item or paragraph
                # Notion API requires knowing the block type to update its rich text.
                # However we can try updating both or just rely on 'bulleted_list_item'.
                # Actually, our reader doesn't save the exact block type. We can just use the known structure.
                # Let's fetch the block first to know its type or just try.
                from notion_client import BASE_URL, NOTION_HEADERS
                import requests
                
                resp = requests.get(f"{BASE_URL}/blocks/{entry.block_id}", headers=NOTION_HEADERS)
                resp.raise_for_status()
                b_type = resp.json().get("type")
                
                payload = {
                    b_type: {"rich_text": rt}
                }
                update_block(entry.block_id, payload)
            except Exception as e:
                print(f"Failed to update block {entry.block_id}: {e}")
                
    save_timeliner_state(updated_state)
    print("TIMELINER sync complete.")
