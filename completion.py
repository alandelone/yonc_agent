from typing import Dict, Any, List
from notion_client import update_block, replace_with_toggle

def format_done_text(rich_text: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Applies strikethrough and gray color to text. 
    Prepends '💯✅ ' to the first element.
    Appends ' `?h`' to the last element.
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
        if not content.startswith("💯✅"):
            first_item["text"]["content"] = f"💯✅ {content}"
            if "plain_text" in first_item:
                first_item["plain_text"] = f"💯✅ {first_item['plain_text']}"
                
    # Append time placeholder conceptually
    # Simple logic: just append the text if it's not there
    last_item = formatted[-1]
    if "text" in last_item and "content" in last_item["text"]:
        content = last_item["text"]["content"]
        if "?h" not in content:
            # Create a separate inline code block for the placeholder
            time_placeholder = {
                "type": "text",
                "text": {
                    "content": " ?h",
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
                "plain_text": " ?h",
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
    
    new_rich_text = format_done_text(rich_text)
    
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
    new_rich_text = format_done_text(rich_text)
    
    toggle_content = {
        "rich_text": new_rich_text,
        "color": "gray"
    }
    
    return replace_with_toggle(block_id, target_parent_id, toggle_content, children_blocks)
