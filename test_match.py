from flow_pipeline import build_timeliner_scope, fetch_and_parse_timeliner, _normalize_scope_text, _timeliner_entry_theme_anchor, _timeliner_entry_title_match_keys, _timeliner_entry_task_key
entries=fetch_and_parse_timeliner()
theme_text='phdsettle research | review | event | solarman | thesis | dev'
title_text='solarman apparatus learning solarman'
matched=False
for entry in entries:
  t_anchor=_normalize_scope_text(_timeliner_entry_theme_anchor(entry))
  t_keys=_timeliner_entry_title_match_keys(entry)
  if 'solarman' in t_anchor or 'apparatus' in str(t_keys):
    print(f'Anchor: {t_anchor}, Keys: {t_keys}')
    if t_anchor in theme_text and any(k in title_text for k in t_keys):
      matched=True
print('Matched:', matched)
