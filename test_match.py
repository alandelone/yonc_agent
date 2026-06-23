import sys, json, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from flow_pipeline import build_timeliner_scope

tasks = json.load(open('data/tasklist_state.json', encoding='utf-8'))
target_id = '388e1eb5-ce57-81d5-bb62-fd612b314865'

scoped_ids, rank_by_task_id, _ = build_timeliner_scope(tasks, tasks)
print("Is target in scoped_ids?", target_id in scoped_ids)

target_task = next(t for t in tasks if t['id'] == target_id)
print("Target task after build_timeliner_scope:")
print(f"timeliner_rank: {target_task.get('timeliner_rank')}")
print(f"timeliner_key: {target_task.get('timeliner_key')}")
