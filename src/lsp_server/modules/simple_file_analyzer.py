import ast
from dataclasses import dataclass

"""

Minimal single-file type analyzer (MVP).

Walks the top-level statements of a module in order and traces variable types.
Only straight-line code is handled: no functions, no if/else, no loops.

Output is a type table: {(col, line): TableEntry} for every variable occurrence,
where (col, line) is the position the symbol starts at, as reported by ast
(col is 0-based, line is 1-based).

Each TableEntry points back to the entry its type was traced from, so following
the prev pointers gives the variable trace, e.g. for:

    x = 5
    y = x

y's entry ("y = x") -> x's entry ("x = 5") -> None

"""

@dataclass
class TableEntry:
    type: str
    line: int
    code: str                          # source of the statement that produced this type
    prev: "TableEntry | None" = None   # entry the type was traced from, None if it starts here


def infer_type(node: ast.expr, env: dict[str, TableEntry]) -> tuple[str, TableEntry | None]:
    """
    Work out the type of an expression using the variables known so far.
    Returns (type, entry the type was traced from), the entry being None
    when the type comes straight from the expression itself (e.g. a literal).
    """
    match node:
        case ast.Constant():
            return type(node.value).__name__, None
        case ast.Name():
            if node.id in env:
                return env[node.id].type, env[node.id]
            return "Unknown", None
        case ast.List():
            return "list", None
        case ast.Dict():
            return "dict", None
        case ast.Tuple():
            return "tuple", None
        case ast.Set():
            return "set", None
        case ast.BinOp():
            left_type, left_entry = infer_type(node.left, env)
            right_type, right_entry = infer_type(node.right, env)
            if left_type != right_type:
                return "Unknown", None
            # Both sides agree, so trace through whichever side is a variable
            return left_type, left_entry or right_entry
    return "Unknown", None


def analyze(source: str) -> dict[tuple[int, int], TableEntry]:
    tree = ast.parse(source)
    env = {}    # variable name -> entry of its latest assignment
    table = {}  # (col, line) -> entry for the symbol at that position

    for stmt in tree.body:
        code = ast.unparse(stmt)

        # Step 1: record every known variable read in this statement.
        # A read shares the entry of the assignment it reads from, so its
        # trace starts there. Done before the write so `x = x + 1` sees the old x.
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in env:
                table[(node.col_offset, node.lineno)] = env[node.id]

        # Step 2: record every variable written in this statement
        match stmt:
            case ast.Assign():
                value_type, prev = infer_type(stmt.value, env)
                entry = TableEntry(type=value_type, line=stmt.lineno, code=code, prev=prev)
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        env[target.id] = entry
                        table[(target.col_offset, target.lineno)] = entry

            case ast.AnnAssign(target=ast.Name()):
                # x: int = ... trusts the annotation, so the trace starts here
                entry = TableEntry(type=ast.unparse(stmt.annotation), line=stmt.lineno, code=code)
                env[stmt.target.id] = entry
                table[(stmt.target.col_offset, stmt.target.lineno)] = entry

    return table


if __name__ == "__main__":
    with open("tests/cfg_graph_test_cases/linear.py", "r", encoding="utf-8") as f:
        for (col, line), entry in analyze(f.read()).items():
            print(f"line {line}, col {col}: {entry.type}  <- {entry.code}")
