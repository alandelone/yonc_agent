import json
import logging
import os
import sys
from datetime import date, timedelta
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


def register_crons():
    logger.info("Refreshing cron settings and registering crons to nanobot action.jsonl...")
    try:
        from cron_manager import refresh_cron_cache
        entries = refresh_cron_cache()
    except Exception as e:
        logger.error(f"Failed to refresh cron settings: {e}")
        return
        
    target_types = {"alert", "trace", "tracexlt"}
    actions_to_append = []
    
    for entry in entries:
        cron_type = entry.get("cron_type", "").lower()
        if cron_type not in target_types:
            continue
            
        start_hour = entry.get("start_hour")
        end_hour = entry.get("end_hour")
        name_in_db = entry.get("name_in_db", "unknown")
        section = entry.get("section", 1)
        description = entry.get("description", "")
        
        expr = _build_cron_expr(start_hour, end_hour)
        
        job_id = f"cron_{name_in_db}_{section}"
        
        action_payload = {
            "action": "add",
            "params": {
                "id": job_id,
                "name": name_in_db,
                "enabled": True,
                "schedule": {
                    "kind": "cron",
                    "expr": expr,
                    "tz": "Asia/Kuala_Lumpur"
                },
                "payload": {
                    "kind": "agent_turn",
                    "message": f"[{entry.get('cron_type')}] {name_in_db}: {description}",
                    "deliver": True,
                    "channel": "telegram",
                    "to": "1055853620"
                },
                "delete_after_run": False
            }
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
    push_yesterday_dailystate()
    touch_today_dailystate()
    register_crons()
    logger.info("Midnight routine finished.")

if __name__ == "__main__":
    main()
