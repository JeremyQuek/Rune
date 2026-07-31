import ast
from collections import deque

from control_flow_graph import ControlFlowGraph
from ast_walker import ASTWalker

class ModuleAnalyzer():
    def __init__(self, filepath):
        self.filepath = filepath
    
    def process_file(self):
        with open(self.filepath, "r", encoding="utf-8") as f:
            source_code = f.read()
            module_ast = ast.parse(source_code, filename=self.filepath)

        self.cfg = ControlFlowGraph()
        self.ast_walker = ASTWalker(module_ast, self.cfg)
        self.ast_walker.traverse_and_create_cfg()
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
    
if __name__=="__main__":
    module_analyzer = ModuleAnalyzer("tests/try_finally.py")
    module_analyzer.process_file()
    