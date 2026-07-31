import ast

with open("tests/try_catch.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
        print(ast.dump(tree, indent=2, include_attributes=True))