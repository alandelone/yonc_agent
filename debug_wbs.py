from config_reader import load_config
from config_reader import structure_yonctask_config
cfg = structure_yonctask_config(load_config())
with open('debug_wbs.txt', 'w', encoding='utf-8') as f:
    for level, data in cfg.get('wbs_levels', {}).items():
        f.write(f"Level {level}: {data.get('emoji')}\n")
