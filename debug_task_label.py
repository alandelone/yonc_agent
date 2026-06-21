import sys
import json
sys.stdout.reconfigure(encoding='utf-8')

from flow_pipeline import _load_merged_state
from timeliner_sync import _build_task_theme_label_index, _build_theme_original_title_index, _resolve_task_label_for_entry

class DummyEntry:
    def __init__(self, project, subproject, colour_subtheme, task_title=""):
        self.project = project
        self.subproject = subproject
        self.colour_subtheme = colour_subtheme
        self.task_title = task_title
        self.tags = {}

_, _, _, flat_tasks = _load_merged_state()

idx = _build_task_theme_label_index(flat_tasks)
original_title_index = _build_theme_original_title_index(flat_tasks)

print("Candidates for 'thesis':")
for c in original_title_index.get('thesis', set()):
    if 'Logic' in c:
        print(" -", c)

entry = DummyEntry(project="Thesis", subproject="", colour_subtheme="Phd Logic")
label = "Thesis"
res = _resolve_task_label_for_entry(entry, label, original_title_index)
print("Resolved task label for 'Phd Logic':", res)

entry2 = DummyEntry(project="Thesis", subproject="", colour_subtheme="Thesis Phd Logic")
res2 = _resolve_task_label_for_entry(entry2, label, original_title_index)
print("Resolved task label for 'Thesis Phd Logic':", res2)

