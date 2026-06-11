import json
import logging
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("midnight_routine")

PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = PROJECT_ROOT.parent
DAILYSTATE_DIR = WORKSPACE_ROOT / "sessions" / "dailystate"
ACTION_JSONL_PATH = WORKSPACE_ROOT / "cron" / "action.jsonl"
TODAY_STATUS_PATH = WORKSPACE_ROOT / "today_status.json"
LOCAL_TZ = timezone(timedelta(hours=8))

DEFAULT_TODAY_STATUS = {
    "current_state": 0,
    "day_mode": "",
    "max_energy_lv": 5.0,
    "current_location": "",
    "state_checklist": {
        "STATE_0": {
            "initialized": False,
            "context_read": False,
            "mode_resolved": False,
            "options_cached": False,
            "user_notified": False,
        },
        "STATE_1": {
            "metrics_loaded": False,
            "matrix_compiled": False,
            "speculative_cache_written": False,
            "user_prompted": False,
        },
        "STATE_2": {
            "intent_parsed": False,
            "backend_allocated": False,
            "ledger_opened": False,
            "interrupt_scheduled": False,
        },
        "STATE_3": {
            "polling_active": True,
            "interrupt_cache_written": False,
        },
        "STATE_4": {
            "ledger_closed": False,
            "energy_recalculated": False,
            "db_posted": False,
            "remote_synced": False,
        },
    },
}

def archive_day_mode():
    """Read day_mode from today_status.json and append it as a metadata
    line to yesterday's JSONL ledger BEFORE resetting."""
    if not TODAY_STATUS_PATH.exists():
        logger.info("No today_status.json found, skipping day_mode archive.")
        return
    try:
        status = json.loads(TODAY_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to read today_status.json for day_mode archive: {e}")
        return

    day_mode_raw = status.get("day_mode", "")
    if not day_mode_raw:
        logger.info("No day_mode set in today_status.json, skipping archive.")
        return

    # Extract the dayStyle name string
    if isinstance(day_mode_raw, dict):
        day_mode_name = day_mode_raw.get("dayStyle", str(day_mode_raw))
    else:
        day_mode_name = str(day_mode_raw)

    yesterday = date.today() - timedelta(days=1)
    file_path = DAILYSTATE_DIR / f"{yesterday.isoformat()}.jsonl"
    if not file_path.exists():
        logger.info(f"Yesterday's JSONL {file_path} does not exist, skipping day_mode archive.")
        return

    now_iso = datetime.now(LOCAL_TZ).isoformat()
    meta_entry = {
        "activity": "__day_mode_record__",
        "activity_type": "metadata",
        "day_mode": day_mode_name,
        "started_at": now_iso,
        "ended_at": now_iso,
        "energy_lv": 0,
        "LIJ": 0,
        "location": ""
    }
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(meta_entry, ensure_ascii=False) + "\n")
        logger.info(f"Archived day_mode '{day_mode_name}' to {file_path}")
    except Exception as e:
        logger.error(f"Failed to archive day_mode: {e}")


def push_yesterday_dailystate():
    yesterday = date.today() - timedelta(days=1)
    yesterday_str = yesterday.isoformat()
    file_path = DAILYSTATE_DIR / f"{yesterday_str}.jsonl"
    
    logger.info(f"Checking yesterday's dailystate: {file_path}")
    
    if not file_path.exists():
        logger.info("File does not exist, nothing to push.")
        return
        
    try:
        content = file_path.read_text(encoding="utf-8").strip()
    except Exception as e:
        logger.error(f"Failed to read {file_path}: {e}")
        return
        
    if not content:
        logger.info("File is empty. Deleting it.")
        file_path.unlink()
        return
        
    logger.info("Pushing yesterday's dailystate to Notion...")
    try:
        from main import cmd_daily
        # Explicitly pass date_str=yesterday_str to ensure it writes to yesterday's Notion page
        cmd_daily(
            mode="write",
            prop_name="dailystate",
            value=content,
            date_str=yesterday_str
        )
        logger.info("Successfully pushed to Notion.")
    except Exception as e:
        logger.error(f"Failed to push to Notion: {e}")


def touch_today_dailystate():
    today_str = date.today().isoformat()
    file_path = DAILYSTATE_DIR / f"{today_str}.jsonl"
    
    if not file_path.exists():
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()
        logger.info(f"Created today's dailystate file: {file_path}")
    else:
        logger.info(f"Today's dailystate file already exists: {file_path}")


def reset_today_status():
    try:
        TODAY_STATUS_PATH.write_text(
            json.dumps(DEFAULT_TODAY_STATUS, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info(f"Reset today status file: {TODAY_STATUS_PATH}")
    except Exception as e:
        logger.error(f"Failed to reset today status file: {e}")


def _build_cron_expr(start_hour, end_hour):
    if end_hour is None:
        return f"0 {start_hour} * * *"
    
    if isinstance(end_hour, list):
        # Multiple specific hours
        hours = [start_hour] + end_hour
        hours_str = ",".join(str(h) for h in sorted(set(hours)))
        return f"0 {hours_str} * * *"
        
    if isinstance(end_hour, int):
        # Range of hours
        return f"0 {start_hour}-{end_hour} * * *"
        
    return f"0 {start_hour} * * *"


def _expand_schedule_hours(start_hour, end_hour) -> list[int]:
    if end_hour is None:
        hours = [start_hour]
    elif isinstance(end_hour, list):
        hours = [start_hour] + end_hour
    elif isinstance(end_hour, int):
        hours = list(range(start_hour, end_hour + 1))
    else:
        hours = [start_hour]

    return sorted({h for h in hours if isinstance(h, int) and 0 <= h <= 23})


def _build_once_at(today: date, hour: int) -> str:
    return datetime.combine(today, time(hour=hour), tzinfo=LOCAL_TZ).isoformat()


def register_crons():
    logger.info("Refreshing cron settings and registering one-time crons to nanobot action.jsonl...")
    try:
        from cron_manager import refresh_cron_cache
        entries = refresh_cron_cache()
    except Exception as e:
        logger.error(f"Failed to refresh cron settings: {e}")
        return
        
    target_types = {"alert", "trace", "tracexlt"}
    actions_to_append = []
    today = date.today()
    
    for entry in entries:
        cron_type = entry.get("cron_type", "").lower()
        if cron_type not in target_types:
            continue
            
        start_hour = entry.get("start_hour")
        end_hour = entry.get("end_hour")
        name_in_db = entry.get("name_in_db", "unknown")
        section = entry.get("section", 1)
        description = entry.get("description", "")

        for hour in _expand_schedule_hours(start_hour, end_hour):
            job_id = f"cron_{name_in_db}_{section}_{today.isoformat()}_{hour:02d}"
            action_payload = {
                "action": "add",
                "params": {
                    "id": job_id,
                    "name": name_in_db,
                    "enabled": True,
                    "schedule": {
                        "kind": "at",
                        "at": _build_once_at(today, hour),
                        "tz": "Asia/Kuala_Lumpur"
                    },
                    "payload": {
                        "kind": "agent_turn",
                        "message": f"[{entry.get('cron_type')}] {name_in_db}: {description}",
                        "deliver": True,
                        "channel": "telegram",
                        "to": "1055853620"
                    },
                    "delete_after_run": True
                },
            }
            actions_to_append.append(json.dumps(action_payload, ensure_ascii=False))

    if actions_to_append:
        try:
            ACTION_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(ACTION_JSONL_PATH, "a", encoding="utf-8") as f:
                for line in actions_to_append:
                    f.write(line + "\n")
            logger.info(f"Appended {len(actions_to_append)} actions to {ACTION_JSONL_PATH}")
        except Exception as e:
            logger.error(f"Failed to append to action.jsonl: {e}")
    else:
        logger.info("No matching crons found to register.")

def main():
    logger.info("Starting midnight routine...")
    archive_day_mode()            # NEW: preserve day_mode FIRST
    push_yesterday_dailystate()   # Then push to Notion (now includes day_mode)
    touch_today_dailystate()
    reset_today_status()          # Now safe to reset
    register_crons()
    logger.info("Midnight routine finished.")

if __name__ == "__main__":
    main()
