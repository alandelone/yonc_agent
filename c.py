import json
import sys
from llm_pipeline import _apply_rule_based_tags
from config_reader import load_config

cfg = load_config()

with open(r'c:\Users\Alandelone\CodeSpace_Local\yonc_agent\data\current_state.json', 'r', encoding='utf-8') as f:
    local_state = json.load(f)

# isolate the task
test_state = [t for t in local_state if t.get('notion_block_id') == '33be1eb5-ce57-81a1-966b-fe8416463b4b']

processed_state = _apply_rule_based_tags(test_state, cfg, False, allow_llm=False)
task = processed_state[0]

res = [
    f'theme_display_label: {task.get("theme_display_label", "NONE")}',
    f'Task Theme with colour tag: {task.get("tags", {}).get("Task Theme with colour", "NONE")}',
    f'context_heading: {task.get("context_heading", "NONE")}'
]

sys.stdout.buffer.write('\n'.join(res).encode('utf-8'))
