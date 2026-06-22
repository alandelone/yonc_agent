import json
from flow_pipeline import _normalize_scope_text, _pick_theme_key
from timeliner_reader import fetch_and_parse_timeliner
from flow_pipeline import _timeliner_entry_task_key, _timeliner_entry_title_match_keys, _timeliner_entry_theme_anchor

d = json.load(open('data/tasklist_state.json', encoding='utf-8'))
daq = [t for t in d if 'DAQ' in t.get('title', '')][0]
state = d

entries = fetch_and_parse_timeliner()

scope_entries = []
seen_subtheme = set()
for entry in entries:
    raw_subproject = getattr(entry, "subproject", "")
    raw_task_key = _timeliner_entry_task_key(entry)
    sub_key = _normalize_scope_text(raw_task_key)
    title_match_keys = _timeliner_entry_title_match_keys(entry)
    if not sub_key:
        continue
    subproject_txt = str(raw_subproject or "").strip()
    anchor_raw = _timeliner_entry_theme_anchor(entry)
    theme_anchor = _normalize_scope_text(anchor_raw)
    scope_entries.append(
        {
            "subtheme_key": sub_key,
            "title_match_keys": title_match_keys or [sub_key],
            "theme_anchor": theme_anchor,
            "is_subproject": bool(subproject_txt),
            "raw_label": str(raw_task_key or getattr(entry, "colour_subtheme", "")).strip(),
            "matched_count": 0,
        }
    )

task = daq
task_id = str(task.get("notion_block_id"))

theme_text = _normalize_scope_text(_pick_theme_key(task))

state_by_id = {str(t.get("notion_block_id") or t.get("id")): t for t in state}
parent_titles = []
current_pid = task.get("parent_id")
depth_count = 0
while current_pid and depth_count < 3:
    parent_task = state_by_id.get(str(current_pid))
    if parent_task:
        parent_titles.append(str(parent_task.get("original_notion_title") or parent_task.get("title", "")))
        current_pid = parent_task.get("parent_id")
        depth_count += 1
    else:
        break

title_text = _normalize_scope_text(
    " ".join(
        [
            str(task.get("title", "")),
            str(task.get("original_notion_title", "")),
            str(task.get("context_heading", "")),
        ] + parent_titles
    )
)

print("evaluating task DAQ")
for rank, se in enumerate(scope_entries):
    sub_key = se["subtheme_key"]
    if 'apparatus' not in sub_key:
        continue
    
    theme_anchor = se["theme_anchor"]
    title_match_keys = se.get("title_match_keys") or [sub_key]
    
    title_ok = any(bool(key and key in title_text) for key in title_match_keys)
    print("title_ok:", title_ok, "keys:", title_match_keys)
    
    title_text_overwrite = _normalize_scope_text(task.get("original_notion_title") or task.get("title", ""))
    
    if theme_anchor:
        theme_ok = bool(theme_anchor in theme_text)
        print("theme_ok early:", theme_ok, "anchor:", theme_anchor, "theme_text:", theme_text)
        if theme_ok and theme_anchor not in title_text_overwrite:
            major_projects = ["thesis", "research", "solarman", "rstv", "review", "event"]
            first_part = title_text_overwrite.split(':')[0] if ':' in title_text_overwrite else title_text_overwrite
            print("first_part:", first_part)
            for mp in major_projects:
                if mp in first_part and mp != theme_anchor:
                    theme_ok = False
                    print("Overmatch prevented! mp:", mp)
                    break
    else:
        theme_ok = bool(sub_key in theme_text)

    print("Final title_ok:", title_ok, "theme_ok:", theme_ok)
