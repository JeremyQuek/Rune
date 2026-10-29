from dataclasses import dataclass

from control_flow_graph import ControlFlowGraph, Node

@dataclass
class SCCNode():
    entry_node: Node
    exit_node: Node
    cluster_size: int 
    adj: dict[Node, list[Node]] #only loops edge, not point in or outside the scc
    next: list[SCCNode] = field(default_factory=list)
    
class CondensedGraph():
    def __init__(self):
        self.scc_adj_list: dict[SCCNode, list[SCCNode]] = None
    
    def run_tarjan(pass):
        pass