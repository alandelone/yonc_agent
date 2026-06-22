import sys, requests, json
sys.stdout.reconfigure(encoding='utf-8')
from notion_client import BASE_URL, NOTION_HEADERS

block_id = '360e1eb5-ce57-80f8-8a8d-c73e4d51ee10'
resp = requests.get(f'{BASE_URL}/blocks/{block_id}', headers=NOTION_HEADERS)
block = resp.json()
b_type = block['type']
rt = block[b_type]['rich_text']

# Fix: replace the text content that says "科研人" with "Thesis"
# and "Thesis writing" with "thesis writing"
for seg in rt:
    if seg.get('type') == 'text':
        content = seg['text']['content']
        if '科研人' in content:
            seg['text']['content'] = content.replace('科研人', 'Thesis')
        # Also fix "Thesis writing" -> "thesis writing" in the task label segment
        if content.strip() == 'Thesis writing':
            seg['text']['content'] = content.replace('Thesis writing', 'thesis writing')

# Print what we'll write
plain = ''.join(
    s.get('text', {}).get('content', '') if s.get('type') == 'text'
    else s.get('plain_text', '')
    for s in rt
)
print("Will write:", plain)

# Update the block
payload = {b_type: {'rich_text': rt}}
resp2 = requests.patch(f'{BASE_URL}/blocks/{block_id}', headers=NOTION_HEADERS, json=payload)
resp2.raise_for_status()
print("Block updated successfully!")
