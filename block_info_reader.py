import json
import re
from typing import Any, Dict, List, Tuple


def split_title_description(text: str) -> Tuple[str, str]:
    raw = str(text or "").strip()
    if ":" not in raw:
        return (raw, "")
    title, desc = raw.split(":", 1)
    return (title.strip(), desc.strip())


def build_state_indexes(tasks: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    task_by_id: Dict[str, Dict[str, Any]] = {}
    children_by_parent: Dict[str, List[Dict[str, Any]]] = {}

    for task in tasks:
        block_type = task.get("notion_type") or task.get("type")
        if task.get("is_content_block") and block_type != "quote":
            continue
        task_id = str(task.get("notion_block_id") or task.get("id") or "")
        if not task_id:
            continue
        task_by_id[task_id] = task
        parent_id = str(task.get("parent_id") or "")
        if parent_id:
            children_by_parent.setdefault(parent_id, []).append(task)

    return task_by_id, children_by_parent


def _normalize_text(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _truncate_words(text: str, max_words: int = 120) -> str:
    words = str(text or "").split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).strip() + " ..."


def _compact_sources(sources: List[Dict[str, Any]], max_chars: int) -> Tuple[List[Dict[str, Any]], bool]:
    total_chars = sum(int(src.get("char_count", 0)) for src in sources)
    if total_chars <= max_chars:
        return sources, False

    # Compact largest source first to reduce payload aggressively.
    ordered = sorted(sources, key=lambda s: int(s.get("char_count", 0)), reverse=True)
    compacted: List[Dict[str, Any]] = []
    remaining_budget = max_chars

    for src in ordered:
        content = str(src.get("content", ""))
        min_keep = 240
        budget_for_src = max(min_keep, remaining_budget // max(1, len(ordered)))
        shortened = content[:budget_for_src]
        summary = _truncate_words(shortened, max_words=80)
        compacted_src = dict(src)
        compacted_src["summary"] = summary
        compacted_src["content"] = shortened
        compacted_src["char_count"] = len(shortened)
        compacted.append(compacted_src)
        remaining_budget = max(0, remaining_budget - len(shortened))

    return compacted, True


def build_block_info(
    task: Dict[str, Any],
    task_by_id: Dict[str, Dict[str, Any]],
    children_by_parent: Dict[str, List[Dict[str, Any]]],
    max_chars: int = 5000,
) -> Dict[str, Any]:
    task_id = str(task.get("notion_block_id") or task.get("id") or "")
    original_title = str(task.get("original_notion_title", task.get("title", "")) or "")
    title, description = split_title_description(original_title)

    parent_blocks: List[Dict[str, Any]] = []
    seen: set[str] = set()
    parent_id = str(task.get("parent_id") or "")
    while parent_id and parent_id not in seen:
        seen.add(parent_id)
        parent = task_by_id.get(parent_id)
        if not parent:
            break
        parent_title, parent_desc = split_title_description(parent.get("original_notion_title", parent.get("title", "")))
        parent_blocks.append(
            {
                "id": parent_id,
                "title": _normalize_text(parent_title),
                "description": _normalize_text(parent_desc),
            }
        )
        parent_id = str(parent.get("parent_id") or "")

    parent_blocks.reverse()

    child_blocks: List[Dict[str, Any]] = []
    quote_blocks: List[Dict[str, Any]] = []
    for child in children_by_parent.get(task_id, []):
        child_type = child.get("notion_type") or child.get("type")
        if child_type == "quote":
            quote_title, quote_desc = split_title_description(child.get("original_notion_title", child.get("title", "")))
            quote_text = f"{quote_title}: {quote_desc}" if quote_desc else quote_title
            quote_blocks.append(
                {
                    "id": str(child.get("notion_block_id") or child.get("id") or ""),
                    "content": _normalize_text(quote_text),
                }
            )
        else:
            child_title, child_desc = split_title_description(child.get("original_notion_title", child.get("title", "")))
            child_blocks.append(
                {
                    "id": str(child.get("notion_block_id") or child.get("id") or ""),
                    "title": _normalize_text(child_title),
                    "description": _normalize_text(child_desc),
                    "type": child_type,
                    "checked": child.get("checked"),
                }
            )

    extra_info = {
        "is_toggle": (task.get("notion_type") == "toggle" or task.get("type") == "toggle"),
        "links": task.get("links", []) if isinstance(task.get("links"), list) else [],
        "mentions": task.get("mentions", []) if isinstance(task.get("mentions"), list) else [],
        "context_heading": _normalize_text(task.get("context_heading", "")),
    }

    sources: List[Dict[str, Any]] = []
    if parent_blocks:
        content = " > ".join([p["title"] for p in parent_blocks if p.get("title")])
        sources.append(
            {
                "source": "parent_chain",
                "location": "ancestor_blocks",
                "content": content,
                "char_count": len(content),
            }
        )

    if child_blocks:
        content = "; ".join([c["title"] for c in child_blocks if c.get("title")])
        sources.append(
            {
                "source": "children",
                "location": "direct_children",
                "content": content,
                "char_count": len(content),
            }
        )

    if description:
        sources.append(
            {
                "source": "description",
                "location": "current_block",
                "content": description,
                "char_count": len(description),
            }
        )

    if quote_blocks:
        content = "\n".join([q["content"] for q in quote_blocks])
        sources.append(
            {
                "source": "extra_information",
                "location": "quote_blocks",
                "content": content,
                "char_count": len(content),
            }
        )

    compacted_sources, was_compacted = _compact_sources(sources, max_chars=max_chars)

    return {
        "task_id": task_id,
        "title": _normalize_text(title),
        "description": _normalize_text(description),
        "parent_blocks": parent_blocks,
        "child_blocks": child_blocks,
        "extra_info": extra_info,
        "sources": compacted_sources,
        "compacted": was_compacted,
    }


def build_block_info_for_state(
    tasks: List[Dict[str, Any]],
    task: Dict[str, Any],
    max_chars: int = 5000,
) -> Dict[str, Any]:
    task_by_id, children_by_parent = build_state_indexes(tasks)
    return build_block_info(task, task_by_id, children_by_parent, max_chars=max_chars)


def build_split_context(
    tasks: List[Dict[str, Any]],
    task: Dict[str, Any],
    max_chars: int = 5000,
) -> str:
    info = build_block_info_for_state(tasks, task, max_chars=max_chars)
    return json.dumps(info, ensure_ascii=False)
