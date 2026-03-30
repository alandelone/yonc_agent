import json
import os
from typing import List, Dict, Any

import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

STATE_FILE = os.path.join(DATA_DIR, "tasklist_state.json")
CURRENT_STATE_FILE = os.path.join(DATA_DIR, "current_state.json")

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
        block_type = node.get("type", "")
        type_map = {
            "to_do": "todo",
            "bulleted_list_item": "bullet",
            "numbered_list_item": "bullet",
            "toggle": "toggle",
        }
        task_type = type_map.get(block_type, block_type)
        
        # Create a deep copy of the node properties
        flat_node = {
            "id": node["id"],
            "notion_block_id": node["id"],
            "title": combined_title,
            "original_notion_title": node_title, # Keep track of the real Notion title
            "context_heading": current_context,
            "parent_id": node.get("parent_id"),
            "depth": node.get("depth", 0),
            "wbs_level": None,
            "type": task_type,
            "notion_type": block_type,
            "annotations": node.get("annotations", {}),
            "checked": node.get("checked"),
            "has_tag_style": node.get("has_tag_style", False),
            "created_by_id": node.get("created_by_id", ""),
            "last_edited_by_id": node.get("last_edited_by_id", ""),
            "is_generated": node.get("is_generated", False),
            "origin": node.get("origin", "human"),
            # Default values for fields managed by LLM or User directly
            "tags": {},
            "status": "todo",
            "metrics": {
                "estimated_time_h": None,
                "actual_time_taken_h": None,
                "interruption_count": 0,
            }
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
            raw = json.load(f)
            return [upgrade_task_schema(item) for item in raw]
    except json.JSONDecodeError:
        return []

def upgrade_task_schema(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upgrades legacy task schema to the current format while preserving data.
    """
    upgraded = item.copy()

    type_map = {
        "to_do": "todo",
        "bulleted_list_item": "bullet",
        "numbered_list_item": "bullet",
        "toggle": "toggle",
    }

    # Type migration
    existing_type = upgraded.get("type")
    if existing_type in type_map:
        upgraded["notion_type"] = existing_type
        upgraded["type"] = type_map[existing_type]
    elif "notion_type" not in upgraded:
        upgraded["notion_type"] = None

    # Status migration
    if upgraded.get("status") == "pending":
        upgraded["status"] = "todo"
    elif "status" not in upgraded:
        upgraded["status"] = "todo"

    # Metrics migration
    metrics = upgraded.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {
            "estimated_time_h": None,
            "actual_time_taken_h": None,
            "interruption_count": 0,
        }

    # Legacy time field mapping
    if "time_taken_h" in upgraded and metrics.get("actual_time_taken_h") is None:
        metrics["actual_time_taken_h"] = upgraded.get("time_taken_h")
    upgraded["metrics"] = metrics
    upgraded.pop("time_taken_h", None)

    # Ensure wbs_level key exists
    if "wbs_level" not in upgraded:
        upgraded["wbs_level"] = None
    if "checked" not in upgraded:
        upgraded["checked"] = None
    if "has_tag_style" not in upgraded:
        upgraded["has_tag_style"] = False
    if "created_by_id" not in upgraded:
        upgraded["created_by_id"] = ""
    if "last_edited_by_id" not in upgraded:
        upgraded["last_edited_by_id"] = ""
    if "is_generated" not in upgraded:
        upgraded["is_generated"] = False
    if "origin" not in upgraded:
        upgraded["origin"] = "human"

    return upgraded

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
            notion_item["status"] = existing.get("status", "todo")
            notion_item["metrics"] = existing.get("metrics", {
                "estimated_time_h": None,
                "actual_time_taken_h": None,
                "interruption_count": 0,
            })
            notion_item["wbs_level"] = existing.get("wbs_level")
            
        merged_state.append(notion_item)
        
    return merged_state
