import ast

with open('flow_pipeline.py', 'r', encoding='utf-8') as f:
    source = f.read()

ast.parse(source)
print("Syntax OK")
