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


def parse_title(raw_title: str, raw_desc: str | None, subthemes: list[str], style: str = "split") -> tuple[str | None, str, str | None]:
    clean_desc = (raw_desc or "").strip() or None
    working = (raw_title or "").strip()

    # 1. Separate description from title if not already provided
    if not clean_desc:
        match = re.search(r"\s+[:：]\s*", working) or re.search(r"[:：]\s+", working)
        if match:
            clean_desc = working[match.end():].strip() or None
            working = working[:match.start()].strip()

    if style == "split":
        # Keep task title intact (preserving emojis and tags), cleanly separating description
        return None, working or raw_title, clean_desc

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
        r"^(?:💻Focus|🧘Jail|Handy🤘🏻|小Do📱|🧟Zombie|Watch👁‍🗨|Read|🗂️(?:\d\uFE0F?\u20E3)?|[💣🚨🧨⚡🔥💥💯✅🎯💻🤔👥🧩📋✍️🔬🔨🤘🏻]|[\d*#]\uFE0F?\u20E3|\*[\d\.]+h\*|\s+)+",
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
    parser.add_argument(
        "--title-style",
        choices=["split", "pure", "prefix"],
        default="split",
        help="How to format clean title: 'split' (keep emojis & title name, only separate description), 'pure' (strip emojis), 'prefix' (add [Subtheme] prefix)",
    )
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

    cur.execute("SELECT id, title, description, work_type, wbs_level, tags, parent_id FROM graph_nodes")
    rows = cur.fetchall()

    # Pass 1: Parse titles and find direct subthemes
    # Rule: ONLY Level 4 tasks (WBS 4 or ACTION or depth >= 3) have descriptions!
    # Levels 1, 2, 3 keep their full titles and have description = None.
    raw_nodes = {r[0]: {"parent_id": r[6], "wbs_level": r[4], "work_type": r[3]} for r in rows}
    def get_wbs(nid):
        info = raw_nodes[nid]
        if info["wbs_level"] is not None:
            return info["wbs_level"]
        p = info["parent_id"]
        depth = 0
        while p and p in raw_nodes:
            depth += 1
            p = raw_nodes[p]["parent_id"]
        return 1 if depth == 0 else 2 if depth == 1 else 3 if depth == 2 else 4

    node_map = {}
    for node_id, raw_title, raw_desc, work_type, wbs_level, raw_tags, parent_id in rows:
        eff_wbs = get_wbs(node_id)
        is_level_4 = (eff_wbs == 4) or (work_type == "ACTION")
        if is_level_4:
            sub, clean_t, clean_d = parse_title(raw_title, raw_desc, all_subthemes, style=args.title_style)
        else:
            sub, clean_t, clean_d = None, raw_title, None

        tags_obj = json.loads(raw_tags) if raw_tags else {}
        node_map[node_id] = {
            "raw_title": raw_title,
            "raw_desc": raw_desc,
            "raw_tags": raw_tags,
            "tags_obj": tags_obj,
            "clean_title": clean_t,
            "clean_desc": clean_d,
            "work_type": work_type,
            "wbs_level": wbs_level,
            "parent_id": parent_id,
            "direct_sub": sub,
        }

    # Helper: resolve subtheme with ancestor fallback
    def resolve_subtheme(nid, visited=None):
        if visited is None:
            visited = set()
        if nid in visited or nid not in node_map:
            return None
        visited.add(nid)
        info = node_map[nid]
        if info["direct_sub"]:
            return info["direct_sub"]
        if info["tags_obj"].get("Subtheme"):
            return info["tags_obj"]["Subtheme"]
        if info["parent_id"]:
            return resolve_subtheme(info["parent_id"], visited)
        return None

    updates = []
    for node_id, info in node_map.items():
        sub = resolve_subtheme(node_id) if args.title_style != "split" else None
        target_title = f"[{sub}] {info['clean_title']}" if (args.title_style == "prefix" and sub) else info["clean_title"]

        tags_obj = dict(info["tags_obj"])
        tags_changed = False
        if args.title_style != "split" and sub and tags_obj.get("Subtheme") != sub:
            tags_obj["Subtheme"] = sub
            tags_changed = True
        new_tags_str = json.dumps(tags_obj, ensure_ascii=False) if tags_changed else info["raw_tags"]

        if target_title != info["raw_title"] or info["clean_desc"] != info["raw_desc"] or tags_changed:
            updates.append((node_id, info["raw_title"], target_title, info["clean_desc"], new_tags_str, info["work_type"], info["wbs_level"], sub))

    print(f"Total nodes: {len(rows)}")
    print(f"Nodes with updates: {len(updates)}")
    print("\n--- Samples (first 10) ---")
    for u in updates[:10]:
        print(f"ID: {u[0]}")
        print(f"  BEFORE Title: {u[1]}")
        print(f"  AFTER  Title: {u[2]}")
        if u[3]:
            print(f"  AFTER  Desc:  {u[3]}")
        if u[7]:
            print(f"  SAVED  Subtheme Tag: {u[7]}")
        print()

    if args.apply:
        from datetime import datetime
        backup_path = db_path.with_name(f"project_graph.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite3")
        shutil.copy2(db_path, backup_path)
        print(f"Created backup at {backup_path}")

        for node_id, _, clean_t, clean_d, new_tags_str, _, _, _ in updates:
            cur.execute(
                "UPDATE graph_nodes SET title = ?, description = ?, tags = ? WHERE id = ?",
                (clean_t, clean_d, new_tags_str, node_id),
            )
        conn.commit()
        print(f"Successfully updated {len(updates)} nodes in {db_path}!")
    else:
        print("Dry run completed. Run with '--apply' to persist these changes to the SQLite database.")

    conn.close()


if __name__ == "__main__":
    main()
