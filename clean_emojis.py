import json
import requests
import re
import sys
sys.stdout.reconfigure(encoding='utf-8')
import re
from config import NOTION_HEADERS
BASE_URL = "https://api.notion.com/v1"

data = json.load(open("c:/test_codespace/yonc_agent/data/current_state.json", encoding="utf-8"))
apparatus_id = "383e1eb5-ce57-8129-976d-f7381a06d588"

# Recursively find all descendants of Apparatus Learning (and Apparatus Learning itself)
desc = [apparatus_id]
for _ in range(10):
    for t in data:
        if t.get('parent_id') in desc and t['id'] not in desc:
            desc.append(t['id'])

print(f"Found {len(desc)} total blocks under Apparatus Learning.")

count = 0
for t in data:
    if t['id'] not in desc:
        continue
    
    block_id = str(t.get('notion_block_id') or t.get('id', ''))
    if not block_id:
        continue
        
    url = f"{BASE_URL}/blocks/{block_id}"
    resp = requests.get(url, headers=NOTION_HEADERS)
    if resp.status_code != 200:
        continue
        
    block = resp.json()
    btype = block.get('type')
    if not btype or btype not in block:
        continue
        
    rich_texts = block[btype].get('rich_text', [])
    modified = False
    
    for rt in rich_texts:
        if rt.get('type') == 'text':
            content = rt['text']['content']
            for e in ['🚨', '🧨', '💣']:
                if e in content:
                    content = content.replace(e, '')
                    modified = True
            # Clean up double spaces left behind
            content = content.replace('  ', ' ')
            rt['text']['content'] = content
            
    if modified:
        payload = {btype: {"rich_text": rich_texts}}
        patch_resp = requests.patch(url, headers=NOTION_HEADERS, json=payload)
        if patch_resp.status_code == 200:
            count += 1
            print(f"Cleaned emoji from: {t.get('original_notion_title', block_id)}")
        else:
            print(f"Failed to fix {block_id}: {patch_resp.text}")

print(f"Successfully cleaned emojis from {count} blocks in Notion.")
