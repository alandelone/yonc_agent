from typing import Dict, List, Any
from notion_client import get_page_blocks
from config_reader import parse_rich_text
from config import TEST_MONTHLY_PAGE_ID

def build_task_tree(blocks: List[Dict[str, Any]], depth: int = 0, parent_id: str = None, inherit_context: str = "") -> List[Dict[str, Any]]:
    """
    Recursively builds an in-memory tree of tasks from Notion blocks.
    Captures block_id, plain_text, depth, children, annotations, and context heading.
    """
    task_tree = []
    current_context = inherit_context
    
    for block in blocks:
        block_id = block.get("id")
        block_type = block.get("type", "")
        
        # Standard blocks that contain text
        if block_type in ["bulleted_list_item", "numbered_list_item", "to_do", "toggle", "paragraph"]:
            type_content = block.get(block_type, {})
            rich_text = type_content.get("rich_text", [])
            plain_text = parse_rich_text(rich_text).strip()
            
            if not plain_text and not block.get("has_children"):
                # Skip perfectly empty leaf nodes
                continue
                
            if block_type == "paragraph":
                current_context = plain_text
            
            # Extract annotations from the first text segment (if available)
            annotations = {}
            if rich_text:
                annotations = rich_text[0].get("annotations", {})
                
            task_node = {
                "id": block_id,
                "title": plain_text,
                "context_heading": current_context if block_type != "paragraph" else "",
                "parent_id": parent_id,
                "depth": depth,
                "type": block_type,
                "annotations": annotations,
                "children": []
            }
            
            # Recurse if children were fetched
            if "children_blocks" in block:
                task_node["children"] = build_task_tree(
                    block["children_blocks"], 
                    depth=depth + 1, 
                    parent_id=block_id,
                    inherit_context=current_context
                )
                
            task_tree.append(task_node)
            
        elif "children_blocks" in block:
            # For structural blocks (e.g. columns) that wrap content, pass through
            # without increasing depth to find the actual list items
            task_tree.extend(build_task_tree(
                block["children_blocks"],
                depth=depth,
                parent_id=parent_id,
                inherit_context=current_context
            ))
            
    return task_tree

def fetch_and_build_task_tree() -> List[Dict[str, Any]]:
    """
    Fetches the main task page blocks and builds the hierarchical task tree.
    """
    blocks = get_page_blocks(TEST_MONTHLY_PAGE_ID)
    return build_task_tree(blocks)

if __name__ == "__main__":
    import json
    tree = fetch_and_build_task_tree()
    print(json.dumps(tree, indent=2, ensure_ascii=False))
