import os
import json
import difflib
from datetime import datetime
from typing import Dict, List, Any, Optional

from config_reader import load_config, parse_daystyles, parse_daystyle_dicts
from notion_client import update_block, append_children, delete_block

CONFIG_FILE = "data/daystyle_config.json"
LOG_FILE = "data/daystyle_changes.log"
TODAY_STATUS_FILE = "../today_status.json"

def _atomic_write_json(file_path: str, data: Any) -> None:
    temp_path = file_path + ".tmp"
    dir_name = os.path.dirname(file_path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    if os.path.exists(file_path):
        os.replace(temp_path, file_path)
    else:
        os.rename(temp_path, file_path)

def read_daystyles() -> Dict[str, Any]:
    print("Reading DayStyle configuration from Notion...")
    raw_config = load_config()
    
    daystyle_blocks = raw_config.get("DayStyle", [])
    daystyle_dict_blocks = raw_config.get("DayStyle_Dict", [])
    
    parsed_styles = parse_daystyles(daystyle_blocks)
    parsed_dicts = parse_daystyle_dicts(daystyle_dict_blocks)
    
    result = {
        "daystyles": parsed_styles,
        "daystyle_dicts": parsed_dicts
    }
    
    _atomic_write_json(CONFIG_FILE, result)
    print(f"Saved parsed DayStyle configuration to {CONFIG_FILE}")
    return result

def write_today_daystyle(name: str) -> None:
    if not os.path.exists(CONFIG_FILE):
        read_daystyles()
        
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config_data = json.load(f)
        
    daystyles = config_data.get("daystyles", [])
    style_names = [ds["dayStyle"] for ds in daystyles]
    
    best_matches = difflib.get_close_matches(name, style_names, n=1, cutoff=0.5)
    if not best_matches:
        print(f"Error: DayStyle '{name}' not found. Available DayStyles: {', '.join(style_names)}")
        return
        
    matched_name = best_matches[0]
    matched_style = next(ds for ds in daystyles if ds["dayStyle"] == matched_name)
    
    clean_trajectory = [item["location"] for item in matched_style.get("trajectory", [])]
    clean_timeline = []
    for entry in matched_style.get("expectedStateTimeline", []):
        clean_entry = {
            "time": entry.get("time"),
            "activity": entry.get("activity"),
            "location": entry.get("location"),
            "energy": entry.get("energy"),
            "tasktype": entry.get("tasktype", [])
        }
        clean_timeline.append(clean_entry)
        
    day_mode = {
        "dayStyle": matched_style.get("dayStyle"),
        "description": matched_style.get("description"),
        "trajectory": clean_trajectory,
        "expectedStateTimeline": clean_timeline
    }
    
    status_data = {}
    if os.path.exists(TODAY_STATUS_FILE):
        try:
            with open(TODAY_STATUS_FILE, "r", encoding="utf-8") as f:
                status_data = json.load(f)
        except Exception:
            pass
            
    status_data["day_mode"] = day_mode
    status_data["mode_resolved"] = True
    _atomic_write_json(TODAY_STATUS_FILE, status_data)
    print(f"Successfully wrote DayStyle '{matched_name}' to {TODAY_STATUS_FILE}")

def _log_change(daystyle_name: str, field: str, block_id: str, before: Any, after: Any, action: str) -> None:
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "daystyle": daystyle_name,
        "field": field,
        "block_id": block_id,
        "before": before,
        "after": after,
        "action": action
    }
    dir_name = os.path.dirname(LOG_FILE)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

def edit_daystyle(name: str, field: str, value: str, index: Optional[int] = None, action: str = "update") -> None:
    if not os.path.exists(CONFIG_FILE):
        print("Error: daystyle_config.json not found. Please run 'daystyle read' first.")
        return
        
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config_data = json.load(f)
        
    daystyles = config_data.get("daystyles", [])
    style_names = [ds["dayStyle"] for ds in daystyles]
    
    best_matches = difflib.get_close_matches(name, style_names, n=1, cutoff=0.5)
    if not best_matches:
        print(f"Error: DayStyle '{name}' not found.")
        return
        
    matched_name = best_matches[0]
    matched_style = next(ds for ds in daystyles if ds["dayStyle"] == matched_name)
    parent_id = matched_style.get("block_id")
    
    if field == "description":
        if action != "update":
            print("Error: description field only supports 'update' action.")
            return
        before_val = matched_style.get("description", "")
        payload = {
            "toggle": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": matched_name},
                        "annotations": {"bold": True}
                    },
                    {
                        "type": "text",
                        "text": {"content": f" : {value}"}
                    }
                ]
            }
        }
        update_block(parent_id, payload)
        _log_change(matched_name, "description", parent_id, before_val, value, f"Updated description to: {value}")
        print(f"Successfully updated description for '{matched_name}' on Notion.")
        
    elif field == "trajectory":
        items = matched_style.get("trajectory", [])
        if action == "update":
            if index is None or index < 0 or index >= len(items):
                print(f"Error: index {index} out of range for trajectory.")
                return
            target_block = items[index]
            before_val = target_block["location"]
            payload = {
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": value}}]
                }
            }
            update_block(target_block["block_id"], payload)
            _log_change(matched_name, f"trajectory[{index}]", target_block["block_id"], before_val, value, f"Updated trajectory index {index} to {value}")
            print(f"Successfully updated trajectory index {index} to '{value}'.")
            
        elif action == "add":
            after_id = None
            if index is not None and index >= 0 and index < len(items):
                after_id = items[index]["block_id"]
            elif items:
                after_id = items[-1]["block_id"]
                
            new_block = {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": value}}]
                }
            }
            res = append_children(parent_id, [new_block], after_id=after_id)
            new_id = res.get("results", [{}])[0].get("id", "unknown")
            _log_change(matched_name, "trajectory", new_id, None, value, f"Added trajectory item '{value}'")
            print(f"Successfully added trajectory item '{value}'.")
            
        elif action == "delete":
            if index is None or index < 0 or index >= len(items):
                print(f"Error: index {index} out of range.")
                return
            target_block = items[index]
            delete_block(target_block["block_id"])
            _log_change(matched_name, f"trajectory[{index}]", target_block["block_id"], target_block["location"], None, f"Deleted trajectory item '{target_block['location']}'")
            print(f"Successfully deleted trajectory item '{target_block['location']}'.")
            
        elif action == "reorder":
            try:
                new_order = [int(i.strip()) for i in value.split(",")]
            except ValueError:
                print("Error: value must be a comma-separated list of integer indices.")
                return
            if len(new_order) != len(items) or set(new_order) != set(range(len(items))):
                print("Error: invalid reorder indices.")
                return
                
            before_vals = [it["location"] for it in items]
            after_vals = [items[idx]["location"] for idx in new_order]
            for i, idx in enumerate(new_order):
                target_block = items[i]
                new_val = items[idx]["location"]
                payload = {
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {"content": new_val}}]
                    }
                }
                update_block(target_block["block_id"], payload)
            _log_change(matched_name, "trajectory", parent_id, before_vals, after_vals, f"Reordered trajectory to indices: {value}")
            print(f"Successfully reordered trajectory items.")
            
    elif field == "expectedStateTimeline":
        items = matched_style.get("expectedStateTimeline", [])
        if action == "update":
            if index is None or index < 0 or index >= len(items):
                print(f"Error: index {index} out of range.")
                return
            target_block = items[index]
            before_val = target_block["raw"]
            payload = {
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": value}}]
                }
            }
            update_block(target_block["block_id"], payload)
            _log_change(matched_name, f"expectedStateTimeline[{index}]", target_block["block_id"], before_val, value, f"Updated timeline index {index} to {value}")
            print(f"Successfully updated timeline index {index}.")
            
        elif action == "add":
            after_id = None
            if index is not None and index >= 0 and index < len(items):
                after_id = items[index]["block_id"]
            elif items:
                after_id = items[-1]["block_id"]
                
            new_block = {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": value}}]
                }
            }
            res = append_children(parent_id, [new_block], after_id=after_id)
            new_id = res.get("results", [{}])[0].get("id", "unknown")
            _log_change(matched_name, "expectedStateTimeline", new_id, None, value, f"Added timeline item '{value}'")
            print(f"Successfully added timeline item.")
            
        elif action == "delete":
            if index is None or index < 0 or index >= len(items):
                print(f"Error: index {index} out of range.")
                return
            target_block = items[index]
            delete_block(target_block["block_id"])
            _log_change(matched_name, f"expectedStateTimeline[{index}]", target_block["block_id"], target_block["raw"], None, f"Deleted timeline item '{target_block['raw']}'")
            print(f"Successfully deleted timeline item.")
            
        elif action == "reorder":
            try:
                new_order = [int(i.strip()) for i in value.split(",")]
            except ValueError:
                print("Error: value must be a comma-separated list of integer indices.")
                return
            if len(new_order) != len(items) or set(new_order) != set(range(len(items))):
                print("Error: invalid reorder indices.")
                return
                
            before_vals = [it["raw"] for it in items]
            after_vals = [items[idx]["raw"] for idx in new_order]
            for i, idx in enumerate(new_order):
                target_block = items[i]
                new_val = items[idx]["raw"]
                payload = {
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": new_val}}]
                    }
                }
                update_block(target_block["block_id"], payload)
            _log_change(matched_name, "expectedStateTimeline", parent_id, before_vals, after_vals, f"Reordered timeline to indices: {value}")
            print(f"Successfully reordered timeline items.")
            
    # Auto-refresh local JSON cache
    read_daystyles()


def analyze_daystyles(name: Optional[str] = None) -> None:
    """Analyze historical JSONL files to compare actual vs expected timelines."""
    import glob
    from collections import defaultdict

    workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dailystate_dir = os.path.join(workspace_root, "sessions", "dailystate")

    if not os.path.exists(dailystate_dir):
        print(f"Error: dailystate directory not found at {dailystate_dir}")
        return

    # Load daystyle config
    if not os.path.exists(CONFIG_FILE):
        read_daystyles()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config_data = json.load(f)
    daystyles = config_data.get("daystyles", [])
    style_map = {ds["dayStyle"]: ds for ds in daystyles}

    # Scan all JSONL files for __day_mode_record__ entries
    jsonl_files = sorted(glob.glob(os.path.join(dailystate_dir, "*.jsonl")))
    if not jsonl_files:
        print("No dailystate JSONL files found.")
        return

    # Group files by day_mode
    mode_days: Dict[str, List[str]] = defaultdict(list)
    mode_entries: Dict[str, List[List[dict]]] = defaultdict(list)

    for fpath in jsonl_files:
        day_mode_found = None
        day_entries = []
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("activity") == "__day_mode_record__":
                        day_mode_found = entry.get("day_mode", "")
                    else:
                        day_entries.append(entry)
        except Exception:
            continue

        if day_mode_found:
            mode_days[day_mode_found].append(os.path.basename(fpath))
            mode_entries[day_mode_found].append(day_entries)

    if not mode_days:
        print("No day_mode records found in any JSONL files.")
        print("Hint: day_mode archival was recently added to midnight_routine.py.")
        print("      Records will accumulate over the coming days.")
        return

    # Filter by name if specified
    if name:
        best = difflib.get_close_matches(name, list(mode_days.keys()), n=1, cutoff=0.5)
        if not best:
            print(f"Error: No data found for DayStyle '{name}'.")
            print(f"Available: {', '.join(mode_days.keys())}")
            return
        target_modes = [best[0]]
    else:
        target_modes = list(mode_days.keys())

    # Output summary
    print("\n" + "=" * 60)
    print("DayStyle Analysis Report")
    print("=" * 60)

    for mode_name in sorted(target_modes):
        days = mode_days[mode_name]
        entries_per_day = mode_entries[mode_name]
        count = len(days)

        print(f"\n  {mode_name}: {count} days recorded")

        if count < 10:
            print(f"  ⚠ Insufficient data (need ≥10, have {count}). Skipping analysis.")
            print(f"    Dates: {', '.join(days[:5])}{'...' if count > 5 else ''}")
            continue

        # Get expected timeline
        expected = style_map.get(mode_name, {}).get("expectedStateTimeline", [])
        if not expected:
            print(f"  ⚠ No expectedStateTimeline found in config for '{mode_name}'.")
            continue

        # Aggregate actual first-activity times
        first_times: Dict[str, List[float]] = defaultdict(list)
        for day_entries in entries_per_day:
            for entry in day_entries:
                activity = entry.get("activity", "")
                started = entry.get("started_at", "")
                if not activity or not started:
                    continue
                try:
                    dt = datetime.fromisoformat(started)
                    minutes_since_midnight = dt.hour * 60 + dt.minute
                    if activity not in first_times or True:
                        first_times[activity].append(minutes_since_midnight)
                except Exception:
                    continue

        # Compare expected vs actual
        print(f"\n  {'Time':<8}  {'Expected':<20}  {'Actual (avg)':<20}  {'Drift'}")
        print(f"  {'─'*8}  {'─'*20}  {'─'*20}  {'─'*8}")

        for exp_entry in expected:
            exp_time = exp_entry.get("time", "??:??")
            exp_activity = exp_entry.get("activity", "?")
            exp_location = exp_entry.get("location", "?")

            # Parse expected time
            try:
                h, m = map(int, exp_time.split(":"))
                exp_minutes = h * 60 + m
            except Exception:
                exp_minutes = 0

            # Find matching actual entries
            actual_times = first_times.get(exp_activity, [])
            if actual_times:
                avg_minutes = sum(actual_times) / len(actual_times)
                avg_h = int(avg_minutes // 60)
                avg_m = int(avg_minutes % 60)
                drift = avg_minutes - exp_minutes
                drift_str = f"{'+' if drift >= 0 else ''}{int(drift)}m"
                drift_flag = " ⚡" if abs(drift) > 15 else ""
                print(f"  {exp_time:<8}  {exp_activity:<20}  {avg_h:02d}:{avg_m:02d} @ {exp_location:<12}  {drift_str}{drift_flag}")
            else:
                print(f"  {exp_time:<8}  {exp_activity:<20}  {'(no data)':<20}  {'—'}")

        # Recommendation
        drifts = []
        for exp_entry in expected:
            exp_activity = exp_entry.get("activity", "")
            actual_times = first_times.get(exp_activity, [])
            if actual_times:
                try:
                    h, m = map(int, exp_entry.get("time", "00:00").split(":"))
                    drift = (sum(actual_times) / len(actual_times)) - (h * 60 + m)
                    drifts.append(abs(drift))
                except Exception:
                    pass

        if drifts:
            avg_drift = sum(drifts) / len(drifts)
            if avg_drift > 15:
                print(f"\n  📊 Average drift: {avg_drift:.0f}min — consider updating timeline")
                print(f"     Use: python yonc_agent-master/main.py daystyle edit --name \"{mode_name}\" --field expectedStateTimeline --action update --index <N> --value '<new entry>'")
            else:
                print(f"\n  ✅ Average drift: {avg_drift:.0f}min — timeline is well-calibrated")

    print("\n" + "=" * 60)

