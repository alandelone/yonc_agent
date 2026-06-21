import sys
sys.stdout.reconfigure(encoding='utf-8')

from state_manager import load_state, STATE_FILE
from timeliner_sync import _build_theme_original_title_index

flat_tasks = load_state(STATE_FILE)
title_idx = _build_theme_original_title_index(flat_tasks)

print("=== title_idx keys ===")
print(title_idx.keys())
print("\ntitle_idx['thesis']:", title_idx.get('thesis'))
