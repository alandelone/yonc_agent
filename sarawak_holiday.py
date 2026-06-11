#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CLI to check if today is a holiday in Sarawak, Malaysia."""

import argparse
import io
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

# Fix Windows terminal encoding for emoji/unicode
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# --- Auto-update logic ---
UPDATE_CHECK_FILE = Path(__file__).parent / ".holidays_update_check"
UPDATE_INTERVAL_DAYS = 30


def _check_and_update_holidays():
    """Auto-upgrade holidays package if last check was > 30 days ago."""
    today_str = date.today().isoformat()

    # Read last check date
    if UPDATE_CHECK_FILE.exists():
        try:
            data = json.loads(UPDATE_CHECK_FILE.read_text())
            last_check = date.fromisoformat(data.get("last_check", "2000-01-01"))
            if (date.today() - last_check).days < UPDATE_INTERVAL_DAYS:
                return  # Too soon, skip
        except (json.JSONDecodeError, ValueError):
            pass

    # Time to update
    print(f"[AUTO-UPDATE] Checking for holidays package update (every {UPDATE_INTERVAL_DAYS} days)...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "holidays", "-q"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if "Successfully installed" in result.stdout:
            print("[AUTO-UPDATE] holidays package updated!")
        else:
            print("[AUTO-UPDATE] Already up to date.")
    except Exception as e:
        print(f"[AUTO-UPDATE] Update check failed: {e}")

    # Save check timestamp
    UPDATE_CHECK_FILE.write_text(json.dumps({"last_check": today_str}))


# Run auto-update check before importing
_check_and_update_holidays()

import holidays  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Check if today is a public holiday in Sarawak, Malaysia.")
    parser.add_argument("--date", "-d", type=str, help="Check a specific date (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--list", "-l", action="store_true", help="List all Sarawak holidays for the year.")
    parser.add_argument("--update", "-u", action="store_true", help="Force update the holidays package now.")
    args = parser.parse_args()

    # Force update
    if args.update:
        print("Forcing holidays package update...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "holidays"], timeout=60)
        # Reset the check timer
        UPDATE_CHECK_FILE.write_text(json.dumps({"last_check": date.today().isoformat()}))
        print("Done.")
        return

    if args.date:
        try:
            check_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print("Invalid date format. Use YYYY-MM-DD.")
            sys.exit(1)
    else:
        check_date = date.today()

    swk_holidays = holidays.Malaysia(state="SWK", years=check_date.year)

    # List all holidays
    if args.list:
        print(f"\n=== Public Holidays in Sarawak, Malaysia ({check_date.year}) ===")
        print("=" * 55)
        for d in sorted(swk_holidays.keys()):
            marker = "  <-- TODAY" if d == date.today() else ""
            print(f"  {d.strftime('%a, %d %b %Y')}  -  {swk_holidays[d]}{marker}")
        print(f"\nTotal: {len(swk_holidays)} holidays")
        return

    # Check single date
    label = "Today" if check_date == date.today() else check_date.strftime("%Y-%m-%d")
    formatted = check_date.strftime("%A, %d %B %Y")

    if check_date in swk_holidays:
        print(f"\n[YES] {label} ({formatted}) is a HOLIDAY in Sarawak!")
        print(f"  >> {swk_holidays[check_date]}")
    else:
        print(f"\n[NO] {label} ({formatted}) is NOT a holiday in Sarawak.")

    # Next upcoming holiday
    upcoming = sorted([d for d in swk_holidays if d > check_date])
    if upcoming:
        nxt = upcoming[0]
        days = (nxt - check_date).days
        print(f"\nNext holiday: {swk_holidays[nxt]} - {nxt.strftime('%a, %d %b %Y')} ({days} day{'s' if days != 1 else ''} away)")


if __name__ == "__main__":
    main()
