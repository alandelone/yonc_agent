import logging
import sys
from flow_pipeline import build_timeliner_scope, _load_merged_state

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.WARNING,
    format='%(levelname)s: %(message)s'
)

def check():
    _, _, _, state = _load_merged_state()
    if state:
        build_timeliner_scope(state, require_cached_state=False)

if __name__ == '__main__':
    check()
