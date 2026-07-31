from control_flow_graph import ControlFlowGraph
from ast_walker import ASTWalker

class ModuleAnalyzer():
    def __init__(self, filepath):
        self.filepath = filepath
        self.cfg = ControlFlowGraph()
        self.ast_walker = ASTWalker(self.cfg, filepath)
        self.ast_walker.traverse_and_create_cfg()
        self.cfg._pretty_print()
        adj = self.cfg.create_adjacency_list()
        print(adj)
    
if __name__=="__main__":
    module_analyzer = ModuleAnalyzer("tests/try_catch.py")
    