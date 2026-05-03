import os
import json
from collections import defaultdict
from typing import List, Dict, Any
from timeliner_state import TIMELINER_AUDIT_FILE
import sys

def parse_audit_log() -> List[Dict[str, Any]]:
    """Parse audit log JSONL file."""
    if not os.path.exists(TIMELINER_AUDIT_FILE):
        return []
    entries = []
    with open(TIMELINER_AUDIT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries

def format_date_diff(subtheme: str = None) -> str:
    """Read audit log and optionally filter by subtheme, return formatted diff text."""
    entries = parse_audit_log()
    if not entries:
        return "No date audit history found.\n"
        
    if subtheme:
        entries = [e for e in entries if e.get("colour_subtheme") == subtheme]
        
    if not entries:
        return f"No date audit history found for subtheme: {subtheme}\n"
        
    output = []
    for entry in entries:
        timestamp = entry.get("timestamp", "Unknown")
        # take just the date part of ISO timestamp
        date_str = timestamp.split("T")[0]
        project = str(entry.get("project", "") or "").strip()
        subproject = str(entry.get("subproject", "") or "").strip()
        st = entry.get("colour_subtheme", "Unknown")
        scope_label = " / ".join([x for x in [project, subproject, st] if x]) or st
        old_v = entry.get("old_value", "Unknown")
        new_v = entry.get("new_value", "Unknown")
        ext_count = entry.get("extension_count", "?")
        status_change = entry.get("status_change", "? \u2192 ?")
        
        chunk = [
            f"[{date_str}] {scope_label}",
            f"  - Settle by: {old_v}",
            f"  + Settle by: {new_v}",
            f"  (Extension #{ext_count}: {status_change})\n"
        ]
        output.append("\n".join(chunk))
        
    return "\n".join(output)

def print_date_diff_all() -> None:
    """Print the overall git-diff style date history to standard output."""
    # reconfigure stdout encoding so unicode emojis display correctly on windows
    sys.stdout.reconfigure(encoding='utf-8')
    print(format_date_diff())
