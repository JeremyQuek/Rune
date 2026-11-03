import ast
import copy
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from functools import reduce

from type_lattice import LatticeValue, display
from lexical_environment import Key
from provenance_table import Origin, ProvenanceTable, TableEntry
from module_table_builder import ModuleTableBuilder
from global_namespace_table import GlobalNamespaceTable
from ast_node_wrappers import CaughtAs, EnteredFrom, IteratedFrom, ParameterOf, StarredFrom, UnpackedAt, unparse_header

class ExpressionEvaluatorMock():
    """
    Stands in for the expression evaluator: does the substitution, fakes the computation.
    Each leaf of the recipe (a parent, found by its position) is replaced by its type, then:
        JOIN entry                        → the union of its parents (already the real rule)
        the recipe is one leaf (x = y)    → that leaf's type, passed through
        a read whose parent is its definition (x, a.b assigned) → the definition's type
        anything else (a + b, f(x), ...)  → the substituted recipe as a placeholder type: ⟨int + str⟩
    A placeholder inside a placeholder shows as …, so a loop (x += 1) converges instead of nesting forever.
    """

    @staticmethod
    def evaluate(entry: TableEntry, parent_types: dict[Key, LatticeValue]) -> LatticeValue:
        union = reduce(LatticeValue.join, parent_types.values(), LatticeValue.unknown())
        recipe = entry.expr
        if entry.origin == Origin.JOIN:
            return union
        if recipe is None or not parent_types or isinstance(recipe, ParameterOf):
            return union   # no recipe, nothing to substitute, or a parameter's default: its type
        if isinstance(recipe, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return LatticeValue.of(f"⟨def {recipe.name}(...)⟩")

        # a wrapper (IteratedFrom, UnpackedAt, StarredFrom, CaughtAs, EnteredFrom) is substituted inside its one plain-AST
        # field; nested ones (for a, b in pairs: UnpackedAt(IteratedFrom(pairs))) are unwrapped to the innermost
        inner = recipe
        while isinstance(inner, (CaughtAs, IteratedFrom, UnpackedAt, StarredFrom, EnteredFrom)):
            inner = inner.type if isinstance(inner, CaughtAs) else inner.value
        substituted, hits = ExpressionEvaluatorMock._mock_substitute(inner, parent_types)
        if inner is recipe and isinstance(substituted, ast.Name) and len(hits) == 1:
            return parent_types[hits[0]]   # the whole recipe was one leaf
        if not hits and isinstance(recipe, (ast.Name, ast.Attribute)) and ast.unparse(recipe) == entry.symbol:
            return union                   # a read: its parent is the definition it sees
        return LatticeValue.of(f"⟨{ExpressionEvaluatorMock._mock_text(recipe, substituted, parent_types)}⟩")

    @staticmethod
    def _mock_substitute(recipe: ast.AST, parent_types: dict[Key, LatticeValue]) -> tuple[ast.AST, list[Key]]:
        """A copy of recipe with each leaf whose position is a parent's key replaced by its type's name."""
        hits: list[Key] = []

        class Substitute(ast.NodeTransformer):
            def _leaf(self, node: ast.expr) -> ast.AST:
                if getattr(node, "lineno", None) is not None:   # synthetic recipes (builtins.len) have no position
                    key = ((node.end_lineno, node.end_col_offset - len(node.attr)) if isinstance(node, ast.Attribute)
                           else (node.lineno, node.col_offset))
                    if key in parent_types:
                        hits.append(key)
                        return ast.Name(id=ExpressionEvaluatorMock._mock_show(parent_types[key]))
                return self.generic_visit(node)
            visit_Name = visit_Attribute = _leaf

        return Substitute().visit(copy.deepcopy(recipe)), hits

    @staticmethod
    def _mock_show(value: LatticeValue) -> str:
        """A parent's type inside a placeholder; a placeholder in it shows as …"""
        return " | ".join(sorted("…" if display(t).startswith("⟨") else display(t) for t in value.types)) or "Unknown"

    @staticmethod
    def _mock_text(recipe: ast.AST, substituted: ast.AST, parent_types: dict[Key, LatticeValue]) -> str:
        """The substituted recipe as text (substituted is the wrapper's inner field); the wrappers and x += e have no unparse of their own."""
        match recipe:
            case IteratedFrom():
                return f"element of {ast.unparse(substituted)}"
            case UnpackedAt(index=index):
                return f"[{index}] of {ast.unparse(substituted)}"
            case StarredFrom():
                return f"*{ast.unparse(substituted)}"
            case CaughtAs():
                return f"instance of {ast.unparse(substituted)}"
            case EnteredFrom():
                return f"{ast.unparse(substituted)}.__enter__()"
            case ast.AugAssign(op=op):
                # parents: the old x first, then the reads of e
                in_value = ExpressionEvaluatorMock._mock_substitute(recipe.value, parent_types)[1]
                old = next((key for key in parent_types if key not in in_value), None)
                left = ExpressionEvaluatorMock._mock_show(parent_types[old]) if old else "Unknown"
                symbol = ast.unparse(ast.BinOp(ast.Name("a"), op, ast.Name("b")))[2:-2]
                return f"{left} {symbol} {ast.unparse(substituted.value)}"
        return ast.unparse(substituted)


@dataclass
class Request():
    """
    The evaluator's answer when it can't finish: the types of members it can't see, e.g. ("x" on A) for a.x
    with a: A. It knows Python, not the tables, so it asks; ModuleFileObject finds the keys.
    """
    requests: list[tuple[LatticeValue, str]]   # (receiver type, member name)


class ModuleFileObject():
    """
    One file: builds its provenance table, then answers get_type(key) lazily, caching every type it resolves.
    Public surface (the engine reads nothing else):
        get_type(key)      the type at key
        key_at(line, col)  the positional key whose name covers the cursor (ast coordinates), or None
        parents(key)       the keys key's type was derived from
        symbol(key)        the name written at key ("x", "self.x")
        side(key)          "lhs" if key writes its symbol, "rhs" if it reads it
        source(key)        where a type with no parents comes from: "literal", "annotation", "builtin", ...
        code(key)          the code that made key, for trace labels: "c = a + b", "for a, b in pairs", "k.v"
    """
    MAX_CYCLE_PASSES = 10

    def __init__(self, filepath: str, source_code: str, global_namespace_table: GlobalNamespaceTable):
        self.filepath: str = filepath
        self.global_namespace_table: GlobalNamespaceTable= global_namespace_table
        self.source_code: str = source_code
        self.table: ProvenanceTable = ModuleTableBuilder(filepath, source_code, global_namespace_table).build()
        self.expr_evaluator:ExpressionEvaluatorMock = ExpressionEvaluatorMock

    def get_type(self, key: Key) -> LatticeValue:
        """
        The type at key. Tarjan over the unresolved parents yields each SCC parents first; each is resolved
        before Tarjan moves on, so its parents are always ready. A Request from the evaluator becomes parent edges
        (_add_dynamic_link_tarjan) and the walk reruns: resolved SCCs are leaves now, so only what was still
        open is walked again.
        """
        if key not in self.table:
            return LatticeValue.unknown()
        while True:
            for scc in self._run_tarjan(key):
                request = self._resolve_scc_tarjan(scc)
                if request is not None:
                    self._add_dynamic_link_tarjan(*request)
                    break
            else:
                return self.table[key].type

    def key_at(self, line: int, col: int) -> Key | None:
        """
        The key under the cursor. Positional keys sit where a name starts (an attribute's, at the attribute), so
        any key on the line whose last name segment spans col matches; the rightmost wins when spans overlap.
        """
        hits = [key for key, entry in self.table.items()
                if len(key) == 2 and all(isinstance(n, int) for n in key)
                and key[0] == line and key[1] <= col < key[1] + len(entry.symbol.rsplit(".", 1)[-1])]
        return max(hits, default=None)

    def parents(self, key: Key) -> list[Key]:
        """The keys key's type is derived from, in the table: what a trace walks."""
        return [p for p in self.table[key].parents if p in self.table] if key in self.table else []

    def symbol(self, key: Key) -> str:
        return self.table[key].symbol if key in self.table else ""

    def side(self, key: Key) -> str:
        return self.table[key].side if key in self.table else "lhs"

    def source(self, key: Key) -> str:
        """
        Where key's type comes from when no parent explains it, for the trace's leaves:
            builtin      ("builtins", name)
            parameter    a parameter (its annotation, receiver or default decides the type)
            import       a module or a name imported from one
            definition   def f / class A: the definition is its own type
            annotation   x: int with no value
            literal      a recipe with no names in it: 1, "s", [1, 2]
            unresolved   anything else: a name with no definition, a lookup nothing answers yet
        """
        entry = self.table.get(key)
        if entry is None:
            return "unresolved"
        if key[0] == "builtins":
            return "builtin"
        if entry.origin == Origin.PARAMETER:
            return "parameter"
        if entry.origin == Origin.IMPORT:
            return "import"
        if isinstance(entry.expr, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return "definition"
        if entry.expr is None and entry.resolved:
            return "annotation"
        if entry.expr is not None and not any(isinstance(n, (ast.Name, ast.Attribute)) for n in ast.walk(entry.expr)):
            return "literal"
        return "unresolved"

    def code(self, key: Key) -> str:
        """
        The code that made key, for trace labels; never a comment, always one line.
            builtin                      builtins.len
            binding wrapper              its statement, rebuilt by the wrapper's unparse: for a, b in pairs, x, *y = e,
                                         except E as err, with open(p) as fh, b: int = 0
            def f / class A              the header, decorators and body dropped: def f(a, b=x) -> int
            import                       import m / from m import b / ... as k (the recipes are synthetic: no source)
            read                         its exact text: k.v
            x += e                       the statement's exact text
            x: T (no value)              x: T, from the resolved type
            any other definition         symbol = its recipe's exact text: c = a + b
        Exact text is cut from the source by position, so it keeps the user's formatting; rebuilt statements are
        ast.unparse'd, so they're normalised.
        """
        entry = self.table.get(key)
        if entry is None:
            return ""
        expr = entry.expr
        if key[0] == "builtins":
            return f"builtins.{entry.symbol}"
        if isinstance(expr, (IteratedFrom, UnpackedAt, StarredFrom, CaughtAs, EnteredFrom, ParameterOf)):
            return expr.unparse()
        if isinstance(expr, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            header = copy.copy(expr)
            header.body, header.decorator_list = [], []
            return unparse_header(header)
        if entry.origin == Origin.IMPORT or (expr is not None and getattr(expr, "lineno", None) is None):
            return self._import_code(entry)
        if expr is None:
            return f"{entry.symbol}: {entry.type!r}" if entry.resolved else entry.symbol
        text = self._source_segment_code(expr)
        if text is None:
            return entry.symbol
        if entry.side == "rhs" or isinstance(expr, ast.AugAssign):
            return text
        return f"{entry.symbol} = {text}"

    def _source_segment_code(self, node: ast.AST) -> str | None:
        """node's exact source text, joined onto one line; None if it has no position."""
        text = ast.get_source_segment(self.source_code, node)
        return " ".join(line.strip() for line in text.splitlines()) if text is not None else None

    def _import_code(self, entry: TableEntry) -> str:
        """Import entries have synthetic recipes: m (the root), Attribute(m, a) (a member), Name(a) (an `as` alias)."""
        match entry.expr:
            case None:
                return f"import {entry.symbol}"
            case ast.Attribute(value=ast.Name(id=receiver), attr=attr):
                return f"from {receiver} import {attr}"
            case ast.Name(id=name):
                parent = self.table.get(entry.parents[0]) if entry.parents else None
                if parent is not None and isinstance(parent.expr, ast.Attribute):
                    return f"from {parent.expr.value.id} import {name} as {entry.symbol}"
                return f"import {name} as {entry.symbol}"
        return entry.symbol

    def _run_tarjan(self, root: Key) -> Iterator[list[Key]]:
        """
        Yields the strongly connected groups of unresolved entries reachable from root, parents before children.
        Iterative (a long chain would hit the recursion limit). Resolved entries are leaves: never pushed.
        Each group is yielded the moment its root closes, nothing is stored, and the caller resolves it
        before the walk resumes.
        """
        if self.table[root].resolved:
            return
        index: dict[Key, int] = {root: 0}
        low: dict[Key, int] = {root: 0}
        stack, on_stack = [root], {root}
        work = [(root, self._unresolved_parents_tarjan(root), 0)]   # (key, its unresolved parents, next parent to visit)
        while work:
            u, parents, i = work[-1]
            if i < len(parents):
                work[-1] = (u, parents, i + 1)
                v = parents[i]
                if v not in index:
                    index[v] = low[v] = len(index)
                    stack.append(v); on_stack.add(v)
                    work.append((v, self._unresolved_parents_tarjan(v), 0))
                elif v in on_stack:
                    low[u] = min(low[u], index[v])
                continue
            work.pop()
            if work:   # pass u's low up to its DFS parent
                parent = work[-1][0]
                low[parent] = min(low[parent], low[u])
            if low[u] == index[u]:
                scc = []
                while True:
                    w = stack.pop(); on_stack.discard(w)
                    scc.append(w)
                    if w == u:
                        break
                yield scc   # popped deepest first: closest to the parents first

    def _unresolved_parents_tarjan(self, key: Key) -> list[Key]:
        return [p for p in self.table[key].parents if p in self.table and not self.table[p].resolved]

    def _resolve_scc_tarjan(self, keys: list[Key]) -> tuple[Key, Request] | None:
        """
        Evaluates one group, once or until stable if it's a cycle, then marks it resolved.
        A cycle starts from its members' current types (bottom, Unknown = {}) and grows: each member reads the
        others' latest types. Returns (key, Request) if the evaluator asked for something; the types written so
        far stay, they are below the fixed point, so the rerun carries on upward from them.
        """
        cyclic = len(keys) > 1 or keys[0] in self.table[keys[0]].parents
        for _ in range(self.MAX_CYCLE_PASSES if cyclic else 1):
            changed = False
            for key in keys:
                entry = self.table[key]
                result = self.expr_evaluator.evaluate(entry, {p: self.table[p].type for p in entry.parents if p in self.table})
                if isinstance(result, Request):
                    return key, result
                changed |= result != entry.type
                entry.type = result
            if not changed:
                break
        else:
            if cyclic:
                logging.getLogger(__name__).warning("cycle %s did not settle in %d passes", keys, self.MAX_CYCLE_PASSES)
        for key in keys:
            self.table[key].resolved = True
        return None

    def _add_dynamic_link_tarjan(self, key: Key, request: Request) -> None:
        """
        A link found during Tarjan: looks up the evaluator's member requests in the namespace table (along the MRO)
        and writes the keys found into the entry's parents, so the rerun walks them and the trace shows them.
        Must add a parent or settle the request (Unknown), or get_type would rerun forever.
        Not built: needs the MRO walk, and the mock evaluator never asks.
        """
        raise NotImplementedError("member lookups through the namespace table")
    
