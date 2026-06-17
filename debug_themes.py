import json
from config_reader import load_config, structure_yonctask_config

cfg = load_config()
sc = structure_yonctask_config(cfg)
with open('debug_themes.txt', 'w', encoding='utf-8') as f:
    json.dump(sc.get('themes'), f, indent=2, ensure_ascii=False)
