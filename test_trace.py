import json
import sys
from config_reader import load_config
from sync_engine import push_tags_to_notion

d = json.load(open('temp_out.json', encoding='utf-8'))
task = d[0] # 方法论证 Report
cfg = load_config()

lines_executed = []
def trace_calls(frame, event, arg):
    if event == "line":
        if "sync_engine.py" in frame.f_code.co_filename and frame.f_code.co_name == "push_tags_to_notion":
            lines_executed.append(frame.f_lineno)
    return trace_calls

sys.settrace(trace_calls)
push_tags_to_notion([task], cfg)
sys.settrace(None)

with open('trace_output.txt', 'w', encoding='utf-8') as f:
    f.write("Lines executed:\n")
    for lineno in lines_executed:
        f.write(f"{lineno}\n")
