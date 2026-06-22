import json
from flow_pipeline import _normalize_scope_text, _pick_theme_key
from timeliner_reader import fetch_and_parse_timeliner
from flow_pipeline import _timeliner_entry_task_key, _timeliner_entry_title_match_keys, _timeliner_entry_theme_anchor

d = json.load(open('data/tasklist_state.json', encoding='utf-8'))
daq = [t for t in d if 'DAQ' in t.get('title', '')][0]

state_by_id = {str(t.get("notion_block_id") or t.get("id")): t for t in d}
parent_titles = []
current_pid = daq.get("parent_id")
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
            str(daq.get("title", "")),
            str(daq.get("original_notion_title", "")),
            str(daq.get("context_heading", "")),
        ] + parent_titles
    )
)
theme_text = _normalize_scope_text(_pick_theme_key(daq))

print("title_text:", title_text)
print("theme_text:", theme_text)

entries = fetch_and_parse_timeliner()
e = [x for x in entries if 'Apparatus' in getattr(x, 'colour_subtheme', '')][0]
sub_key = _timeliner_entry_task_key(e)
title_match_keys = _timeliner_entry_title_match_keys(e) or [sub_key]
theme_anchor = _timeliner_entry_theme_anchor(e)

print("title_match_keys:", title_match_keys)
print("theme_anchor:", theme_anchor)

title_ok = any(bool(key and key in title_text) for key in title_match_keys)
print("title_ok:", title_ok)

title_text_overwrite = _normalize_scope_text(daq.get("original_notion_title") or daq.get("title", ""))
print("title_text_overwrite:", title_text_overwrite)

if theme_anchor:
    theme_ok = bool(theme_anchor in theme_text)
    print("theme_ok init:", theme_ok)
    if theme_ok and theme_anchor not in title_text_overwrite:
        major_projects = ["thesis", "research", "solarman", "rstv", "review", "event"]
        first_part = title_text_overwrite.split(':')[0] if ':' in title_text_overwrite else title_text_overwrite
        print("first_part:", first_part)
        for mp in major_projects:
            if mp in first_part and mp != theme_anchor:
                print("OVERMATCH PREVENTED BY:", mp)
                theme_ok = False
                break
else:
    theme_ok = bool(sub_key in theme_text)

print("Final theme_ok:", theme_ok)
