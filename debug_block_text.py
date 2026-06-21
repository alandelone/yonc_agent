import sys, json, requests
sys.stdout.reconfigure(encoding='utf-8')

from notion_client import BASE_URL, NOTION_HEADERS

# SolarMan block ID
block_id = "34ee1eb5-ce57-803c-83e0-fe7163166c59"
resp = requests.get(f"{BASE_URL}/blocks/{block_id}", headers=NOTION_HEADERS)
resp.raise_for_status()
block = resp.json()

b_type = block.get("type")
rt = block.get(b_type, {}).get("rich_text", [])

print(f"Block type: {b_type}")
print(f"\n=== Rich text segments ===")
for i, segment in enumerate(rt):
    seg_type = segment.get("type")
    if seg_type == "text":
        content = segment["text"]["content"]
        print(f"  [{i}] TEXT: {content!r}")
    elif seg_type == "mention":
        mention = segment.get("mention", {})
        print(f"  [{i}] MENTION: {json.dumps(mention, ensure_ascii=False)}")

print(f"\n=== Full plain text ===")
full_text = "".join(
    s.get("text", {}).get("content", "") if s.get("type") == "text"
    else s.get("plain_text", "")
    for s in rt
)
print(full_text)
