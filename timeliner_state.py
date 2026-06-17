import os
import json
from typing import Dict, Any, Optional, Iterable, Tuple
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

TIMELINER_STATE_FILE = os.path.join(DATA_DIR, "timeliner_state.json")
TIMELINER_AUDIT_FILE = os.path.join(DATA_DIR, "timeliner_date_audit.jsonl")
TASKLIST_STATE_FILE = os.path.join(DATA_DIR, "tasklist_state.json")


def _load_tasklist_titles() -> set[str]:
    if not os.path.exists(TASKLIST_STATE_FILE):
        return set()
    try:
        with open(TASKLIST_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return set()
        titles = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            label = str(item.get("theme_display_label", "") or "").strip()
            original = str(item.get("original_notion_title", "") or "").strip()
            title = f"{label} {original}".strip()
            if title:
                titles.add(title)
        return titles
    except Exception:
        return set()


def _canonicalize_title(
    raw_title: str,
    label: str,
    subtheme: str,
    tasklist_titles: set[str],
) -> str:
    title = str(raw_title or "").strip()
    if not title or not tasklist_titles:
        return title
    if title in tasklist_titles:
        return title

    prefix = (str(label or "").strip() + " ").lower()
    candidates = [t for t in tasklist_titles if t.lower().startswith(prefix)]
    if not candidates:
        return title

    needle = str(subtheme or "").strip().lower()
    if needle:
        contains = [t for t in candidates if needle in t.lower()]
        if len(contains) == 1:
            return contains[0]
        if len(contains) > 1:
            # Prefer the shortest candidate when multiple include the same needle.
            return sorted(contains, key=len)[0]

    return title

def build_scope_key(subtheme: str, project: str = "", subproject: str = "") -> str:
    """Build a stable scope key to disambiguate same subtheme across projects."""
    p = str(project or "").strip()
    sp = str(subproject or "").strip()
    st = str(subtheme or "").strip()
    if p or sp:
        return f"{p}::{sp}::{st}"
    return st


def load_timeliner_state() -> Dict[str, Any]:
    """Load latest known settle dates per subtheme."""
    if not os.path.exists(TIMELINER_STATE_FILE):
        return {}
    try:
        with open(TIMELINER_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {}

            # New structured format:
            # {
            #   "main_projects": {"<scope_key>": "YYYY-MM-DD", ...},
            #   "sub_projects": {"<scope_key>": "YYYY-MM-DD", ...}
            # }
            main_map = data.get("main_projects")
            sub_map = data.get("sub_projects")
            if isinstance(main_map, dict) or isinstance(sub_map, dict):
                merged: Dict[str, Any] = {}
                for group_map in [main_map, sub_map]:
                    if not isinstance(group_map, dict):
                        continue
                    for k, v in group_map.items():
                        # New entry shape:
                        # "<title>": {"scope_key": "...", "settle_date": "YYYY-MM-DD"}
                        if isinstance(v, dict):
                            scope_key = str(v.get("scope_key", "")).strip()
                            settle_date = v.get("settle_date")
                            if scope_key and settle_date:
                                merged[scope_key] = settle_date
                                continue
                            # Backward compatibility for object-valued entries missing scope_key.
                            if settle_date:
                                merged[str(k)] = settle_date
                                continue
                        # Older map shape:
                        # "<scope_key>": "YYYY-MM-DD"
                        merged[str(k)] = v
                return merged

            # Backward-compatible fallback: old flat map format.
            return data
    except json.JSONDecodeError:
        return {}

def save_timeliner_state(
    state: Dict[str, Any],
    priority_scope_order: Optional[Iterable[str]] = None,
) -> None:
    """
    Save latest known settle dates per subtheme.

    `priority_scope_order` can be provided as an ordered sequence of scope keys.
    Priority is calculated separately for `main_projects` and `sub_projects`.
    """
    main_projects: Dict[str, Any] = {}
    sub_projects: Dict[str, Any] = {}
    tasklist_titles = _load_tasklist_titles()
    priority_order = [str(x or "").strip() for x in (priority_scope_order or []) if str(x or "").strip()]
    if not priority_order:
        priority_order = [str(k or "").strip() for k in (state or {}).keys() if str(k or "").strip()]
    priority_index = {scope_key: i for i, scope_key in enumerate(priority_order)}
    main_priority = 1
    sub_priority = 1
    sorted_scope_keys = sorted(
        [str(k or "").strip() for k in (state or {}).keys() if str(k or "").strip()],
        key=lambda k: (priority_index.get(k, 10**9), k),
    )

    for key in sorted_scope_keys:
        settle_date = (state or {}).get(key)

        parts = key.split("::")
        if len(parts) >= 3:
            # scope key shape: "<project>::<subproject>::<subtheme>"
            project = parts[0].strip()
            subproject = parts[1].strip()
            subtheme = "::".join(parts[2:]).lstrip(":").strip()
            if subproject:
                title = f"{subproject} {subtheme}".strip()
                title = _canonicalize_title(title, subproject, subtheme, tasklist_titles)
            elif project:
                title = f"{project} {subtheme}".strip()
                title = _canonicalize_title(title, project, subtheme, tasklist_titles)
            else:
                title = subtheme or key
            entry = {
                "scope_key": key,
                "settle_date": settle_date,
            }
            if subproject:
                entry["priority"] = sub_priority
                sub_priority += 1
                sub_projects[title] = entry
            elif project:
                entry["priority"] = main_priority
                main_priority += 1
                main_projects[title] = entry
            else:
                # Unknown bucket: default to main for compatibility.
                entry["priority"] = main_priority
                main_priority += 1
                main_projects[title] = entry
        else:
            # Legacy key shape fallback.
            main_projects[key] = {
                "scope_key": key,
                "settle_date": settle_date,
                "priority": main_priority,
            }
            main_priority += 1

    payload = {
        "main_projects": main_projects,
        "sub_projects": sub_projects,
    }

    with open(TIMELINER_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def load_latest_audit_dates() -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Load latest settle_date values from audit history.

    Returns:
      - by_scope_key: {"<scope_key>": "YYYY-MM-DD"}
      - by_subtheme: {"<colour_subtheme>": "YYYY-MM-DD"}
    """
    by_scope_key: Dict[str, str] = {}
    by_subtheme: Dict[str, str] = {}

    if not os.path.exists(TIMELINER_AUDIT_FILE):
        return by_scope_key, by_subtheme

    with open(TIMELINER_AUDIT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("field") != "settle_date":
                continue

            new_value = str(entry.get("new_value", "") or "").strip()
            if not new_value:
                continue

            scope_key = str(entry.get("scope_key", "") or "").strip()
            if scope_key:
                by_scope_key[scope_key] = new_value

            subtheme = str(entry.get("colour_subtheme", "") or "").strip()
            if subtheme:
                by_subtheme[subtheme] = new_value

    return by_scope_key, by_subtheme

def get_extension_count(subtheme: str, project: str = "", subproject: str = "") -> int:
    """Read the audit log to determine how many times a subtheme's date was extended."""
    if not os.path.exists(TIMELINER_AUDIT_FILE):
        return 0

    scope_key = build_scope_key(subtheme, project, subproject)
    count = 0
    with open(TIMELINER_AUDIT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                same_scope = (
                    entry.get("scope_key") == scope_key
                    or (
                        not entry.get("scope_key")
                        and entry.get("colour_subtheme") == subtheme
                    )
                )
                if same_scope and entry.get("field") == "settle_date":
                    # Only extensions count (old < new practically, but we just count any change for simplicity)
                    count = entry.get("extension_count", count)
            except json.JSONDecodeError:
                continue
                
    return count

def resolve_status_emoji(extension_count: int) -> str:
    """0 -> 🟢, 1-2 -> 🔴, >2 -> 🔥"""
    if extension_count == 0:
        return "🟢"
    elif 1 <= extension_count <= 2:
        return "🔴"
    else:
        return "🔥"

def record_date_change(
    block_id: str,
    subtheme: str,
    old_date: str,
    new_date: str,
    project: str = "",
    subproject: str = "",
) -> int:
    """
    Append an audit log entry for a date change.
    Returns the new extension_count.
    """
    # Get current extension count before this change
    scope_key = build_scope_key(subtheme, project, subproject)
    current_count = get_extension_count(subtheme, project=project, subproject=subproject)
    new_count = current_count + 1
    
    old_status = resolve_status_emoji(current_count)
    new_status = resolve_status_emoji(new_count)
    status_change = f"{old_status} \u2192 {new_status}"
    
    audit_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "block_id": block_id,
        "project": str(project or "").strip(),
        "subproject": str(subproject or "").strip(),
        "scope_key": scope_key,
        "colour_subtheme": subtheme,
        "field": "settle_date",
        "old_value": old_date,
        "new_value": new_date,
        "extension_count": new_count,
        "status_change": status_change
    }
    
    with open(TIMELINER_AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(audit_entry, ensure_ascii=False) + "\n")
        
    return new_count
