# append_push.py
code = """
def push_root_order_to_notion(before_state: List[Dict[str, Any]], after_state: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    \"\"\"
    Physical root rank reordering: diffs roots order, deep clones the misplaced ones to the correct spot,
    then deletes the originals.
    \"\"\"
    from notion_client import append_children, delete_block

    def _task_id(task: Dict[str, Any]) -> str:
        return str(task.get("notion_block_id") or task.get("id") or "")

    def _build_root_sequence(state: List[Dict[str, Any]]) -> List[str]:
        task_by_id = {_task_id(t): t for t in state if _task_id(t)}
        seen = set()
        roots = []
        for task in state:
            current_id = _task_id(task)
            current = task
            visited = set()
            while current_id and current_id not in visited:
                visited.add(current_id)
                parent_id = str(current.get("parent_id") or "")
                parent = task_by_id.get(parent_id)
                if not parent:
                    break
                current = parent
                current_id = _task_id(parent)
            if current_id and current_id not in seen:
                seen.add(current_id)
                roots.append(current_id)
        return roots

    before_roots = _build_root_sequence(before_state)
    after_roots = _build_root_sequence(after_state)

    if before_roots == after_roots:
        return after_state

    import sys
    sys.stdout.buffer.write(f"Physical Root Rank Reordering: synchronizing order to Notion...\\n".encode('utf-8'))
    
    current_physical_order = list(before_roots)
    state = list(after_state)

    def _normalize_block_type(task: Dict[str, Any]) -> str:
        block_type = task.get("notion_type") or task.get("type") or ""
        if block_type == "todo":
            return "to_do"
        if block_type == "bullet":
            return "bulleted_list_item"
        return block_type

    def _build_block_payload(task: Dict[str, Any]) -> Dict[str, Any]:
        block_type = _normalize_block_type(task)
        if block_type == "numbered_list_item":
            block_type = "bulleted_list_item"
        annotations = task.get("annotations", {}) if isinstance(task.get("annotations"), dict) else {}
        color = annotations.get("color", "default")
        title = str(task.get("original_notion_title", task.get("title", "")) or "").strip()
        if not title:
            title = " "
        rich_text = [{
            "type": "text",
            "text": {"content": title}
        }]

        if block_type == "to_do":
            return {
                "object": "block",
                "type": "to_do",
                "to_do": {
                    "rich_text": rich_text,
                    "checked": bool(task.get("checked")),
                    "color": color
                }
            }
        base = {
            "object": "block",
            "type": block_type if block_type in ["bulleted_list_item", "numbered_list_item", "toggle", "heading_1", "heading_2", "heading_3", "quote"] else "paragraph"
        }
        b_type = base["type"]
        base[b_type] = {
            "rich_text": rich_text,
            "color": color
        }
        return base

    def _batch_clone_children(
        source_tasks: List[Dict[str, Any]],
        new_parent_id: str,
        children_map: Dict[str, List[Dict[str, Any]]],
        after_id: str = None,
        position: str = None
    ) -> List[Dict[str, Any]]:
        from notion_client import append_children
        # note: _normalize_uuid is defined at the module level in sync_engine.py
        safe_parent_id = _normalize_uuid(new_parent_id)
        payloads = [_build_block_payload(t) for t in source_tasks]

        append_res = append_children(safe_parent_id, payloads, after_id=after_id, position=position)
        results = append_res.get("results") or []
        if len(results) > len(source_tasks):
            results = results[:len(source_tasks)]
        new_ids = [str(r.get("id") or "") for r in results]
        
        missing = [i for i, nid in enumerate(new_ids) if not nid]
        if missing:
            raise RuntimeError(f"Missing IDs for cloned blocks at indices {missing}")

        cloned_flat: List[Dict[str, Any]] = []
        for source_task, new_id in zip(source_tasks, new_ids):
            source_id = _task_id(source_task)
            cloned_root = source_task.copy()
            cloned_root["id"] = new_id
            cloned_root["notion_block_id"] = new_id
            cloned_root["parent_id"] = new_parent_id
            cloned_flat.append(cloned_root)

            grandchildren = children_map.get(source_id, [])
            if grandchildren:
                cloned_flat.extend(
                    _batch_clone_children(grandchildren, new_id, children_map)
                )
        return cloned_flat

    def _collect_subtree_ids(root_id: str, children_map: Dict[str, List[Dict[str, Any]]]) -> set:
        ids = set()
        stack = [root_id]
        while stack:
            current = stack.pop()
            if current in ids:
                continue
            ids.add(current)
            for child in children_map.get(current, []):
                cid = _task_id(child)
                if cid:
                    stack.append(cid)
        return ids

    for i, target_root in enumerate(after_roots):
        if i < len(current_physical_order) and current_physical_order[i] == target_root:
            continue

        children_map = {}
        for task in state:
            tid = _task_id(task)
            pid = str(task.get("parent_id") or "")
            if pid and tid:
                children_map.setdefault(pid, []).append(task)
        
        task_by_id = {_task_id(t): t for t in state if _task_id(t)}
        target_task = task_by_id.get(target_root)
        if not target_task:
            continue
            
        parent_id = str(target_task.get("parent_id") or "")
        if not parent_id:
             from config import DFORGE_LINESV2_PAGE_ID
             parent_id = DFORGE_LINESV2_PAGE_ID
        
        old_id = target_root
        prev_id = after_roots[i-1] if i > 0 else None
        
        position = "start" if prev_id is None else None
        
        block_title_prt = str(target_task.get("original_notion_title", target_task.get("title", "")))[:20]
        sys.stdout.buffer.write(f"  -> Moving block '{block_title_prt}' to physical position {i}\\n".encode('utf-8'))
        
        try:
            cloned_flat = _batch_clone_children([target_task], parent_id, children_map, after_id=prev_id, position=position)
            new_id = cloned_flat[0]["id"]
            delete_block(_normalize_uuid(old_id))
            
            after_roots[i] = new_id
            
            if old_id in current_physical_order:
                current_physical_order.remove(old_id)
            current_physical_order.insert(i, new_id)
            
            old_subtree_ids = _collect_subtree_ids(old_id, children_map)
            
            insert_idx = next((idx for idx, t in enumerate(state) if _task_id(t) == old_id), len(state))
            remaining = [t for t in state if _task_id(t) not in old_subtree_ids]
            state = remaining[:insert_idx] + cloned_flat + remaining[insert_idx:]
        except Exception as e:
            sys.stdout.buffer.write(f"  -> Failed moving block '{block_title_prt}': {e}\\n".encode('utf-8'))

    sys.stdout.buffer.write(f"Physical Root Rank Reordering complete.\\n".encode('utf-8'))
    return state
"""

with open("c:\\Users\\Alandelone\\CodeSpace_Local\\yonc_agent\\sync_engine.py", "a", encoding="utf-8") as f:
    f.write("\n" + code + "\n")
