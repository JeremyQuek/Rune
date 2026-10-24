import ast
import os

# Dumps the AST of a test case. Run from anywhere.
ROOT = os.path.join(os.path.dirname(__file__), "..")

with open(os.path.join(ROOT, "tests/cfg_graph_test_cases/match.py"), "r", encoding="utf-8") as f:
    tree = ast.parse(f.read())
    print(ast.dump(tree, indent=2, include_attributes=True))
