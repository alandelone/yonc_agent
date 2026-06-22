import os
import json
import time

history_dir = r"C:\Users\Alandelone\AppData\Roaming\Code\User\History"
target_files = [
    "data/current_state.json",
    "data/tasklist_history.jsonl",
    "data/tasklist_state.json",
    "data/timeliner_state.json",
    "data/tunable.jsonl",
    "data/generated_preference_diffs.jsonl"
]

# 15:53:00 on June 22, 2026
target_time = time.mktime(time.strptime("2026-06-22 15:53:00", "%Y-%m-%d %H:%M:%S")) * 1000

results = {}

for root, dirs, files in os.walk(history_dir):
    if "entries.json" in files:
        entries_path = os.path.join(root, "entries.json")
        try:
            with open(entries_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            resource = data.get("resource", "")
            
            matched = None
            for tf in target_files:
                if tf in resource.replace("%2F", "/").replace("\\", "/"):
                    matched = tf
                    break
            
            if matched:
                entries = data.get("entries", [])
                # find entry just before the target time
                valid_entries = [e for e in entries if e.get("timestamp", 0) <= target_time]
                if valid_entries:
                    valid_entries.sort(key=lambda x: x["timestamp"], reverse=True)
                    best_entry = valid_entries[0]
                    file_path = os.path.join(root, best_entry["id"])
                    
                    results[matched] = {
                        "history_file": file_path,
                        "timestamp": best_entry["timestamp"]
                    }
        except Exception as e:
            pass

for k, v in results.items():
    print(f"MATCH|{k}|{v['history_file']}|{v['timestamp']}")
