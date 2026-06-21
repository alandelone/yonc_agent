import json

with open('data/current_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)

parent = '386e1eb5-ce57-81a6-a0c8-e72eb022cad4'
with open('debug_out.txt', 'w', encoding='utf-8') as out:
    ptask = next((t for t in state if t.get('id') == parent), None)
    if ptask:
        out.write(f"Parent task:\n")
        out.write(f"  Title: {ptask.get('original_notion_title')}\n")
        out.write(f"  split_stage: {ptask.get('split_stage')}\n")
        out.write(f"  is_generated: {ptask.get('is_generated')}\n")
    
    out.write("\nChildren:\n")
    for c in state:
        if c.get('parent_id') == parent:
            title = c.get('original_notion_title')
            gen = c.get('is_generated')
            stage = c.get('split_stage')
            chk = c.get('checked')
            out.write(f"  {title} -> gen:{gen} stage:{stage} chk:{chk}\n")
