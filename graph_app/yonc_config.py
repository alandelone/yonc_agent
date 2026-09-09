"""Persistence and legacy-cache seeding for editable Yonc configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .models import YoncConfig, utcnow


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_CONFIG_PATH = PROJECT_ROOT / "data" / "tasklist.json"

NOTION_COLORS = {
    "default": "#64748b",
    "gray": "#64748b",
    "brown": "#a16207",
    "orange": "#ea580c",
    "yellow": "#ca8a04",
    "green": "#16a34a",
    "blue": "#2563eb",
    "purple": "#9333ea",
    "pink": "#db2777",
    "red": "#dc2626",
}


def _hex_color(value: Any) -> str:
    color = str(value or "default").lower().replace("_background", "")
    if color.startswith("#") and len(color) == 7:
        return color
    return NOTION_COLORS.get(color, NOTION_COLORS["default"])


def _seed_payload() -> dict[str, list[dict[str, Any]]]:
    if not LEGACY_CONFIG_PATH.exists():
        return {"themes": [], "modes": [], "task_types": []}
    try:
        raw = json.loads(LEGACY_CONFIG_PATH.read_text(encoding="utf-8"))
        from config_reader import structure_yonctask_config

        structured = structure_yonctask_config(raw)
    except (OSError, ValueError, TypeError, ImportError):
        return {"themes": [], "modes": [], "task_types": []}

    themes = [
        {
            "name": str(item.get("name") or name).strip(),
            "sub_themes": [str(value).strip() for value in item.get("sub_themes", []) if str(value).strip()],
            "color": _hex_color(item.get("color")),
        }
        for name, item in structured.get("themes", {}).items()
        if str(item.get("name") or name).strip()
    ]
    modes = [
        {
            "mode_name": str(item.get("mode_name") or "").strip(),
            "level": float(item.get("level") or 0),
            "description": str(item.get("description") or "").strip(),
            "color": _hex_color((item.get("annotations") or {}).get("color")),
        }
        for item in structured.get("modes", [])
        if str(item.get("mode_name") or "").strip()
    ]
    task_types = []
    for key, item in structured.get("task_types", {}).items():
        emoji, separator, fallback_name = str(key).partition("|")
        name = str(item.get("name") or fallback_name or key).strip()
        task_types.append({
            "emoji": emoji.strip() if separator else "",
            "name": name,
            "description": str(item.get("description") or "").strip(),
            "tag": str(item.get("tag") or "").strip(),
        })
    return {"themes": themes, "modes": modes, "task_types": task_types}


def get_yonc_config(session: Session) -> YoncConfig:
    config = session.get(YoncConfig, 1)
    if config is None:
        seed = _seed_payload()
        config = YoncConfig(id=1, **seed, source="yonc_config_cache", revision=1)
        session.add(config)
        session.flush()
    return config


def serialize_yonc_config(config: YoncConfig) -> dict[str, Any]:
    return {
        "themes": config.themes or [],
        "modes": config.modes or [],
        "task_types": config.task_types or [],
        "source": config.source,
        "revision": config.revision,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


def update_yonc_config(session: Session, config: YoncConfig, values: dict[str, Any]) -> YoncConfig:
    config.themes = values["themes"]
    config.modes = values["modes"]
    config.task_types = values["task_types"]
    config.source = "settings_ui"
    config.revision += 1
    config.updated_at = utcnow()
    session.flush()
    return config
