import json
import re

d = json.load(open('data/tasklist_state.json', encoding='utf-8'))
daq = [t for t in d if 'DAQ' in t.get('title', '')][0]

def _normalize_scope_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]+', ' ', str(text).lower())
    text = re.sub(r'\s+', ' ', text).strip()
    return text

state_by_id = {str(t.get('notion_block_id') or t.get('id')): t for t in d}

parent_titles = []
current_pid = daq.get('parent_id')
depth_count = 0

print("Initial parent_id:", current_pid)
while current_pid and depth_count < 3:
    parent_task = state_by_id.get(str(current_pid))
    if parent_task:
        pt_title = str(parent_task.get("original_notion_title") or parent_task.get("title", ""))
        parent_titles.append(pt_title)
        print("Found parent title:", pt_title.encode('ascii', 'ignore').decode())
        current_pid = parent_task.get("parent_id")
        depth_count += 1
    else:
        print("Could not find parent for id:", current_pid)
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

print("Final title text for DAQ:")
print(title_text)

