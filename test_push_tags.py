import json
import sys
from config_reader import load_config
from sync_engine import push_tags_to_notion
import notion_client

# Mock update_block
original_update_block = notion_client.update_block

def mock_update_block(block_id, rich_text, checked=False, block_type="to_do"):
    print("CALLED update_block FOR", block_id)
    text = "".join([rt["text"]["content"] for rt in rich_text])
    print("RICH TEXT:", text.encode("ascii", "ignore").decode())
    return original_update_block(block_id, rich_text, checked, block_type)

notion_client.update_block = mock_update_block

d = json.load(open('temp_out.json', encoding='utf-8'))
task = d[0] # 方法论证 Report
print("Task title:", task["title"].encode("ascii", "ignore").decode())
print("Task orig:", task["original_notion_title"].encode("ascii", "ignore").decode())

cfg = load_config()
push_tags_to_notion([task], cfg)
