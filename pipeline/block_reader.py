"""
pipeline/block_reader.py — Rich context accessor for a single Notion block.

BlockReader answers questions like:
  - Where is this block in the sibling list?
  - What are its ancestors / descendants?
  - What is the cleaned description?
  - What content is inside a toggle or linked page?
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


class BlockReader:
    """
    Stateless helper that extracts structural and textual context
    for a single block node given the flat task list (task_by_id map).
    """

    def __init__(self, flat_state: List[Dict[str, Any]], task_by_id: Dict[str, Dict[str, Any]]):
        self._flat_state = flat_state
        self._task_by_id = task_by_id

        # Build parent_id → ordered children list once
        self._children_map: Dict[str, List[Dict[str, Any]]] = {}
        for t in flat_state:
            pid = str(t.get("parent_id") or "")
            if pid:
                self._children_map.setdefault(pid, []).append(t)

    # ── Location ──────────────────────────────────────────────────────────────

    def location_in_list(self, node: Dict[str, Any]) -> Tuple[int, int]:
        """
        Return (1-based index, total siblings) for node among its siblings
        (blocks that share the same parent_id).
        """
        node_id = self._id(node)
        pid = str(node.get("parent_id") or "")
        siblings = self._children_map.get(pid, [])
        for i, sib in enumerate(siblings, start=1):
            if self._id(sib) == node_id:
                return (i, len(siblings))
        # Fallback: not found in map (root-level node)
        root_siblings = [t for t in self._flat_state if not t.get("parent_id")]
        for i, sib in enumerate(root_siblings, start=1):
            if self._id(sib) == node_id:
                return (i, len(root_siblings))
        return (0, 0)

    # ── Ancestors / Descendants ───────────────────────────────────────────────

    def ancestors(self, node: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Return ordered ancestor chain [direct_parent, grandparent, ..., root].
        Stops if a cycle or missing node is detected.
        """
        chain: List[Dict[str, Any]] = []
        seen: set = set()
        current = node
        while True:
            pid = str(current.get("parent_id") or "")
            if not pid or pid in seen:
                break
            seen.add(pid)
            parent = self._task_by_id.get(pid)
            if not parent:
                break
            chain.append(parent)
            current = parent
        return chain

    def direct_children(self, node: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return immediate children of node."""
        nid = self._id(node)
        return list(self._children_map.get(nid, []))

    def all_descendants(self, node: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return all descendants (BFS), excluding node itself."""
        result: List[Dict[str, Any]] = []
        queue = list(self.direct_children(node))
        seen: set = set()
        while queue:
            child = queue.pop(0)
            cid = self._id(child)
            if cid in seen:
                continue
            seen.add(cid)
            result.append(child)
            queue.extend(self.direct_children(child))
        return result

    def is_leaf(self, node: Dict[str, Any]) -> bool:
        """True if node has no children."""
        return len(self.direct_children(node)) == 0

    # ── Content ───────────────────────────────────────────────────────────────

    def description(self, node: Dict[str, Any]) -> str:
        """
        Return the cleaned plain text title of node.
        Uses original_notion_title if available, else title.
        """
        raw = str(node.get("original_notion_title") or node.get("title") or "").strip()
        return raw

    def toggle_content(self, node: Dict[str, Any], max_chars: int = 500) -> Optional[str]:
        """
        If node is a toggle block, fetch its children from Notion and return
        a concatenated plain-text summary (capped at max_chars).
        Returns None if node is not a toggle or fetch fails.
        """
        block_type = node.get("notion_type") or node.get("type") or ""
        if block_type != "toggle":
            return None

        block_id = self._id(node)
        if not block_id:
            return None

        try:
            from notion_client import get_page_blocks
            from config_reader import parse_rich_text

            children_blocks = get_page_blocks(block_id)
            parts: List[str] = []
            for blk in children_blocks:
                bt = blk.get("type", "")
                if bt in ["paragraph", "bulleted_list_item", "numbered_list_item", "to_do", "toggle"]:
                    rt = blk.get(bt, {}).get("rich_text", [])
                    text = parse_rich_text(rt).strip()
                    if text:
                        parts.append(text)

            combined = " | ".join(parts)
            if len(combined) > max_chars:
                combined = combined[:max_chars] + "…"
            return combined if combined else None
        except Exception as e:
            print(f"[BlockReader] toggle_content fetch failed for {block_id}: {e}")
            return None

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convenience: return a dict with all key context info.
        Useful for passing to LLM prompts.
        """
        idx, total = self.location_in_list(node)
        ancs = self.ancestors(node)
        children = self.direct_children(node)
        toggle_text = self.toggle_content(node) if (node.get("type") == "toggle") else None

        return {
            "block_id": self._id(node),
            "title": self.description(node),
            "type": node.get("notion_type") or node.get("type"),
            "wbs_level": node.get("wbs_level"),
            "depth": node.get("depth"),
            "sibling_index": idx,
            "sibling_total": total,
            "parent_titles": [self.description(a) for a in ancs],
            "child_count": len(children),
            "child_titles": [self.description(c) for c in children[:5]],  # cap for LLM brevity
            "toggle_summary": toggle_text,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _id(node: Dict[str, Any]) -> str:
        return str(node.get("notion_block_id") or node.get("id") or "")
