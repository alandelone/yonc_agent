import json, sys
sys.stdout.reconfigure(encoding='utf-8')

data = json.load(open("data/tasklist_state.json", "r", encoding="utf-8"))

ids = [
    "37fe1eb5-ce57-81a1-81bf-e4b73b1ff152",  # Draft in my Word
    "37fe1eb5-ce57-81b0-b823-d755cd59a3ce",  # 汇总电表 BOM (working example)
]

for t in data:
    if t["id"] in ids:
        print(f"Task: {t.get('original_notion_title', '')[:60]}")
        print(f"  id: {t['id']}")
        print(f"  ALL tags: {json.dumps(t.get('tags', {}), ensure_ascii=False)}")
        print(f"  wbs_level: {t.get('wbs_level')}")
        print(f"  has_tag_style: {t.get('has_tag_style')}")
        print(f"  synced_tags: {t.get('synced_tags')}")
        print(f"  is_generated: {t.get('is_generated')}")
        print(f"  type/notion_type: {t.get('type')}/{t.get('notion_type')}")
        print(f"  checked: {t.get('checked')}")
        print()

# Check: how many tasks have WBS level tag with 🔸?
count_wbs4 = 0
count_wbs4_no_emoji = 0
for t in data:
    tags = t.get("tags", {})
    wbs_tag = str(tags.get("WBS level", ""))
    if t.get("wbs_level") == 4:
        count_wbs4 += 1
        if "🔸" not in wbs_tag:
            count_wbs4_no_emoji += 1
            if count_wbs4_no_emoji <= 5:
                print(f"WBS=4 but no 🔸 in tag: {t.get('original_notion_title', '')[:50]}")
                print(f"  WBS tag value: '{wbs_tag}'")

print(f"\nTotal WBS=4 tasks: {count_wbs4}")
print(f"WBS=4 but missing 🔸 in tag text: {count_wbs4_no_emoji}")
