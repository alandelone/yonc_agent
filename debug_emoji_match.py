import json
from config_reader import load_config, structure_yonctask_config

d = load_config()
cfg = structure_yonctask_config(d)

# Get the priority emoji keys
priority_emojis = list(cfg.get("priorities", {}).keys())

# The actual subtask title from state
state = json.load(open("data/tasklist_state.json", "r", encoding="utf-8"))
sub = [t for t in state if "Apparatus Learning" in t.get("title", "") and not t.get("tags")]

if not sub:
    print("No matching subtask found")
else:
    title = sub[0]["title"]
    original_title = sub[0].get("original_notion_title", title)
    
    results = {
        "priority_emojis_repr": [repr(e) for e in priority_emojis],
        "priority_emojis_hex": [[hex(ord(c)) for c in e] for e in priority_emojis],
        "title_chars_with_hex": [],
        "match_results": {}
    }
    
    # Check each char in the title for siren emoji (U+1F6A8)
    for i, ch in enumerate(title):
        if ord(ch) > 0x7F:
            results["title_chars_with_hex"].append({
                "pos": i, 
                "char": repr(ch), 
                "hex": hex(ord(ch))
            })
    
    # Test each priority emoji against the title
    for e in priority_emojis:
        results["match_results"][repr(e)] = {
            "in_title": e in title,
            "in_original": e in original_title,
            "replace_works": title.replace(e, "") != title
        }
    
    # Also look at what the _strip_stale_prefix_emojis does
    known = set()
    for e in priority_emojis:
        if e:
            known.add(str(e).strip())
    
    cleaned = title
    for e in known:
        cleaned = cleaned.replace(e, "")
    
    results["cleaned_title_same_as_original"] = (cleaned == title)
    results["cleaned_len_vs_original_len"] = f"{len(cleaned)} vs {len(title)}"
    
    # Get full subtask details
    results["subtask_keys"] = list(sub[0].keys())
    results["subtask_depth"] = sub[0].get("depth")
    results["subtask_notion_type"] = sub[0].get("notion_type") or sub[0].get("type")
    results["subtask_block_id"] = sub[0].get("notion_block_id") or sub[0].get("id")
    results["subtask_is_generated"] = sub[0].get("is_generated")
    results["subtask_has_tag_style"] = sub[0].get("has_tag_style")
    results["subtask_wbs_level"] = sub[0].get("wbs_level")
    results["subtask_parent_id"] = sub[0].get("parent_id")
    
    json.dump(results, open("debug_emoji_results.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("Done, see debug_emoji_results.json")
