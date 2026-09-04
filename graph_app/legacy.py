"""Safe one-way importer for the existing JSON state and focus log."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import FocusSession, GraphNode
from .service import create_edge, create_node


def legacy_state_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "tasklist_state.json"


def import_legacy_state(session: Session, path: str | Path | None = None) -> dict[str, int]:
    source = Path(path or legacy_state_path())
    if not source.exists():
        return {"created": 0, "updated": 0, "skipped": 0}
    data = json.loads(source.read_text(encoding="utf-8"))
    by_legacy_id: dict[str, GraphNode] = {}
    created = updated = skipped = 0
    for item in data if isinstance(data, list) else []:
        legacy_id = str(item.get("notion_block_id") or item.get("id") or "")
        if not legacy_id:
            skipped += 1
            continue
        existing = session.scalar(select(GraphNode).where(GraphNode.notion_block_id == legacy_id))
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        lifecycle = "DONE" if item.get("checked") or str(item.get("status", "")).lower() in {"done", "completed"} else "TODO"
        values: dict[str, Any] = {
            "title": item.get("original_notion_title") or item.get("title") or "Untitled task",
            "kind": "TASK", "lifecycle": lifecycle, "notion_block_id": legacy_id,
            "wbs_level": item.get("wbs_level"), "origin": item.get("origin", "notion"),
            "tags": item.get("tags") or {}, "links": item.get("links") or [],
            "estimated_effort_hours": metrics.get("estimated_time_h"),
            "planned_end": item.get("timeliner_settle_date"), "deadline": item.get("deadline"),
            "remote_baseline": {"title": item.get("original_notion_title") or item.get("title"), "checked": bool(item.get("checked")), "tags": item.get("tags") or {}},
        }
        if existing:
            for key, value in values.items():
                if key != "lifecycle" or existing.lifecycle not in {"CANCELLED", "SUPERSEDED"}:
                    setattr(existing, key, value)
            by_legacy_id[legacy_id] = existing
            updated += 1
        else:
            node = create_node(session, values, record=False)
            node.observed_work_seconds = _legacy_seconds(metrics.get("timetaken"))
            by_legacy_id[legacy_id] = node
            created += 1
    session.flush()
    for item in data if isinstance(data, list) else []:
        child_id, parent_legacy_id = str(item.get("notion_block_id") or item.get("id") or ""), str(item.get("parent_id") or "")
        if child_id in by_legacy_id and parent_legacy_id in by_legacy_id:
            child = by_legacy_id[child_id]
            child.parent_id = by_legacy_id[parent_legacy_id].id
            create_edge(session, {"source_id": child.parent_id, "target_id": child.id, "relation": "contains"}, record=False)
    return {"created": created, "updated": updated, "skipped": skipped}


def _legacy_seconds(periods: Any) -> int:
    total = 0
    for item in periods if isinstance(periods, list) else []:
        if not isinstance(item, dict) or not item.get("start") or not item.get("end"):
            continue
        try:
            from datetime import datetime
            total += max(0, int((datetime.fromisoformat(item["end"].replace("Z", "+00:00")) - datetime.fromisoformat(item["start"].replace("Z", "+00:00"))).total_seconds()))
        except ValueError:
            continue
    return total
