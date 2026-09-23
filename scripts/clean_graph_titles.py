"""Utility script to inspect and optionally clean titles and populate descriptions in project_graph.sqlite3.

Usage:
    python scripts/clean_graph_titles.py [--apply] [--db PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "project_graph.sqlite3"


def parse_title(raw_title: str, raw_desc: str | None, subthemes: list[str]) -> tuple[str | None, str, str | None]:
    clean_desc = (raw_desc or "").strip() or None
    working = (raw_title or "").strip()

    # 1. Separate description from title if not already provided
    if not clean_desc:
        match = re.search(r"\s+[:：]\s+", working)
        if match:
            clean_desc = working[match.end():].strip() or None
            working = working[:match.start()].strip()

    # 2. Strip leading WBS emojis, brackets, effort tags
    working = re.sub(
        r"^(?:[🏭🟧🔶🔸]|🤖💬🔜|\[.*?\]|\*[\d\.]+h\*|[\d*#]\uFE0F?\u20E3|\s+)+",
        "",
        working,
    ).strip()

    # 3. Resolve subtheme
    found_sub = None
    sorted_subs = sorted(subthemes, key=len, reverse=True)
    for s in sorted_subs:
        if not s:
            continue
        pat = r"^" + re.escape(s) + r"(?:\s+|$)"
        if re.search(pat, working):
            found_sub = s
            working = re.sub(pat, "", working).strip()
            break

    # 4. Strip priority emojis, modes, and icons
    working = re.sub(
        r"^(?:[💣🚨🧨⚡🔥💥💯✅🎯💻🤔👥🧩📋✍️🔬🔨🤘🏻]|💻Focus|🧘Jail|Handy🤘🏻|小Do📱|🧟Zombie|Read|Watch👁‍🗨|[\d*#]\uFE0F?\u20E3|\*[\d\.]+h\*|\s+)+",
        "",
        working,
    ).strip()

    # Check subtheme if after priority emoji
    if not found_sub:
        for s in sorted_subs:
            if not s:
                continue
            pat = r"^" + re.escape(s) + r"(?:\s+|$)"
            if re.search(pat, working):
                found_sub = s
                working = re.sub(pat, "", working).strip()
                break

    # 5. Clean up leading colons or punctuation
    working = re.sub(r"^(?:[💣🚨🧨⚡🔥💥💯✅🎯💻🤔👥🧩📋✍️🔬🔨🤘🏻]|[:：]|\s+)+", "", working).strip()

    return found_sub, working or raw_title, clean_desc


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Inspect or clean node titles and descriptions in SQLite.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Path to SQLite database")
    parser.add_argument("--apply", action="store_true", help="Apply changes to the database (creates backup first)")
    args = parser.parse_args()

    db_path = args.db
    if not db_path.exists():
        print(f"Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Fetch subthemes from yonc_config
    cur.execute("SELECT themes FROM yonc_config LIMIT 1")
    cfg_row = cur.fetchone()
    all_subthemes = []
    if cfg_row and cfg_row[0]:
        try:
            themes = json.loads(cfg_row[0])
            for t in themes:
                all_subthemes.extend(t.get("sub_themes", []))
                all_subthemes.append(t.get("name", ""))
        except Exception:
            pass
    all_subthemes = sorted(set(s for s in all_subthemes if s), key=len, reverse=True)

    cur.execute("SELECT id, title, description, work_type, wbs_level FROM graph_nodes")
    rows = cur.fetchall()

    updates = []
    for node_id, raw_title, raw_desc, work_type, wbs_level in rows:
        sub, clean_t, clean_d = parse_title(raw_title, raw_desc, all_subthemes)
        formatted_clean_title = f"[{sub}] {clean_t}" if sub else clean_t
        if formatted_clean_title != raw_title or clean_d != raw_desc:
            updates.append((node_id, raw_title, formatted_clean_title, clean_d, work_type, wbs_level))

    print(f"Total nodes: {len(rows)}")
    print(f"Nodes with updates: {len(updates)}")
    print("\n--- Samples (first 10) ---")
    for u in updates[:10]:
        print(f"ID: {u[0]}")
        print(f"  BEFORE Title: {u[1]}")
        print(f"  AFTER  Title: {u[2]}")
        if u[3]:
            print(f"  AFTER  Desc:  {u[3]}")
        print()

    if args.apply:
        backup_path = db_path.with_suffix(f".backup_{int(Path(__file__).stat().st_mtime)}.sqlite3")
        shutil.copy2(db_path, backup_path)
        print(f"Created backup at {backup_path}")

        for node_id, _, clean_t, clean_d, _, _ in updates:
            cur.execute(
                "UPDATE graph_nodes SET title = ?, description = ? WHERE id = ?",
                (clean_t, clean_d, node_id),
            )
        conn.commit()
        print(f"Successfully updated {len(updates)} nodes in {db_path}!")
    else:
        print("Dry run completed. Run with '--apply' to persist these changes to the SQLite database.")

    conn.close()


if __name__ == "__main__":
    main()
