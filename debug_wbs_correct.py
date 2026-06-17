from config_reader import load_config, structure_yonctask_config

cfg = load_config()
yonc_config = structure_yonctask_config(cfg)

with open('debug_wbs_correct.txt', 'w', encoding='utf-8') as f:
    for level, data in yonc_config.get('wbs_levels', {}).items():
        f.write(f"Level {level}: {data.get('emoji')}\n")
