import os
import json
from typing import Dict, Any
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

TIMELINER_STATE_FILE = os.path.join(DATA_DIR, "timeliner_state.json")
TIMELINER_AUDIT_FILE = os.path.join(DATA_DIR, "timeliner_date_audit.jsonl")

def load_timeliner_state() -> Dict[str, Any]:
    """Load latest known settle dates per subtheme."""
    if not os.path.exists(TIMELINER_STATE_FILE):
        return {}
    try:
        with open(TIMELINER_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_timeliner_state(state: Dict[str, Any]) -> None:
    """Save latest known settle dates per subtheme."""
    with open(TIMELINER_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def get_extension_count(subtheme: str) -> int:
    """Read the audit log to determine how many times a subtheme's date was extended."""
    if not os.path.exists(TIMELINER_AUDIT_FILE):
        return 0
        
    count = 0
    with open(TIMELINER_AUDIT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("colour_subtheme") == subtheme and entry.get("field") == "settle_date":
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

def record_date_change(block_id: str, subtheme: str, old_date: str, new_date: str) -> int:
    """
    Append an audit log entry for a date change.
    Returns the new extension_count.
    """
    # Get current extension count before this change
    current_count = get_extension_count(subtheme)
    new_count = current_count + 1
    
    old_status = resolve_status_emoji(current_count)
    new_status = resolve_status_emoji(new_count)
    status_change = f"{old_status} \u2192 {new_status}"
    
    audit_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "block_id": block_id,
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
