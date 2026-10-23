import ast
from collections import deque

from control_flow_graph import ControlFlowGraph
from cfg_generator import CFGGenerator

class ModuleAnalyzer():
    def __init__(self, filepath):
        self.filepath = filepath
    
    def process_file(self):
        with open(self.filepath, "r", encoding="utf-8") as f:
            source_code = f.read()
            module_ast = ast.parse(source_code, filename=self.filepath)

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
    
    def analyze_code_block(self):
        pass
    
if __name__=="__main__":
    module_analyzer = ModuleAnalyzer("tests/cfg_graph_test_cases/try_finally.py")
    module_analyzer.process_file()
    