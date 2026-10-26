import ast
from collections import deque

from type_lattice import LatticeValue
from lexical_environment import Environment, Key
from provenance_table import Origin, ProvenanceTable, TableEntry
from control_flow_graph import ControlFlowGraph, Node
from cfg_generator import CFGGenerator
from ast_node_wrappers import ElementOf, ForEntry

class ModuleAnalyzer():
    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.env: Environment | None = None   # built in process_file, once the source is read
        self.provenance_table: ProvenanceTable = {}   # Key -> TableEntry

        self.import_table: dict = {}

        self.cfg_generator: CFGGenerator | None = None
        self.cfg: ControlFlowGraph | None = None

        self.nested: set[int] = set()   # ids of ast nodes inside a def/class body (skipped for now)

    def process_file(self) -> None:
        with open(self.filepath, "r", encoding="utf-8") as f:
            source_code = f.read()
            module_ast = ast.parse(source_code, filename=self.filepath)

        self.env = Environment(source_code, self.filepath)   # symtable parses the source text; the path is only for error messages

        # builtins are implicit imports: `from builtins import name`
        builtins_module = self._module_entry("builtins")
        for name in self.env.builtin:
            self.provenance_table[("builtins", name)] = TableEntry(name, None, parents=[builtins_module])

        for defn in ast.walk(module_ast):
            if isinstance(defn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.nested.update(id(n) for stmt in defn.body for n in ast.walk(stmt))

        self.cfg = ControlFlowGraph()
        self.cfg_generator = CFGGenerator(module_ast, self.cfg)
        self.cfg_generator.make_graph()
        self.cfg._pretty_print()

        adj = self.cfg.create_adjacency_list()
        indeg = self.cfg.count_indeg()

        # Topo Sort Traversal
        q = deque([u for u in adj if indeg[u]==0])
        while q:
            u = q.popleft()
            self.analyze_code_block(u)
            for v in adj[u]:
                indeg[v]-=1
                if indeg[v]==0:
                    q.append(v)  
        return
    
    def analyze_code_block(self, node: Node) -> None:
        for stmt in getattr(node.ast_node, "body", None) or []:
            if id(stmt) in self.nested or any(id(c) in self.nested for c in ast.iter_child_nodes(stmt)):
                continue   # function and class bodies: later
            self.parse_expr(stmt, iterates=isinstance(node.ast_node, ForEntry))

    def parse_expr(self, stmt: ast.stmt, iterates: bool = False) -> None:
        """
        parse_expr() builds the provenance entries for one statement: use entries for the
        names the RHS reads, then a definition entry for each LHS target, with edges from
        the RHS reads to the LHS definition. It never evaluates: types are pulled later.

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

        Statements (module level; function and class bodies skipped)

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
        │ class A(B):                     │ the CFG desugars it to Assign: reads of bases, keywords, decorators → def A (recipe the ClassDef). Body skipped │
        │                                 │ for now                                                                                                         │
        ├─────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ def f(...)                      │ the CFG desugars it to Assign: reads of decorators and defaults → def f (recipe the FunctionDef). Body skipped  │
        │                                 │ for now                                                                                                         │
        └─────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

        Control flow (from the CFG's entry nodes)

        ┌───────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────┐
        │         Construct         │                                        Entries                                         │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ for x in it:              │ the CFG desugars it to Assign(x, it): reads of it → def x (recipe ElementOf(it, None)) │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ except E as e:            │ desugared: read E → def e                                                              │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ match s: / case ... if g: │ reads of s, g (capture patterns deferred)                                              │
        └───────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────┘

        IMPORTS (not built yet, see below)
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
        from m import *             m (IMPORT) ← m.*                             bound: none; unresolved reads fall back to m.* (latest first), then builtins
        builtins (len)              builtins (IMPORT) ← builtins.len             bound: len

          - Every name in the import line gets its own entry, keyed at its position.
          - Only the root (m, ., .., builtins) is IMPORT; the resolver turns it into a module.
          - x.y means member y of x (recipe: an Attribute whose receiver is the parent).
            If x is a module and y isn't in it, the submodule x.y is tried.
          - k (from `as k`) has no recipe: its type is the type of the entry it renames.
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

          - IMPORTS above. The code currently makes one shared ("module", name) entry per
            module, not bound and with no position, and binds each imported name to it:
            import m → m (IMPORT); from m import a as k → k (recipe the alias). The
            path segments (m, m.a in `from m.a import b`) get no entries of their own,
            and `from m import *` is skipped.
          - Relative roots are not resolved to absolute module names (needs ImportResolver).
          - if t: / while t: → reads of t. The CFG's IfElseEntry/WhileLoopEntry carry no
            body, so the test never reaches parse_expr.
          - def f / class A targets are keyed at the def/class keyword, not the name
            (the CFG builds that Assign at the keyword's column).
          - Branches: clone the env per arm; at a merge, a JOIN entry ("join", node_id, x)
            for each name whose key differs between the arms, missing in one arm → A | Unbound.
          - Class Exit: the class body's {member: key} + bases → GlobalNamespaceTable, row
            keyed by the class's definition key. Needs push_scope/pop_scope for the body.
          - Module Exit: the global scope {name: key} → GlobalNamespaceTable, row keyed by
            the module name.
          - Function bodies: params (PARAMETER, resolved if annotated or a literal
            default), return_stmts collected via a stack of function entries.
        """
        match stmt:
            case ast.Assign(targets=targets, value=value) if iterates:
                # desugared `for x in it`: x is an element of it
                parents = self._reads(value)
                for target in targets:
                    self._define(target, ElementOf(value, None), parents)

            case ast.Assign(targets=targets, value=ast.FunctionDef() | ast.ClassDef() as defn):
                # desugared `def f` / `class A(B)`: only decorators, bases and defaults run here
                parents = [key for expr in self._evaluated_at_definition(defn) for key in self._reads(expr)]
                for target in targets:
                    self._define(target, defn, parents)

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
                # import m: m is the module itself. `import a.b` binds a, `import a.b as k` binds k to a.b
                for alias in names:
                    name = alias.asname or alias.name.split(".")[0]
                    module = self._module_entry(alias.name if alias.asname else name)
                    self._bind(name, self._key(alias), TableEntry(name, alias, origin=Origin.IMPORT, parents=[module]))

            case ast.ImportFrom(module=module, names=names, level=level):
                # from m import a: a is member a of m
                source = self._module_entry("." * level + (module or ""))
                for alias in names:
                    if alias.name == "*":
                        continue
                    name = alias.asname or alias.name
                    self._bind(name, self._key(alias), TableEntry(name, alias, parents=[source]))

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

    def _module_entry(self, module: str) -> Key:
        """Hidden entry for a module, shared by every import of it. Never bound in the env:
        after `from m import a`, m is not a usable name."""
        key = ("module", module)
        if key not in self.provenance_table:
            self.provenance_table[key] = TableEntry(module, None, origin=Origin.IMPORT)
        return key

    def _evaluated_at_definition(self, defn: ast.FunctionDef | ast.ClassDef) -> list[ast.expr]:
        if isinstance(defn, ast.ClassDef):
            return defn.decorator_list + defn.bases + [k.value for k in defn.keywords]
        return defn.decorator_list + defn.args.defaults + [d for d in defn.args.kw_defaults if d is not None]

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

if __name__=="__main__":
    module_analyzer = ModuleAnalyzer("tests/cfg_graph_test_cases/try_finally.py")
    module_analyzer.process_file()
