import json
import sys
state = json.load(open('data/current_state.json', encoding='utf-8'))
for t in state:
    title = t.get('title', '')
    if 'Logic' in title or 'SolarMan' in title or 'Thesis' in title:
        try:
            sys.stdout.buffer.write(f"{t.get('has_tag_style')} | {title[:60]}\n".encode('utf-8'))
        except: pass
