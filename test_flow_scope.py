import json
from flow_pipeline import build_timeliner_scope
_, scope_entries, _ = build_timeliner_scope([])
for se in scope_entries:
    print(f"subtheme: {se.get('subtheme_key')}, priority: {se.get('priority')}")
