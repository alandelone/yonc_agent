import json
import os
from typing import List, Dict, Any

STATE_FILE = "tasklist_state.json"
CURRENT_STATE_FILE = "current_state.json"

def flatten_tree(tree: List[Dict[str, Any]], parent_title_prefix: str = "", inherit_context: str = "") -> List[Dict[str, Any]]:
    """
    Flattens the hierarchical task tree into a flat list of objects.
    Appends parent title to child bullet items to form a combined title.
    """
    flat_list = []
    for node in tree:
        node_title = node["title"]
        # If it's a child (has a prefix), prepend the prefix
        combined_title = f"{parent_title_prefix} {node_title}".strip()
        
        current_context = node.get("context_heading", "") or inherit_context
        
        # Create a deep copy of the node properties
        flat_node = {
            "id": node["id"],
            "notion_block_id": node["id"],
            "title": combined_title,
            "original_notion_title": node_title, # Keep track of the real Notion title
            "context_heading": current_context,
            "parent_id": node.get("parent_id"),
            "depth": node.get("depth", 0),
            "type": node.get("type", ""),
            "annotations": node.get("annotations", {}),
            # Default values for fields managed by LLM or User directly
            "tags": {},
            "status": "pending",
            "time_taken_h": None
        }
        flat_list.append(flat_node)
        
        # Recursively flatten children, passing down the combined title as prefix
        if "children" in node and node["children"]:
            flat_list.extend(flatten_tree(node["children"], parent_title_prefix=combined_title, inherit_context=current_context))
            
    return flat_list

def save_state(state: List[Dict[str, Any]], filename: str = STATE_FILE):
    """Write the flattened state to a JSON file."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def load_state(filename: str = STATE_FILE) -> List[Dict[str, Any]]:
    """Read the flattened state from a JSON file."""
    if not os.path.exists(filename):
        return []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def merge_states(notion_tree: List[Dict[str, Any]], local_state: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Bidirectional merge logic.
    Updates the structure and titles from Notion, but preserves local LLM-applied tags, status, etc.
    """
    flat_notion = flatten_tree(notion_tree)
    local_dict = {item["notion_block_id"]: item for item in local_state}
    
    merged_state = []
    for notion_item in flat_notion:
        b_id = notion_item["notion_block_id"]
        if b_id in local_dict:
            # Preserve local state values that might have been updated by LLM or completion logic
            existing = local_dict[b_id]
            notion_item["tags"] = existing.get("tags", {})
            notion_item["status"] = existing.get("status", "pending")
            notion_item["time_taken_h"] = existing.get("time_taken_h")
            
        merged_state.append(notion_item)
        
    return merged_state
