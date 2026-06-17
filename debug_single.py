import json
from notion_client import update_block
block_id = " d3174151-5184-48f8-b347-1fdded8c3f4e\
payload = { \to_do\: { \rich_text\: [ { \type\: \text\, \text\: { \content\: \Thesis \ }, \annotations\: { \bold\: True, \code\: True, \color\: \red\ } }, { \type\: \text\, \text\: { \content\: \Phd Logic: clear justification\ }, \annotations\: { \strikethrough\: False, \color\: \default\ } } ], \color\: \default\, \checked\: False } }
res = update_block(block_id, payload)
print(res)
