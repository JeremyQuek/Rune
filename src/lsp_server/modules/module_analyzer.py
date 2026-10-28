import ast
import io
import re
import tokenize
from collections import deque

from type_lattice import LatticeValue
from lexical_environment import Environment, Key, join
from provenance_table import Origin, ProvenanceTable, TableEntry
from control_flow_graph import ControlFlowGraph, Node
from ast_node_wrappers import CaughtAs, ClassDefinitionEntry, ElementOf, EnteredFrom, Exit, ExitKind, ForEntry, ParameterOf

class ModuleAnalyzer():
    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.env: Environment | None = None   # built in process_file, once the source is read
        self.provenance_table: ProvenanceTable = {}   # Key -> TableEntry

        self.import_table: dict = {}

        self.cfg: ControlFlowGraph | None = None
        self.source_lines: list[str] = []

    def process_file(self) -> None:
        with open(self.filepath, "r", encoding="utf-8") as f:
            source_code = f.read()
            module_ast = ast.parse(source_code, filename=self.filepath)
        self.source_lines = source_code.splitlines()

        self.env = Environment(source_code, self.filepath)   # symtable parses the source text; the path is only for error messages

        # builtins are implicit imports: `from builtins import name`
        builtins_module = self._module_entry("builtins")
        for name in self.env.builtin:
            self.provenance_table[("builtins", name)] = TableEntry(name, self._member_recipe("builtins", name),
                                                                    parents=[builtins_module])

        self.cfg = ControlFlowGraph(module_ast)
        self.cfg._pretty_print()
        self._traverse_graph()

    def _traverse_graph(self):
        # Topologically traverse the graph
        adj = self.cfg.create_adjacency_list()
        indeg = self.cfg.count_indeg()

        q = deque([u for u in adj if indeg[u]==0])
        for u in q:
            u.incoming_environments.append(self.env)   # the roots start from the module's environment
        
        while q:
            u = q.popleft()

            # Get the ID of the node
            node_id = self.cfg._node_ids[id(u)]

            # Combine incoming envs such as on join branches
            u.enviroment = join(u.incoming_environments, lambda x, keys: self._join_entry(node_id, x, keys))
            u.incoming_environments = []
            self.env = u.enviroment

            if isinstance(u.ast_node, Exit) and u.ast_node.kind == ExitKind.CLASS_DEFINITION:
                self.env.pop_scope()   # leaving the class body
            if u in self.cfg.function_bodies:
                defn = self.cfg.function_bodies[u]   # entering a function body: its env is the def's clone, no pop needed
                self.env.push_scope(defn.name, defn.lineno)

            self._analyze_code_block(u)

            if isinstance(u.ast_node, ClassDefinitionEntry):
                defn = u.ast_node.body[0].value   # the class name is bound in the enclosing scope, then the body runs in its own
                self.env.push_scope(defn.name, defn.lineno)

            children = adj[u]
            for v in children:
                # Share a ref of the env to a single child else clone the env to all children
                v.incoming_environments.append(u.enviroment if len(children) == 1 else u.enviroment.clone())
                indeg[v]-=1
                if indeg[v]==0:
                    q.append(v)
        return
    
    def _analyze_code_block(self, node: Node) -> None:
        for stmt in getattr(node.ast_node, "body", None) or []:
            self._parse_expr(stmt, iterates=isinstance(node.ast_node, ForEntry))

    def _parse_expr(self, stmt: ast.stmt, iterates: bool = False) -> None:
        """
        parse_expr() builds the file variable dependencies into the provenance table.

        General rules

        ┌──────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
        │           Rule           │                                                        Meaning                                                         │
        ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Entries are created for  │ names, attribute links (a, a.b, a.b.c) and import segments. Load = a read (use entry), Store = a definition            │
        ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Literals                 │ no entry; evaluate types them at resolve time                                                                          │
        ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Order                    │ reads (RHS) first, then definitions (LHS) + env.assign. Order trap: in x = x + 1 the RHS x is the old x                │
        ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Use entry                │ expr = itself. A name's parent is which(x).key; an attribute link's parent is described under ATTRIBUTES               │
        ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Definition entry         │ expr = the RHS (the recipe), parents = that statement's read keys                                                      │
        ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Keys                     │ (col, line) of the name itself, so the hover finds it. Attribute links are keyed at the attribute's name (b in a.b).   │
        │                          │ Only builtins have non-positional keys ("builtins", name), because they don't appear in the source                     │
        ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Resolved at build time   │ a bare x: T, an annotated parameter, and x = <lone Constant> (x = 5 → int, no dunder needed; to confirm). Everything   │
        │                          │ else resolved=False, type ⊥                                                                                            │
        ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Builtins                 │ prefilled entries keyed ("builtins", name): builtins (IMPORT) ← builtins.len, bound as len through the env's builtin   │
        │                          │ fallback                                                                                                               │
        └──────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

        Expressions: what counts as a read

        ┌───────────────────────────────────────┬───────────────┬───────────────────────────────────────┐
        │                  Code                 │     Reads     │                 Notes                 │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ a + b, -a, a < b < c, a or b, not a   │ a, b, c       │ operators aren't operands             │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ a if x else b                         │ a, x, b       │ the condition too                     │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ [a, b], {a, b}, (a, b), {a: b}, {**d} │ a, b, d       │                                       │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ a.b.c                                 │ a, a.b, a.b.c │ one entry per link, keyed at its name │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ a[i], a[1:j]                          │ a, i, j       │                                       │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ f(a, k=b, *c, **d)                    │ f, a, b, c, d │                                       │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ a.f(x)                                │ a, a.f, x     │ the callee chain + args               │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ f"{a} {b!r:>{w}}"                     │ a, b, w       │ including the format specs            │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ [x for x in xs if x > n]              │ xs, n         │ skip names bound by the comprehension │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ lambda y: y + z                       │ z             │ skip parameters                       │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ (y := e)                              │ reads of e    │ definition of y                       │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ await, yield                          │ their operand │ type is Unknown later                 │
        └───────────────────────────────────────┴───────────────┴───────────────────────────────────────┘

        Statements

        ┌─────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
        │            Statement            │                                                     Entries                                                     │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ x = e                           │ reads of e → def x (recipe e)                                                                                   │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ x = y = e                       │ reads of e → def x, def y                                                                                       │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ x, *y = e                       │ reads of e → def x, def y (recipe ElementOf(e, i) / ElementOf(e, i, rest=True))                                 │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ x: T                            │ def x, resolved T                                                                                               │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ x: T = e                        │ reads of e → def x (the value decides)                                                                          │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ x += e                          │ reads of e → def x with parents [old x's definition] + reads of e, recipe = the AugAssign statement. No read    │
        │                                 │ entry for x: it would share the def's key                                                                       │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ a.b = e                         │ reads of e, read a → def of "a.b" keyed at b, bound in a's scope. Never writes to a class row (one instance,    │
        │                                 │ not the class)                                                                                                  │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ a[i] = e                        │ reads of e, a, i; no definition (it's a mutation)                                                               │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ e (a bare expression statement) │ reads only (xs.append(1) is reads only)                                                                         │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ import ..., from ... import ... │ see IMPORTS                                                                                                     │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ del x                           │ nothing for now                                                                                                 │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ class A(B):                     │ the CFG desugars it to Assign: reads of bases, keywords, decorators → def A (recipe the ClassDef), keyed at the │
        │                                 │ name A (found in the source: the AST stores it as a string). Body runs in the class's own scope                 │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ def f(...) / async def f(...)   │ the CFG desugars it to Assign: reads of decorators and defaults → def f (recipe the FunctionDef), keyed at the  │
        │                                 │ name f. The body runs on a clone of the env at the def (the def entry branches), in the function's own scope    │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ global a, b / nonlocal a, b     │ a read of each name (parent: the definition it refers to), keyed at the name, found in the source               │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ def f(a: T, b=e)                │ the CFG binds each param at the start of the body: def a (recipe ParameterOf, origin PARAMETER), keyed at       │
        │                                 │ the name. Annotated → resolved T; else a literal default → its type; else a name default → parent: its          │
        │                                 │ read on the def line                                                                                            │
        └─────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

        Control flow (from the CFG's entry nodes)

        ┌───────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────┐
        │         Construct         │                                        Entries                                         │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ several children (branch) │ each child gets a clone of the env (one child: the same env)                           │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ several parents (merge)   │ the parents' envs are joined: a name whose keys differ gets                            │
        │                           │ one JOIN entry ("join", node_id, x); unbound in an arm → ("unbound", x)                │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ if / elif / while t:      │ the branch entry carries t: reads of t                                                 │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ for x in it:              │ the CFG desugars it to Assign(x, it): reads of it → def x (recipe ElementOf(it, None)) │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ except E as e:            │ desugared: read E → def e (recipe CaughtAs(E)), keyed at e, found after `as`           │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ with a as f:              │ the CFG flattens it: read a → def f (recipe EnteredFrom(a)), then the body             │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ match s: / case ... if g: │ reads of s, g (capture patterns deferred)                                              │
        └───────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────┘

        IMPORTS
        import m                    m (IMPORT)                                   bound: m
        import m as k               m (IMPORT) ← k                               bound: k
        import m.a                  m (IMPORT) ← m.a                             bound: m
        import m.a.b                m (IMPORT) ← m.a ← m.a.b                     bound: m   (later m.a.b is a chain read)
        import m.a.b as k           m (IMPORT) ← m.a ← m.a.b ← k                 bound: k
        from m import a             m (IMPORT) ← m.a                             bound: a
        from m import a as k        m (IMPORT) ← m.a ← k                         bound: k
        from m import a, b          m (IMPORT) ← m.a, m.b                        bound: a, b
        from m.a import b           m (IMPORT) ← m.a ← m.a.b                     bound: b
        from m.a import b as k      m (IMPORT) ← m.a ← m.a.b ← k                 bound: k
        from . import a             . (IMPORT) ← .a                              bound: a
        from .m import a            . (IMPORT) ← .m ← .m.a                       bound: a
        from ..m import a           .. (IMPORT) ← ..m ← ..m.a                    bound: a
        from m import *             skipped for now
        builtins (len)              builtins (IMPORT) ← builtins.len             bound: len

          - Every name in the import line gets its own entry, keyed at its position.
          - Only the root (m, ., .., builtins) is IMPORT; the resolver turns it into a module.
          - x.y means member y of x (recipe: an Attribute whose receiver is the parent).
            If x is a module and y isn't in it, the submodule x.y is tried.
          - k (from `as k`) has the renamed name as its recipe (m, m.a, a), with the entry it renames as parent.
          - bound is the only name the code can then use; the others exist for hover and the trace.

        ATTRIBUTES: one entry per link

          - rhs  a.b.c      entries for a, a.b and a.b.c, each keyed at its own name
                            (b in a.b: end_col_offset - len(attr)), so hovering a and
                            .b show different things. Parents:
                              a      which("a")
                              a.b    which("a.b") if a.b was assigned, else the a entry
                              a.b.c  which("a.b.c") if assigned, else the a.b entry
                            The statement's parents get only the outermost link.
          - lhs  a.b = e    a is a read; "a.b" is a def keyed at b, bound in a's scope
                            (symtable doesn't know "a.b", so the scope comes from a).
          - writes          assigning a prefix drops every longer chain:
                            a = ... drops "a.b", "a.b.c";  a.b = ... drops "a.b.c".
          - inside a chain  calls/indexes get no link of their own (a.f(x)[i].c:
                            links a, a.f, .c); x and i are separate reads.
          - rebinding       x = a.b; x = 5 only rebinds x, "a.b" keeps its binding.
          - mutation        xs.append(1) is reads only: types are fixed at creation.

        NOT BUILT YET (rules agreed, code doesn't follow them)

          - from m import *: m (IMPORT) ← m.*, bound: none; reads with no definition fall
            back to m.* (latest first), then builtins.
          - Relative roots (., ..) are resolved to a module by the ImportResolver, which
            needs the importing file.
          - Class Exit: the class body's {member: key} + bases → GlobalNamespaceTable, row
            keyed by the class's definition key. Needs push_scope/pop_scope for the body.
          - Module Exit: the global scope {name: key} → GlobalNamespaceTable, row keyed by
            the module name.
          - Function bodies: return_stmts on the def entry, and a free name with no binding at the def
            linked to its binding at the module exit (late binding).
          - Loops: the back edge isn't joined into the loop head (fixpoint).

        """
        match stmt:
            case ast.Assign(targets=targets, value=value) if iterates:
                # desugared `for x in it`: x is an element of it
                parents = self._reads(value)
                for target in targets:
                    self._define(target, ElementOf(value, None), parents)

            case ast.Assign(value=ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() as defn):
                # desugared `def f` / `class A(B)`: only decorators, bases and defaults run here
                parents = [key for expr in self._evaluated_at_definition(defn) for key in self._reads(expr)]
                [key] = self._get_declared_key_offset(defn)
                self._bind(defn.name, key, TableEntry(defn.name, defn, parents=parents))

            case ast.Assign(targets=[ast.Name(id=name) as target], value=ParameterOf(arg=arg, default=default) as param):
                # a parameter, bound at the start of the body: the annotation wins, else the default decides
                entry = TableEntry(name, param, origin=Origin.PARAMETER)
                if arg.annotation is not None:
                    entry.type, entry.resolved = LatticeValue.of(ast.unparse(arg.annotation)), True
                elif isinstance(default, ast.Constant):
                    entry.type, entry.resolved = LatticeValue.of(type(default.value).__name__), True
                elif isinstance(default, (ast.Name, ast.Attribute)):
                    entry.parents = [self._key(default)]   # its read on the def line
                self._bind(name, self._key(target), entry)

            case ast.Assign(value=CaughtAs() as caught):
                # desugared `except E as e`
                parents = self._reads(caught.type)
                [key] = self._get_declared_key_offset(caught)
                self._bind(caught.name, key, TableEntry(caught.name, caught, parents=parents))

            case ast.Assign(targets=targets, value=value):
                parents = self._reads(value)
                for target in targets:
                    self._define(target, value, parents)

            case ast.AnnAssign(target=ast.Name(id=name) as target, annotation=annotation, value=None):
                # bare declaration: the annotation is the type
                self._bind(name, self._key(target), TableEntry(name, None, resolved=True,
                                                               type=LatticeValue.of(ast.unparse(annotation))))

            case ast.AnnAssign(target=target, value=value) if value is not None:
                self._define(target, value, self._reads(value))   # the value decides

            case ast.AugAssign(target=target, value=value):
                # x += e: the recipe is the statement, parents = old x + reads of e.
                # No use entry for the old x: it would share the def's key.
                parents = self._reads(value)
                symbol = self._chain_symbol(target)
                if symbol is None:
                    self._reads(target)   # a[i] += e: mutation
                    return
                receiver = self._chain(target.value) if isinstance(target, ast.Attribute) else None
                previous = self.env.which(symbol)
                old = previous.key if previous else receiver
                self._bind(symbol, self._key(target), TableEntry(symbol, stmt,
                                                                 parents=([old] if old else []) + parents))

            case ast.Import(names=names):
                # import m.a.b: m (IMPORT) <- m.a <- m.a.b, binds m;  `as k` adds k <- m.a.b, binds k
                for alias in names:
                    parts = alias.name.split(".")
                    keys = self._path([(part, (alias.col_offset + len(".".join(parts[:i])) + (i > 0), alias.lineno))
                                       for i, part in enumerate(parts)])
                    if alias.asname:
                        self._bind(alias.asname, self._asname_key(alias),
                                   TableEntry(alias.asname, ast.Name(id=alias.name, ctx=ast.Load()), parents=[keys[-1]]))
                    else:
                        self.env.assign(parts[0], keys[0])

            case ast.ImportFrom(names=names):
                # from m.a import b as k: m (IMPORT) <- m.a <- m.a.b <- k, binds k
                path = self._from_path(stmt)
                receiver, receiver_key = path[-1][0], self._path(path)[-1]
                for alias in names:
                    if alias.name == "*":
                        continue   # star imports: later
                    key = self._key(alias)
                    self.provenance_table[key] = TableEntry(alias.name, self._member_recipe(receiver, alias.name),
                                                            parents=[receiver_key])
                    if alias.asname:
                        self._bind(alias.asname, self._asname_key(alias), TableEntry(alias.asname, ast.Name(id=alias.name, ctx=ast.Load()), parents=[key]))
                    else:
                        self.env.assign(alias.name, key)

            case ast.Global(names=names) | ast.Nonlocal(names=names):
                # global a / nonlocal a: a read of each name, so hovering it shows what it refers to
                for name, key in zip(names, self._get_declared_key_offset(stmt)):
                    col, line = key
                    node = ast.Name(id=name, ctx=ast.Load(), lineno=line, col_offset=col,
                                    end_lineno=line, end_col_offset=col + len(name))
                    definition = self.env.which(name)
                    self._use(name, key, node, definition.key if definition else None)

            case _:
                # bare expressions, match subjects/guards, return, raise, assert, ...: reads only
                for child in ast.iter_child_nodes(stmt):
                    if isinstance(child, ast.expr):
                        self._reads(child)

    # --------- Writes --------- #

    def _define(self, target: ast.expr, recipe: ast.AST, parents: list[Key]) -> None:
        match target:
            case ast.Tuple(elts=elts) | ast.List(elts=elts):
                for i, elt in enumerate(elts):
                    if isinstance(elt, ast.Starred):
                        self._define(elt.value, ElementOf(recipe, i, rest=True), parents)
                    else:
                        self._define(elt, ElementOf(recipe, i), parents)
            case _:
                symbol = self._chain_symbol(target)
                if symbol is None:
                    self._reads(target)   # a[i] = e, a.f().b = e: mutation, reads only
                    return
                if isinstance(target, ast.Attribute):
                    self._chain(target.value)   # a.b = e: a is a read, a.b the def
                entry = TableEntry(symbol, recipe, parents=parents)
                if isinstance(recipe, ast.Constant):
                    entry.type, entry.resolved = LatticeValue.of(type(recipe.value).__name__), True
                self._bind(symbol, self._key(target), entry)

    def _bind(self, symbol: str, key: Key, entry: TableEntry) -> Key:
        self.provenance_table[key] = entry
        self.env.assign(symbol, key)
        return key

    def _join_entry(self, node_id: int, symbol: str, keys: list[Key | None]) -> Key:
        """The JOIN entry for symbol at merge node node_id; None (unbound in an arm) → ("unbound", symbol)."""
        parents = []
        for key in keys:
            if key is None:
                key = ("unbound", symbol)
                self.provenance_table.setdefault(key, TableEntry(symbol, None))
            parents.append(key)
        key = ("join", node_id, symbol)
        self.provenance_table[key] = TableEntry(symbol, None, parents=parents, origin=Origin.JOIN)
        return key

    def _module_entry(self, module: str) -> Key:
        """Non-positional entry for a module that doesn't appear in the source (builtins)."""
        key = ("module", module)
        if key not in self.provenance_table:
            self.provenance_table[key] = TableEntry(module, None, origin=Origin.IMPORT)
        return key

    # --------- Imports --------- #

    def _path(self, segments: list[tuple[str, Key]]) -> list[Key]:
        """m (IMPORT) <- m.a <- m.a.b: the root is the import, each later segment a member of the previous."""
        for i, (symbol, key) in enumerate(segments):
            if i == 0:
                self.provenance_table[key] = TableEntry(symbol, None, origin=Origin.IMPORT)
            else:
                receiver, receiver_key = segments[i - 1]
                self.provenance_table[key] = TableEntry(symbol, self._member_recipe(receiver, symbol),
                                                        parents=[receiver_key])
        return [key for _, key in segments]

    def _from_path(self, stmt: ast.ImportFrom) -> list[tuple[str, Key]]:
        """
        The `m.a` in `from m.a import b`, with positions: ImportFrom.module is a plain string,
        so they come from the source tokens. Leading dots are the root (`.`, `..`).
        """
        text = "\n".join(self.source_lines[stmt.lineno - 1:stmt.end_lineno])
        segments: list[tuple[str, Key]] = []
        started = named = False
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            position = (tok.start[1], stmt.lineno + tok.start[0] - 1)
            if not started:
                started = tok.type == tokenize.NAME and tok.string == "from" and position == self._key(stmt)
            elif tok.type == tokenize.NAME:
                if tok.string == "import":
                    break
                segments.append((tok.string, position))
                named = True
            elif tok.type == tokenize.OP and set(tok.string) == {"."} and not named:
                if segments:
                    segments[0] = (segments[0][0] + tok.string, segments[0][1])
                else:
                    segments.append((tok.string, position))
        return segments

    def _member_recipe(self, receiver: str, attr: str) -> ast.Attribute:
        """Member attr of the entry's parent (the receiver is the parent, not looked up by name)."""
        return ast.Attribute(value=ast.Name(id=receiver, ctx=ast.Load()), attr=attr, ctx=ast.Load())

    def _asname_key(self, alias: ast.alias) -> Key:
        return (alias.end_col_offset - len(alias.asname), alias.end_lineno)

    def _evaluated_at_definition(self, defn: ast.FunctionDef | ast.ClassDef) -> list[ast.expr]:
        if isinstance(defn, ast.ClassDef):
            return defn.decorator_list + defn.bases + [k.value for k in defn.keywords]
        return defn.decorator_list + defn.args.defaults + [d for d in defn.args.kw_defaults if d is not None]

    def _get_declared_key_offset(self, node: ast.AST) -> list[Key]:
        """
        Keys of names the AST stores as plain strings, with no position of their own,
        so they are found in the source line:
            def f / class A          the name after the keyword
            except E as e            the name after `as`, searched after E
            global a, b / nonlocal   each name in order, after the keyword
        """
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            line, start, patterns = node.lineno, node.col_offset, [rf"(?:def|class)\s+({node.name})\b"]
        elif isinstance(node, CaughtAs):
            line, start, patterns = node.type.end_lineno, node.type.end_col_offset, [rf"\bas\s+({node.name})\b"]
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            keyword = "global" if isinstance(node, ast.Global) else "nonlocal"
            line, start, patterns = node.lineno, node.col_offset + len(keyword), [rf"\b({name})\b" for name in node.names]
        else:
            raise TypeError(f"no declared names in {type(node).__name__}")

        text = self.source_lines[line - 1]
        keys = []
        for pattern in patterns:
            found = re.compile(pattern).search(text, start)
            keys.append((found.start(1), line))
            start = found.end(1)
        return keys

    # --------- Reads --------- #

    def _reads(self, expr: ast.AST, bound: frozenset[str] = frozenset()) -> list[Key]:
        """Use entries for every name/chain expr reads, in source order. Returns their keys
        (for a chain, only its outermost link)."""
        keys: list[Key] = []
        self._visit(expr, bound, keys)
        return keys

    def _visit(self, node: ast.AST, bound: frozenset[str], keys: list[Key]) -> None:
        match node:
            case ast.Name() | ast.Attribute():
                key = self._chain(node, bound, keys)
                if key is not None:
                    keys.append(key)

            case ast.NamedExpr(target=target, value=value):
                start = len(keys)
                self._visit(value, bound, keys)
                keys.append(self._bind(target.id, self._key(target), TableEntry(target.id, value, parents=keys[start:])))

            case ast.Lambda(args=args, body=body):
                for default in args.defaults + [d for d in args.kw_defaults if d is not None]:
                    self._visit(default, bound, keys)
                params = args.posonlyargs + args.args + args.kwonlyargs + [a for a in (args.vararg, args.kwarg) if a]
                self._visit(body, bound | {a.arg for a in params}, keys)

            case ast.ListComp(generators=gens) | ast.SetComp(generators=gens) | ast.GeneratorExp(generators=gens) \
                    | ast.DictComp(generators=gens):
                inner = bound
                for i, gen in enumerate(gens):
                    self._visit(gen.iter, bound if i == 0 else inner, keys)   # the first iterable runs outside
                    inner = inner | {n.id for n in ast.walk(gen.target) if isinstance(n, ast.Name)}
                    for cond in gen.ifs:
                        self._visit(cond, inner, keys)
                for elt in ([node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]):
                    self._visit(elt, inner, keys)

            case _:
                for child in ast.iter_child_nodes(node):
                    self._visit(child, bound, keys)

    # --------- Attribute chains --------- #

    def _chain(self, node: ast.expr, bound: frozenset[str] = frozenset(), keys: list[Key] | None = None) -> Key | None:
        """
        One use entry per link of a chain, so a.b.c gets entries for a, a.b and a.b.c,
        each keyed at its own name, so hovering a and .b show different things.
            a      parent: which("a")
            a.b    parent: which("a.b") if a.b was assigned, else the a entry
            a.b.c  parent: which("a.b.c") if assigned, else the a.b entry
        Calls and indexes inside the chain (a.f(x)[i].c) get no link of their own; their
        args are separate reads. Returns the outermost link's key (None: nothing to read).
        """
        keys = [] if keys is None else keys
        match node:
            case ast.Name(id=name):
                if name in bound:
                    return None
                definition = self.env.which(name)
                return self._use(name, self._key(node), node, definition.key if definition else None)

            case ast.Attribute(value=value):
                inner = self._chain(value, bound, keys)
                root, _ = self._spine(node)
                if isinstance(root, ast.Name) and root.id in bound:
                    return None   # [x.y for x in xs]: x.y is the comprehension's own
                symbol = self._chain_symbol(node)
                assigned = self.env.which(symbol) if symbol else None
                parent = assigned.key if assigned else inner
                return self._use(symbol or ast.unparse(node), self._key(node), node, parent)

            case ast.Call(func=func, args=args, keywords=keywords):
                inner = self._chain(func, bound, keys)
                for arg in args + [k.value for k in keywords]:
                    self._visit(arg, bound, keys)
                return inner

            case ast.Subscript(value=value, slice=index):
                inner = self._chain(value, bound, keys)
                self._visit(index, bound, keys)
                return inner

            case _:
                self._visit(node, bound, keys)   # "s".upper(), (a + b).c
                return None

    def _use(self, symbol: str, key: Key, node: ast.AST, parent: Key | None) -> Key:
        self.provenance_table[key] = TableEntry(symbol, node, parents=[parent] if parent else [])
        return key

    def _key(self, node: ast.AST) -> Key:
        """(col, line) of a name; for an attribute, of the attribute's own name (b in a.b)."""
        if isinstance(node, ast.Attribute):
            return (node.end_col_offset - len(node.attr), node.end_lineno)
        return (node.col_offset, node.lineno)

    def _spine(self, node: ast.expr) -> tuple[ast.expr, list[ast.expr]]:
        """a.f(x)[i].c -> (Name a, [.c, [i], (x), .f]): the root and the links above it, outermost first."""
        spine = []
        while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
            spine.append(node)
            node = node.func if isinstance(node, ast.Call) else node.value
        return node, spine

    def _chain_symbol(self, target: ast.expr) -> str | None:
        """x -> "x", a.b.c -> "a.b.c"; None when it isn't a plain name chain (a[i], a.f().b)."""
        root, spine = self._spine(target)
        if not isinstance(root, ast.Name) or not all(isinstance(part, ast.Attribute) for part in spine):
            return None
        return ".".join([root.id] + [part.attr for part in reversed(spine)])

# Test function
def visualize_file(analyzer: ModuleAnalyzer, path: str | None = None) -> str:
    """
    Debug view of the provenance table: the source file with every entry boxed at its
    (col, line), and an arrow from each parent to its child. Entries with no position
    (builtins, modules) sit in a column on the right; only the ones something points to
    are shown. Hover an entry to see its trace (parents, orange) and what uses it (cyan);
    click to pin. Writes the page to `path` (default: the temp dir) and opens it.
    """
    import html, json, pathlib, tempfile, webbrowser

    def kind(key: Key, entry: TableEntry) -> str:
        # synthetic member recipes (m.a, builtins.len) have no position
        if entry.origin == Origin.IMPORT or (isinstance(entry.expr, ast.Attribute) and getattr(entry.expr, "end_col_offset", None) is None):
            return "import"
        if isinstance(entry.expr, (ast.Name, ast.Attribute)) and getattr(entry.expr, "col_offset", None) is not None \
                and analyzer._key(entry.expr) == key:
            return "use"
        return "def"

    def describe(expr: ast.AST | None) -> str:
        match expr:
            case None:
                return ""
            case ElementOf(value=value, index=index, rest=rest):
                which = "the rest" if rest else ("an element" if index is None else f"element {index}")
                return f"{which} of {describe(value)}"
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                return f"def {expr.name}(...)"
            case ast.ClassDef():
                return f"class {expr.name}"
            case CaughtAs(type=caught):
                return f"an instance of {describe(caught)}"
            case EnteredFrom(value=value):
                return f"{describe(value)}.__enter__()"
        try:
            text = ast.unparse(expr)
        except Exception:
            text = type(expr).__name__
        return text if len(text) <= 120 else text[:117] + "..."

    table = analyzer.provenance_table
    referenced = {parent for entry in table.values() for parent in entry.parents}
    nodes = []
    for key, entry in table.items():
        positional = len(key) == 2 and all(isinstance(k, int) for k in key)
        if not positional and key not in referenced:
            continue   # the ~150 builtins nothing reads
        nodes.append({
            "id": json.dumps(list(key)),
            "pos": list(key) if positional else None,
            "symbol": entry.symbol,
            "label": entry.symbol.rsplit(".", 1)[-1] or entry.symbol,   # the token at the position: b in a.b
            "kind": kind(key, entry),
            "origin": entry.origin.name,
            "type": str(entry.type),
            "resolved": entry.resolved,
            "expr": describe(entry.expr),
            "parents": [json.dumps(list(parent)) for parent in entry.parents],
        })
    data = {"file": analyzer.filepath, "lines": analyzer.source_lines, "nodes": nodes}

    template = r"""<!doctype html>
        <html lang="en">
        <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Provenance: __TITLE__</title>
        <style>
        :root {
            --bg: #ffffff; --panel: #f6f7f9; --border: #d9dce1; --text: #1f2328; --muted: #6b7280;
            --code: #4b5563; --edge: #c3c8d0; --use: #2563eb; --def: #059669; --import: #7c3aed;
            --ext: #9ca3af; --trace: #ea580c; --usedby: #0891b2;
        }
        @media (prefers-color-scheme: dark) {
            :root:not([data-theme="light"]) {
            --bg: #0f1115; --panel: #171a21; --border: #2a2f3a; --text: #e6e8eb; --muted: #8b93a1;
            --code: #a3acb9; --edge: #39404d; --use: #60a5fa; --def: #34d399; --import: #a78bfa;
            --ext: #6b7280; --trace: #fb923c; --usedby: #22d3ee;
            }
        }
        :root[data-theme="dark"] {
            --bg: #0f1115; --panel: #171a21; --border: #2a2f3a; --text: #e6e8eb; --muted: #8b93a1;
            --code: #a3acb9; --edge: #39404d; --use: #60a5fa; --def: #34d399; --import: #a78bfa;
            --ext: #6b7280; --trace: #fb923c; --usedby: #22d3ee;
        }
        #theme { margin-left: auto; background: var(--panel); color: var(--text); border: 1px solid var(--border);
                 border-radius: 6px; padding: 3px 10px; font: inherit; cursor: pointer; }
        * { box-sizing: border-box; }
        body { margin: 0; background: var(--bg); color: var(--text);
                font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
        header { padding: 10px 16px; border-bottom: 1px solid var(--border); display: flex;
                gap: 16px; align-items: center; flex-wrap: wrap; }
        header h1 { font-size: 14px; margin: 0; font-weight: 600; }
        .legend { display: flex; gap: 12px; color: var(--muted); flex-wrap: wrap; }
        .legend span::before { content: ""; display: inline-block; width: 10px; height: 10px;
                                border-radius: 2px; margin-right: 4px; vertical-align: -1px;
                                border: 2px solid var(--c); }
        main { display: flex; height: calc(100vh - 45px); }
        #scroll { flex: 1; overflow: auto; }
        #canvas { position: relative; }
        pre { margin: 0; position: absolute; font: 13px/22px ui-monospace, SFMono-Regular, Menlo, monospace; }
        #nums { color: var(--muted); text-align: right; opacity: .6; }
        #code { color: var(--code); }
        svg { position: absolute; left: 0; top: 0; pointer-events: none; overflow: visible; }
        path.edge { fill: none; stroke: var(--edge); stroke-width: 1.2; }
        path.edge.trace { stroke: var(--trace); stroke-width: 2; }
        path.edge.usedby { stroke: var(--usedby); stroke-width: 2; }
        .mark { position: absolute; height: 22px; border: 1.5px solid var(--c); border-radius: 4px;
                cursor: pointer; background: color-mix(in srgb, var(--c) 10%, transparent); }
        .mark.use { --c: var(--use); } .mark.def { --c: var(--def); } .mark.import { --c: var(--import); }
        .mark.ext { --c: var(--ext); font: 12px/19px ui-monospace, Menlo, monospace; padding: 0 6px;
                    white-space: nowrap; color: var(--text); width: auto !important; }
        .dim .mark:not(.trace):not(.usedby):not(.self) { opacity: .25; }
        .dim path.edge:not(.trace):not(.usedby) { opacity: .25; }
        .mark.self { box-shadow: 0 0 0 2px var(--trace); }
        .mark.trace { --c: var(--trace); }
        .mark.usedby { --c: var(--usedby); }
        aside { width: 340px; border-left: 1px solid var(--border); background: var(--panel);
                padding: 14px 16px; overflow: auto; }
        aside h2 { font-size: 13px; margin: 0 0 10px; }
        dl { margin: 0; display: grid; grid-template-columns: 72px 1fr; gap: 6px 10px; }
        dt { color: var(--muted); } dd { margin: 0; font-family: ui-monospace, Menlo, monospace;
                                        word-break: break-word; }
        a { color: var(--use); cursor: pointer; text-decoration: none; } a:hover { text-decoration: underline; }
        .hint { color: var(--muted); }
        @media (max-width: 700px) { main { flex-direction: column; height: auto; }
                                    aside { width: auto; border-left: 0; border-top: 1px solid var(--border); } }
        </style>
        </head>
        <body>
        <header>
        <h1 id="title"></h1>
        <div class="legend">
            <span style="--c: var(--use)">use</span><span style="--c: var(--def)">def</span>
            <span style="--c: var(--import)">import</span><span style="--c: var(--ext)">no position</span>
            <span style="--c: var(--trace)">trace (parents)</span><span style="--c: var(--usedby)">used by</span>
        </div>
        <button id="theme" type="button"></button>
        </header>
        <main>
        <div id="scroll"><div id="canvas"><svg id="edges"></svg><pre id="nums"></pre><pre id="code"></pre></div></div>
        <aside id="panel"></aside>
        </main>
        <script type="application/json" id="data">__DATA__</script>
        <script>
        const data = JSON.parse(document.getElementById("data").textContent);

        // theme: auto (follows the OS) -> light -> dark, remembered across reloads when storage allows
        const themes = ["auto", "light", "dark"], themeButton = document.getElementById("theme");
        function applyTheme(theme) {
            if (theme === "auto") document.documentElement.removeAttribute("data-theme");
            else document.documentElement.dataset.theme = theme;
            themeButton.textContent = { auto: "◐ auto", light: "☀ light", dark: "☾ dark" }[theme];
            themeButton.dataset.theme = theme;
        }
        let savedTheme = "auto";
        try { savedTheme = localStorage.getItem("rune-theme") || "auto"; } catch (e) {}
        applyTheme(themes.includes(savedTheme) ? savedTheme : "auto");
        themeButton.addEventListener("click", () => {
            const next = themes[(themes.indexOf(themeButton.dataset.theme) + 1) % themes.length];
            applyTheme(next);
            try { localStorage.setItem("rune-theme", next); } catch (e) {}
        });
        const LH = 22, PAD = 16;
        const canvas = document.getElementById("canvas"), svg = document.getElementById("edges");
        const panel = document.getElementById("panel");
        document.getElementById("title").textContent =
        `${data.file} · ${data.nodes.filter(n => n.pos).length} entries in the source`;

        // character width of the code font
        const probe = document.createElement("pre");
        probe.style.cssText = "position:absolute;visibility:hidden;font:13px/22px ui-monospace,SFMono-Regular,Menlo,monospace";
        probe.textContent = "M".repeat(100);
        document.body.appendChild(probe);
        const CW = probe.getBoundingClientRect().width / 100;
        probe.remove();

        const nums = document.getElementById("nums"), code = document.getElementById("code");
        const numW = String(data.lines.length).length * CW;
        nums.textContent = data.lines.map((_, i) => i + 1).join("\n");
        nums.style.cssText = `left:${PAD}px;top:${PAD}px;width:${numW}px`;
        const codeX = PAD + numW + 16;
        code.textContent = data.lines.join("\n");
        code.style.cssText = `left:${codeX}px;top:${PAD}px`;

        // layout: positional entries over their token, the rest in a right-hand column
        const byId = new Map(data.nodes.map(n => [n.id, n]));
        const children = new Map(data.nodes.map(n => [n.id, []]));
        const maxLen = Math.max(20, ...data.lines.map(l => l.length));
        const extX = codeX + (maxLen + 10) * CW;
        let row = 0;
        for (const n of data.nodes) {
        if (n.pos) {
            n.x = codeX + n.pos[0] * CW - 2; n.y = PAD + (n.pos[1] - 1) * LH;
            n.w = Math.max(1, n.label.length) * CW + 4;
        } else {
            n.x = extX; n.y = PAD + row++ * LH * 1.4; n.w = (n.symbol.length + 2) * CW + 12;
        }
        for (const p of n.parents) if (children.has(p)) children.get(p).push(n.id);
        }
        const height = Math.max(PAD * 2 + data.lines.length * LH, PAD * 2 + row * LH * 1.4);
        const width = extX + 260;
        canvas.style.cssText = `width:${width}px;height:${height}px`;
        svg.setAttribute("width", width); svg.setAttribute("height", height);

        const NS = "http://www.w3.org/2000/svg";
        const edges = [];
        for (const n of data.nodes) {
        for (const p of n.parents) {
            const from = byId.get(p);
            if (!from) continue;
            const x1 = from.x + from.w / 2, y1 = from.y + LH / 2, x2 = n.x + n.w / 2, y2 = n.y + LH / 2;
            const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
            const off = Math.min(80, len * 0.3) + 8;
            const cx = (x1 + x2) / 2 + dy / len * off, cy = (y1 + y2) / 2 - dx / len * off;
            const path = document.createElementNS(NS, "path");
            path.setAttribute("d", `M${x1},${y1} Q${cx},${cy} ${x2},${y2}`);
            path.setAttribute("class", "edge");
            svg.appendChild(path);
            edges.push({ from: p, to: n.id, el: path });
        }
        }

        for (const n of data.nodes) {
        const el = document.createElement("div");
        el.className = `mark ${n.pos ? n.kind : "ext"}`;
        el.style.cssText = `left:${n.x}px;top:${n.y + (n.pos ? 0 : 1)}px;width:${n.w}px`;
        if (!n.pos) el.textContent = n.symbol;
        el.title = `${n.symbol}  ${n.id}`;
        el.addEventListener("mouseenter", () => { if (!pinned) select(n.id); });
        el.addEventListener("click", e => { e.stopPropagation(); pinned = pinned === n.id ? null : n.id; select(n.id); });
        canvas.appendChild(el);
        n.el = el;
        }

        function walk(start, next) {
        const seen = new Set(), stack = [...next(start)];
        while (stack.length) {
            const id = stack.pop();
            if (seen.has(id) || !byId.has(id)) continue;
            seen.add(id); stack.push(...next(id));
        }
        return seen;
        }

        let pinned = null;
        function select(id) {
        const n = byId.get(id);
        const trace = walk(id, x => byId.get(x)?.parents ?? []);
        const usedBy = walk(id, x => children.get(x) ?? []);
        document.body.classList.add("dim");
        for (const m of data.nodes) {
            m.el.classList.toggle("self", m.id === id);
            m.el.classList.toggle("trace", trace.has(m.id));
            m.el.classList.toggle("usedby", usedBy.has(m.id) && !trace.has(m.id));
        }
        for (const e of edges) {
            e.el.classList.toggle("trace", (trace.has(e.from) || e.from === id) && (trace.has(e.to) || e.to === id));
            e.el.classList.toggle("usedby", (usedBy.has(e.to)) && (usedBy.has(e.from) || e.from === id));
        }
        const link = x => byId.has(x) ? `<a data-id='${x}'>${esc(byId.get(x).symbol)} ${esc(x)}</a>` : `${esc(x)} (missing)`;
        panel.innerHTML = `<h2>${esc(n.symbol)}${pinned === id ? " · pinned" : ""}</h2><dl>
            <dt>key</dt><dd>${esc(n.id)}</dd>
            <dt>kind</dt><dd>${n.kind}</dd>
            <dt>origin</dt><dd>${n.origin}</dd>
            <dt>type</dt><dd>${esc(n.type)}${n.resolved ? " (resolved)" : " (unresolved)"}</dd>
            <dt>recipe</dt><dd>${esc(n.expr) || "—"}</dd>
            <dt>parents</dt><dd>${n.parents.map(link).join("<br>") || "—"}</dd>
            <dt>used by</dt><dd>${(children.get(id) ?? []).map(link).join("<br>") || "—"}</dd>
        </dl>`;
        panel.querySelectorAll("a[data-id]").forEach(a => a.addEventListener("click", () => {
            pinned = a.dataset.id; select(a.dataset.id);
            byId.get(a.dataset.id).el.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
        }));
        }
        function clear() {
        pinned = null; document.body.classList.remove("dim");
        for (const m of data.nodes) m.el.classList.remove("self", "trace", "usedby");
        for (const e of edges) e.el.classList.remove("trace", "usedby");
        panel.innerHTML = `<h2>Provenance table</h2><p class="hint">Hover an entry to see its trace
            (orange: what it was traced from) and what uses it (cyan). Click to pin, click empty space or
            press Esc to clear.</p><p class="hint">${data.nodes.length} entries shown, ${edges.length} edges.</p>`;
        }
        const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
        canvas.addEventListener("mouseleave", () => { if (!pinned) clear(); });
        document.getElementById("scroll").addEventListener("click", clear);
        document.addEventListener("keydown", e => { if (e.key === "Escape") clear(); });
        clear();
        </script>
        </body>
        </html>
        """

    name = pathlib.Path(analyzer.filepath).name
    page = template.replace("__TITLE__", html.escape(name)).replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    out = pathlib.Path(path) if path else pathlib.Path(tempfile.gettempdir()) / f"rune_{pathlib.Path(name).stem}.html"
    out.write_text(page, encoding="utf-8")
    webbrowser.open(out.as_uri())
    return str(out)

if __name__=="__main__":
    module_analyzer = ModuleAnalyzer("src/lsp_server/modules/simple_file_analyzer.py") 
    module_analyzer.process_file()

    visualize_file(module_analyzer)
