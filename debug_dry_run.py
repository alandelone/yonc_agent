import json
from config_reader import load_config, structure_yonctask_config

cfg = load_config()
structured_cfg = structure_yonctask_config(cfg)
themes = structured_cfg.get('themes', {})
state = json.load(open('data/current_state.json', encoding='utf-8'))

with open('debug_dry_run.txt', 'w', encoding='utf-8') as f:
    for task in state:
        original_title = task.get('original_notion_title', '')
        if 'Logic' in original_title or 'SolarMan' in original_title or 'Thesis' in original_title:
            tags = task.get('tags', {})
            theme_val = tags.get('Task Theme with colour', '')
            if not theme_val:
                for t_name in themes.keys():
                    if t_name and t_name in original_title:
                        theme_val = t_name
                        break
                if not theme_val:
                    for t_name, t_data in themes.items():
                        for st in t_data.get('sub_themes', []):
                            if st and st in original_title:
                                theme_val = st
                                break
                        if theme_val:
                            break
            
            main_theme_name = str(theme_val).split()[0] if theme_val else ''
            if main_theme_name and main_theme_name not in themes:
                for t_name, t_data in themes.items():
                    if main_theme_name in t_data.get('sub_themes', []):
                        main_theme_name = t_name
                        break
                        
            # Inline _resolve_display_theme_label logic
            search_target = original_title
            theme_str = main_theme_name
            if main_theme_name in themes and search_target:
                sub_themes = themes[main_theme_name].get("sub_themes", [])
                for st in sorted(sub_themes, key=len, reverse=True):
                    if st.lower() in search_target.lower():
                        theme_str = st
                        break
            
            f.write(f"Title: {original_title[:60]}\ntheme_val: {theme_val}\nmain: {main_theme_name}\ntheme_str: {theme_str}\n\n")
