import ast

with open("tests/cfg_graph_test_cases/match.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
        print(ast.dump(tree, indent=2, include_attributes=True))