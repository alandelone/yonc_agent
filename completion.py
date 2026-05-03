from datetime import datetime
from typing import Dict, Any, List, Optional
from notion_client import update_block, replace_with_toggle

DONE_PREFIX = "\U0001F4AF\u2705"

def _parse_iso_timestamp(raw: str) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    # Handle "Z" suffix from persisted UTC timestamps.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _render_hours_label(hours_taken: Optional[float]) -> str:
    if hours_taken is None or hours_taken < 0:
        return "?h"
    rounded = round(hours_taken, 1)
    if rounded.is_integer():
        return f"{int(rounded)}h"
    return f"{rounded}h"


def _compute_focus_hours_for_block(block_id: str) -> Optional[float]:
    # Local import avoids hard dependency for callers that only test text formatting.
    from focus_tracker import load_focus_log

    log = load_focus_log()
    history = log.get("history", [])

    total_seconds = 0.0
    for item in history:
        if item.get("block_id") != block_id:
            continue
        started_at = _parse_iso_timestamp(item.get("started_at", ""))
        ended_at = _parse_iso_timestamp(item.get("ended_at", ""))
        if started_at is None or ended_at is None:
            continue
        delta = (ended_at - started_at).total_seconds()
        if delta > 0:
            total_seconds += delta

    if total_seconds <= 0:
        return None
    return total_seconds / 3600.0


def format_done_text(rich_text: List[Dict[str, Any]], hours_taken: Optional[float] = None) -> List[Dict[str, Any]]:
    """
    Applies strikethrough and gray color to text.
    Prepends '\U0001F4AF\u2705 ' to the first element.
    Appends an inline-code duration (`?h` fallback or computed value).
    """
    if not rich_text:
        return []

    formatted = []

    # Deep copy elements to avoid mutating original state if cached
    for item in rich_text:
        new_item = item.copy()
        if "annotations" in new_item:
            new_item["annotations"] = new_item["annotations"].copy()
        else:
            new_item["annotations"] = {}

        new_item["annotations"]["strikethrough"] = True
        new_item["annotations"]["color"] = "gray"
        formatted.append(new_item)

    # Prepend icon
    first_item = formatted[0]
    if "text" in first_item and "content" in first_item["text"]:
        content = first_item["text"]["content"]
        if not content.startswith(DONE_PREFIX):
            first_item["text"]["content"] = f"{DONE_PREFIX} {content}"
            if "plain_text" in first_item:
                first_item["plain_text"] = f"{DONE_PREFIX} {first_item['plain_text']}"

    has_time_token = any(
        (
            item.get("type") == "text"
            and item.get("annotations", {}).get("code") is True
            and str(item.get("text", {}).get("content", "")).strip().endswith("h")
        )
        for item in formatted
    )
    if not has_time_token:
        hours_label = _render_hours_label(hours_taken)
        time_placeholder = {
            "type": "text",
            "text": {
                "content": f" {hours_label}",
                "link": None
            },
            "annotations": {
                "bold": False,
                "italic": False,
                "strikethrough": True,
                "underline": False,
                "code": True,
                "color": "gray"
            },
            "plain_text": f" {hours_label}",
            "href": None
        }
        formatted.append(time_placeholder)

    return formatted

def mark_block_done(block: Dict[str, Any]) -> Dict[str, Any]:
    """
    Updates a Notion block in-place to mark it as done 
    (applies formatting to its rich_text).
    """
    block_id = block["id"]
    block_type = block["type"]
    
    if block_type not in ["bulleted_list_item", "numbered_list_item", "to_do", "paragraph"]:
        return block
        
    type_content = block.get(block_type, {})
    rich_text = type_content.get("rich_text", [])
    
    hours_taken = _compute_focus_hours_for_block(block_id)
    new_rich_text = format_done_text(rich_text, hours_taken=hours_taken)
    
    payload = {
        block_type: {
            "rich_text": new_rich_text,
            "color": "gray"
        }
    }
    
    return update_block(block_id, payload)


def handle_parent_conversion(parent_block: Dict[str, Any], target_parent_id: str, children_blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    If a parent and all its subtasks are done, convert parent to a Toggle block.
    target_parent_id is the ID of the block that contains this parent_block.
    """
    block_id = parent_block["id"]
    block_type = parent_block["type"]
    
    type_content = parent_block.get(block_type, {})
    rich_text = type_content.get("rich_text", [])
    
    # Format the parent's text
    hours_taken = _compute_focus_hours_for_block(block_id)
    new_rich_text = format_done_text(rich_text, hours_taken=hours_taken)
    
    toggle_content = {
        "rich_text": new_rich_text,
        "color": "gray"
    }
    
    return replace_with_toggle(block_id, target_parent_id, toggle_content, children_blocks)
