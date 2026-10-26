import ast
from collections import deque

from type_lattice import LatticeValue
from lexical_environment import Environment
from provenance_table import ProvenanceTable
from control_flow_graph import ControlFlowGraph
from cfg_generator import CFGGenerator

class ModuleAnalyzer():
    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.env: Environment | None = None   # built in process_file, once the source is read
        self.provenance_table: ProvenanceTable = {}   # Key -> TableEntry

        self.import_table: dict = {}

        self.cfg_generator: CFGGenerator | None = None
        self.cfg: ControlFlowGraph | None = None

    def process_file(self) -> None:
        with open(self.filepath, "r", encoding="utf-8") as f:
            source_code = f.read()
            module_ast = ast.parse(source_code, filename=self.filepath)

        self.env = Environment(source_code, self.filepath)   # symtable parses the source text; the path is only for error messages

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
            # processing step
            pass
            for v in adj[u]:
                indeg[v]-=1
                if indeg[v]==0:
                    q.append(v)  
        return
    
    def analyze_code_block(self) -> None:
        pass

    def parse_expr(stmt: ast.AST):
        """
        Parse_expr() extracts Name operands from the LHS expression, and draws edges from the ProvenanceTableEntries of RHS target(s) to the LHS operands

        General rules

        ┌────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
        │        Rule        │                                                                                                                                                               │
        ├────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Entries are        │ names only: Load = a read (use entry), Store = a definition                                                                                                   │
        │ created for        │                                                                                                                                                               │
        ├────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Literals           │ no entry; evaluate types them at resolve time                                                                                                                 │
        ├────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Order              │ reads (RHS) first, then definitions (LHS) + assign. Order trap: x = x + 1                                                                                     │
        ├────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Use entry          │ expr = itself, parents = [which(x).key]                                                                                                                       │
        ├────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Definition entry   │ expr = the RHS (the recipe), parents = that statement's use keys                                                                                              │
        ├────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Resolved at build  │ a bare x: T, an annotated parameter, and x = <lone Constant> (x = 5 → int, no dunder needed; to confirm). Everything else resolved=False, type ⊥.             │
        │ time               │                                                                                                                                                               │
        ├────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ Builtins           │ prefilled IMPORT entries keyed ("builtins", name)                                                                                                             │
        └────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

        Expressions: what counts as a read

        ┌───────────────────────────────────────┬───────────────┬───────────────────────────────────────┐
        │                 Code                  │     Reads     │                 Notes                 │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ a + b, -a, a < b < c, a or b, not a   │ a, b, c       │ operators aren't operands             │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ a if x else b                         │ a, x, b       │ the condition too                     │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ [a, b], {a, b}, (a, b), {a: b}, {**d} │ a, b, d       │                                       │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ a.b, a.b.c, a.b().c                   │ one symbol    │ parent = longest bound prefix         │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ a[i], a[1:j]                          │ a, i, j       │                                       │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ f(a, k=b, *c, **d)                    │ f, a, b, c, d │                                       │
        ├───────────────────────────────────────┼───────────────┼───────────────────────────────────────┤
        │ (a.f)(x) / a.f(x)                     │ a.f, x        │ the callee chain + args               │
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

        Statements (module level; functions skipped)

        ┌───────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
        │           Statement           │                                                                      Entries                                                                       │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ x = e                         │ reads of e → def x (recipe e)                                                                                                                      │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ x = y = e                     │ reads of e → def x, def y                                                                                                                          │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ x, *y = e                     │ reads of e → def x, def y (recipe "element i of e" / "rest of e")                                                                                  │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ x: T                          │ def x, resolved T                                                                                                                                  │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ x: T = e                      │ reads of e → def x (the value decides)                                                                                                             │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ x += e                        │ read x + reads of e → def x                                                                                                                        │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ a.b = e                       │ reads of e → def of the symbol "a.b", bound in a's scope. Never writes to the class table (one instance, not the class)                            │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ a[i] = e                      │ reads of e, a, i; no definition (it's a mutation)                                                                                                  │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ e (a bare expression          │ reads only (xs.append(1) is reads only)                                                                                                            │
        │ statement)                    │                                                                                                                                                    │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ import m, import m.n as k     │ def m / k, IMPORT origin, keyed at the alias node                                                                                                  │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ from m import a as b          │ def b, IMPORT                                                                                                                                      │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ del x                         │ nothing for now                                                                                                                                    │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ class A(B):                   │ the CFG desugars it to Assign: read B → def A. The body is its own scope. At the class's Exit, write {member: key} and the bases to                │
        │                               │ GlobalClassTable["mod.A"]                                                                                                                          │
        ├───────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
        │ def f(...)                    │ skipped for now (def f only)                                                                                                                       │
        └───────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

        Control flow (from the CFG's entry nodes)

        ┌───────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────┐
        │         Construct         │                                        Entries                                         │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ if t:, while t:           │ reads of t                                                                             │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ for x in it:              │ the CFG desugars it to Assign(x, it): reads of it → def x (recipe "element of it")     │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ except E as e:            │ desugared: read E → def e                                                              │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ match s: / case ... if g: │ reads of s, g (capture patterns deferred)                                              │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ Branch merge              │ a JOIN entry ("join", node_id, x) for each name whose key differs between the branches │
        ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
        │ Module Exit               │ snapshot the global scope → GlobalExportTable["mod"]                                   │
        └───────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────┘

        Attribute chains (a.b, a.b.c) are a single symbol

          - lhs  a.b = e    def entry with symbol "a.b", bound in a's scope (symtable
                            doesn't know "a.b", so the scope comes from the root name a).
          - writes          assigning a prefix drops every longer chain:
                            a = ... drops "a.b", "a.b.c";  a.b = ... drops "a.b.c".
          - rhs  a.b.c      longest prefix bound in the env wins:
                            which("a.b.c"), else which("a.b"), else which("a").
                            The rest of the chain (.c, or .b.c) is looked up through
                            the class table at resolve time.
          - inside a chain  calls/indexes stay part of the symbol (a.f(x)[i].c);
                            x and i are separate reads.
          - rebinding       x = a.b; x = 5 only rebinds x, "a.b" keeps its binding.
          - mutation        xs.append(1) is reads only: types are fixed at creation.
        """
    
if __name__=="__main__":
    module_analyzer = ModuleAnalyzer("tests/cfg_graph_test_cases/try_finally.py")
    module_analyzer.process_file()
    