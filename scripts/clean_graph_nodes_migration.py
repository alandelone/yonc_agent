"""Database migration script to clean titles, extract descriptions, and strip emojis in project_graph.sqlite3.

Usage:
    python scripts/clean_graph_nodes_migration.py [--dry-run]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "project_graph.sqlite3"

EMOJI_PATTERN = re.compile(
    r'[\U00010000-\U0010ffff\u2600-\u27bf\u2b50-\u2b55\u2300-\u23ff\u2190-\u21ff\u200d\ufe0f]'
)

def clean_node(title: str, description: str | None) -> tuple[str, str | None]:
    t = (title or "").strip()
    d = (description or "").strip() or None

    # 1. Extract trapped description if missing
    if not d and (":" in t or "：" in t):
        parts = re.split(r'\s*[:：]\s*', t, maxsplit=1)
        if len(parts) == 2 and parts[1].strip():
            t = parts[0].strip()
            d = parts[1].strip()

    # 2. Strip completion and effort markers
    t = re.sub(r'💯\s*✅|✅|💯', '', t)
    t = re.sub(r'\*\d+(?:\.\d+)?h\*', '', t)
    t = re.sub(r'实际\s*Deadline\s*[:：]?', '', t, flags=re.IGNORECASE)

    # 3. Strip compound mode tags with emojis
    t = re.sub(r'Handy\s*🤘[🏻🏼🏽🏾🏿]?', '', t)
    t = re.sub(r'小Do\s*📱?', '', t)
    t = re.sub(r'🧘\s*Jail', '', t)
    t = re.sub(r'💻\s*Focus', '', t)
    t = re.sub(r'🧟\s*Zombie', '', t)
    t = re.sub(r'Watch\s*👁‍?🗨?', '', t)
    t = re.sub(r'Read\s*📖', '', t)

    # 4. Strip standalone mode keywords if leading
    t = re.sub(r'^(?:Focus|Zombie)\b\s*', '', t, flags=re.IGNORECASE)

    # 5. Strip sequence markers like 🗂️0️⃣, 🗂️1️⃣, 0️⃣
    t = re.sub(r'🗂️?\s*\d\uFE0F?\u20E3', '', t)

    # 6. Strip all emojis and special pictographs from title
    t = EMOJI_PATTERN.sub('', t)

    # 7. Clean title whitespace and leading/trailing separators
    t = re.sub(r'\s+', ' ', t).strip(" \t\n\r|:-")
    if not t:
        t = "Untitled task"

    # 8. Clean description
    if d:
        d = EMOJI_PATTERN.sub('', d)
        d = re.sub(r'\s+', ' ', d).strip(" \t\n\r|:-")
        if not d:
            d = None

    return t, d


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Clean titles and descriptions in project_graph.sqlite3")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Path to SQLite DB")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without modifying database")
    args = parser.parse_args()

    db_path = args.db
    if not db_path.exists():
        print(f"Error: Database file not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("SELECT id, title, description FROM graph_nodes")
    rows = cur.fetchall()
    total_nodes = len(rows)
    print(f"Total nodes in database: {total_nodes}")

    updates = []
    extracted_desc_count = 0
    title_cleaned_count = 0

    for node_id, orig_title, orig_desc in rows:
        clean_title, clean_desc = clean_node(orig_title, orig_desc)
        if not orig_desc and clean_desc:
            extracted_desc_count += 1
        if clean_title != orig_title or clean_desc != orig_desc:
            title_cleaned_count += 1
            updates.append((clean_title, clean_desc, node_id))

    print(f"Nodes needing update: {len(updates)} / {total_nodes}")
    print(f"  - Descriptions extracted from title: {extracted_desc_count}")

    if args.dry_run:
        print("\n[DRY RUN] Sample updates (first 10):")
        for ct, cd, nid in updates[:10]:
            print(f"Node [{nid[:8]}]:")
            print(f"  Title: {ct}")
            print(f"  Desc : {cd}")
        print("\nDry run complete. No database changes were made.")
        conn.close()
        return

    # Backup database before making changes
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"project_graph.backup_before_clean_{timestamp}.sqlite3"
    print(f"\nCreating backup: {backup_path}")
    shutil.copy2(db_path, backup_path)
    print("Backup successfully created.")

    # Execute updates
    now_iso = datetime.now(timezone.utc).isoformat()
    cur.executemany(
        "UPDATE graph_nodes SET title = ?, description = ?, updated_at = ? WHERE id = ?",
        [(ct, cd, now_iso, nid) for ct, cd, nid in updates],
    )
    conn.commit()
    print(f"Successfully updated {len(updates)} nodes in graph_nodes.")

    # Verification
    cur.execute("PRAGMA integrity_check")
    integrity = cur.fetchone()[0]
    print(f"Integrity check: {integrity}")

    # Verify no emojis remain in titles
    cur.execute("SELECT id, title FROM graph_nodes")
    all_titles = cur.fetchall()
    emoji_titles = [t for t in all_titles if EMOJI_PATTERN.search(t[1])]
    print(f"Remaining titles with emojis: {len(emoji_titles)}")

    # Verify descriptions count
    cur.execute("SELECT count(*) FROM graph_nodes WHERE description IS NOT NULL AND trim(description) != ''")
    new_desc_count = cur.fetchone()[0]
    print(f"Nodes with description now: {new_desc_count} / {total_nodes}")

    conn.close()
    print("Migration finished successfully.")


if __name__ == "__main__":
    main()
