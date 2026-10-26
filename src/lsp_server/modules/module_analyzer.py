import ast
from collections import deque

from type_lattice import LatticeValue
from lexical_environment import Environment
from provenance_table import ProvenanceTableEntry
from control_flow_graph import ControlFlowGraph
from cfg_generator import CFGGenerator

class ModuleAnalyzer():
    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.env: Environment | None = None   # built in process_file, once the source is read
        self.provenance_table: dict[tuple[int, int], ProvenanceTableEntry] = {
            # (col, lineo) = ProvenanceTableEntry(type, parents: list[ProvenanceTableEntry])
        }

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
        return

    def evalute_expr() -> LatticeValue:
        return
    
if __name__=="__main__":
    module_analyzer = ModuleAnalyzer("tests/cfg_graph_test_cases/try_finally.py")
    module_analyzer.process_file()
    