import ast
from enum import Enum, auto
from collections import defaultdict

import ast_node_wrappers

class NodeType(Enum):
    MODULE_ENTRY = auto()
    BRANCH_ENTRY = auto()
    FUNCTION_DEFINITION = auto()
    CLASS_DEFINITION = auto()
    EXIT = auto()
    MODULE_BODY = auto()
    FUNCTION_BODY = auto()
    CLASS_BODY = auto()
    IF_BODY = auto()
    ELSE_BODY = auto()
    TRY_BODY = auto()
    EXCEPT_BODY = auto()
    FOR_BODY = auto()
    WHILE_BODY = auto()
    FINALLY_BODY = auto()
    CASE_BODY = auto()

# Boundary nodes mark where the lexical environment changes shape:
# a new scope starts (module, function) or gets cloned per branch.
BOUNDARY_TYPES = {
    NodeType.MODULE_ENTRY,
    NodeType.BRANCH_ENTRY,
    NodeType.FUNCTION_DEFINITION,
}

class Node():
    def __init__(self, node_type: NodeType, is_boundary: bool = False, ast_node = None, enviroment = None):
        self.node_type = node_type
        self.ast_node = ast_node
        self.is_boundary = is_boundary
        self.enviroment = enviroment
        self.next = []

    def __repr__(self):
        return self.node_type.name

class ControlFlowGraph():
    mapping= {
        ast.FunctionDef : NodeType.FUNCTION_DEFINITION,
        ast_node_wrappers.FunctionDefinitionEntry : NodeType.FUNCTION_DEFINITION,
        ast.ClassDef : NodeType.CLASS_DEFINITION,
        ast_node_wrappers.ClassDefinitionEntry : NodeType.CLASS_DEFINITION,
        ast_node_wrappers.ModuleEntry: NodeType.MODULE_ENTRY,
        # Branch decision nodes
        ast_node_wrappers.IfElseEntry: NodeType.BRANCH_ENTRY,
        ast_node_wrappers.ForLoopEntry: NodeType.BRANCH_ENTRY,
        ast_node_wrappers.WhileLoopEntry: NodeType.BRANCH_ENTRY,
        ast_node_wrappers.TryExceptBranchEntry: NodeType.BRANCH_ENTRY,
        ast_node_wrappers.MatchEntry: NodeType.BRANCH_ENTRY,
        # Arm entry nodes - same region as their Body counterpart
        ast_node_wrappers.ModuleBody: NodeType.MODULE_BODY,
        ast_node_wrappers.IfEntry: NodeType.IF_BODY,
        ast_node_wrappers.ElseEntry: NodeType.ELSE_BODY,
        ast_node_wrappers.ForEntry: NodeType.FOR_BODY,
        ast_node_wrappers.WhileEntry: NodeType.WHILE_BODY,
        ast_node_wrappers.TryEntry: NodeType.TRY_BODY,
        ast_node_wrappers.ExceptEntry: NodeType.EXCEPT_BODY,
        ast_node_wrappers.FinallyEntry: NodeType.FINALLY_BODY,
        ast_node_wrappers.CaseEntry: NodeType.CASE_BODY,
        ast_node_wrappers.Body: NodeType.MODULE_BODY,
        ast_node_wrappers.FunctionBody: NodeType.FUNCTION_BODY,
        ast_node_wrappers.ClassBody: NodeType.CLASS_BODY,
        ast_node_wrappers.IfBody: NodeType.IF_BODY,
        ast_node_wrappers.ElseBody: NodeType.ELSE_BODY,
        ast_node_wrappers.TryBody: NodeType.TRY_BODY,
        ast_node_wrappers.ExceptBody: NodeType.EXCEPT_BODY,
        ast_node_wrappers.ForBody: NodeType.FOR_BODY,
        ast_node_wrappers.WhileBody: NodeType.WHILE_BODY,
        ast_node_wrappers.FinallyBody: NodeType.FINALLY_BODY,
        ast_node_wrappers.CaseBody: NodeType.CASE_BODY,
        ast_node_wrappers.Exit: NodeType.EXIT,
        }

    def __init__(self):
        self.entry = Node(NodeType.MODULE_ENTRY, is_boundary=True)
        self.nodes = {self.entry: self.entry}
        self.edges=[]
        self.adj = defaultdict(list)
        self.indeg = defaultdict(int)

        # For pretty print
        self._id_counter = 0
        self._node_ids = {id(self.entry): 0}
    
    def insert(self, parent: ast.AST, child: ast.AST)->None:
        u = self.entry if parent is None else self._get_node(parent) 
        v = self._get_node(child)
        u.next.append(v)
        self.edges.append([u,v])
    
    def create_adjacency_list(self):
        for (u,v) in self.edges:
            self.adj[u].append(v)
        
        return self.adj
    
    def count_indeg(self): 
        for (u,v) in self.edges:
            self.indeg[v]+=1
            self.indeg[u]+=0 #Touch u
        return self.indeg

    def _get_node(self, ast_node: ast.AST) -> Node:
        if ast_node not in self.nodes:
            u = self._create_node(ast_node)
            self.nodes[ast_node] = u 
        else:
            u = self.nodes[ast_node]
        return u

    # returns a Node of the correct type
    def _create_node(self, ast_node: ast.AST) -> Node:
        node_type = self.mapping[type(ast_node)]
        node = Node(node_type, is_boundary=node_type in BOUNDARY_TYPES, ast_node=ast_node)

        # For pretty print
        self._id_counter += 1
        self._node_ids[id(node)] = self._id_counter
        return node
    
    """
    Prints the edge list in a format pasteable into 
    graphonline.top/create_graph_by_edge_list for visual debugging.
    """
    def _pretty_print(self):
        
        for u, v in self.edges:
            print(f"{self._label(u)}-{self._label(v)}")

    def _label(self, node: Node) -> str:
        nid = self._node_ids[id(node)]
        if node.ast_node is None:
            return f"Entry({nid})"
        if node.node_type == NodeType.EXIT:
            return f"{''.join(word.capitalize() for word in node.ast_node.kind.name.split('_'))}Exit({nid})"
        return node.ast_node.__class__.__name__ + f"({nid})"
       