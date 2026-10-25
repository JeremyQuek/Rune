import ast
from dataclasses import dataclass, field

"""

Minimal single-file type analyzer (MVP).

Walks the top-level statements of a module in order and traces variable types.
Only straight-line code is handled: no functions, no if/else, no loops.

Output is a type table: {(col, line): TableEntry} for every variable occurrence,
where (col, line) is the position the symbol starts at, as reported by ast
(col is 0-based, line is 1-based).

Each TableEntry points back to the entries its type was traced from, so following
the parents gives the variable trace. It is a DAG, not a chain, e.g. for:

    a = 1
    b = 2
    c = a + b

c's entry ("c = a + b") -> parents [a's entry ("a = 1"), b's entry ("b = 2")]

"""

@dataclass
class Operand:
    name: str          # source text, e.g. `a` or `1`
    type: str
    line: int | None   # line the operand's type was assigned on, None for literals and unknown names


@dataclass
class TableEntry:
    type: str
    line: int
    code: str                                                  # source of the statement that produced this type
    parents: list["TableEntry"] = field(default_factory=list)  # entries the type was traced from, empty if it starts here
    operands: list[Operand] = field(default_factory=list)      # the names and literals the rhs is built from


def unique(entries: list[TableEntry]) -> list[TableEntry]:
    """Drop repeated entries (e.g. `y + y`), keeping order."""
    seen = []
    for entry in entries:
        if not any(entry is s for s in seen):
            seen.append(entry)
    return seen


def infer_type(node: ast.expr, env: dict[str, TableEntry]) -> tuple[str, list[TableEntry]]:
    """
    Work out the type of an expression using the variables known so far.
    Returns (type, entries the type was traced from), the list being empty
    when the type comes straight from the expression itself (e.g. a literal).
    """
    match node:
        case ast.Constant():
            return type(node.value).__name__, []
        case ast.Name():
            if node.id in env:
                return env[node.id].type, [env[node.id]]
            return "Unknown", []
        case ast.List() | ast.Tuple() | ast.Set():
            # The container's type is fixed, but its elements still feed the trace
            parents = [p for elt in node.elts for p in infer_type(elt, env)[1]]
            return type(node).__name__.lower(), unique(parents)
        case ast.Dict():
            parts = [k for k in node.keys if k is not None] + node.values
            parents = [p for part in parts for p in infer_type(part, env)[1]]
            return "dict", unique(parents)
        case ast.BinOp():
            left_type, left_parents = infer_type(node.left, env)
            right_type, right_parents = infer_type(node.right, env)
            parents = unique(left_parents + right_parents)
            if left_type != right_type:
                return "Unknown", parents
            return left_type, parents
    return "Unknown", []


def operands_of(node: ast.expr, env: dict[str, TableEntry]) -> list[Operand]:
    """The names and literals an expression is built from, in source order, each once."""
    leaves = [n for n in ast.walk(node) if isinstance(n, (ast.Name, ast.Constant))]
    leaves.sort(key=lambda n: (n.lineno, n.col_offset))
    operands = []
    for leaf in leaves:
        text = ast.unparse(leaf)
        if any(o.name == text for o in operands):
            continue
        if isinstance(leaf, ast.Name):
            known = env.get(leaf.id)
            operands.append(Operand(text, known.type if known else "Unknown", known.line if known else None))
        else:
            operands.append(Operand(text, type(leaf.value).__name__, None))
    return operands


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
                value_type, parents = infer_type(stmt.value, env)
                entry = TableEntry(type=value_type, line=stmt.lineno, code=code, parents=parents,
                                   operands=operands_of(stmt.value, env))
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        env[target.id] = entry
                        table[(target.col_offset, target.lineno)] = entry

            case ast.AnnAssign(target=ast.Name()):
                # x: int = ... trusts the annotation, so the trace starts here
                operands = operands_of(stmt.value, env) if stmt.value else []
                entry = TableEntry(type=ast.unparse(stmt.annotation), line=stmt.lineno, code=code, operands=operands)
                env[stmt.target.id] = entry
                table[(stmt.target.col_offset, stmt.target.lineno)] = entry

    return table


if __name__ == "__main__":
    with open("tests/trace_dag_preview.py", "r", encoding="utf-8") as f:
        for (col, line), entry in analyze(f.read()).items():
            print(f"line {line}, col {col}: {entry.type}  <- {entry.code}  parents: {[p.code for p in entry.parents]}")
