import ast
from collections import defaultdict

import ast_wrappers

class Node():
    def __init__(self, block = None, enviroment = None):
        self.block = block
        self.enviroment = enviroment
        self.next = []

    def __repr__(self):
        return self.__class__.__name__

# Special Nodes: Terminal Nodes Represent enviromental boundary nodesß
class TerminalNode(Node): pass

class ModuleEntryNode(TerminalNode): pass
class ModuleExitNode(TerminalNode):pass
class BranchEntryNode(TerminalNode): pass # - This needs to handle for!
class FunctionDefinitionNode(TerminalNode): pass # - This needs to handle function definition
class ClassDefinitionNode(Node): pass
class ExitNode(Node): pass

# Regular code nodes
class ModuleBodyNode(Node):pass
class FunctionBody(Node): pass
class ClassBodyNode(Node): pass
class IfBodyNode(Node): pass
class ElseBodyNode(Node): pass
class TryBodyNode(Node): pass
class ExceptBodyNode(Node): pass
class ForBodyNode(Node): pass
class WhileBodyNode(Node): pass
class FinallyBodyNode(Node): pass

class ControlFlowGraph():
    mapping= {
        ast.FunctionDef : FunctionDefinitionNode,
        ast_wrappers.FunctionDefinitionEntry : FunctionDefinitionNode,
        ast.ClassDef : ClassDefinitionNode,
        ast_wrappers.ClassDefinitionEntry : ClassDefinitionNode,
        ast_wrappers.ModuleEntry: ModuleEntryNode,
        # Branch decision nodes
        ast_wrappers.IfElseEntry: BranchEntryNode,
        ast_wrappers.ForLoopEntry: BranchEntryNode,
        ast_wrappers.WhileLoopEntry: BranchEntryNode,
        ast_wrappers.TryExceptBranchEntry: BranchEntryNode,
        # Arm entry nodes - same region as their Body counterpart
        ast_wrappers.ModuleBody: ModuleBodyNode,
        ast_wrappers.IfEntry: IfBodyNode,
        ast_wrappers.ElseEntry: ElseBodyNode,
        ast_wrappers.ForEntry: ForBodyNode,
        ast_wrappers.WhileEntry: WhileBodyNode,
        ast_wrappers.TryEntry: TryBodyNode,
        ast_wrappers.ExceptEntry: ExceptBodyNode,
        ast_wrappers.FinallyEntry: FinallyBodyNode,
        ast_wrappers.Body: ModuleBodyNode,
        ast_wrappers.FunctionBody: FunctionBody,
        ast_wrappers.ClassBody: ClassBodyNode,
        ast_wrappers.IfBody: IfBodyNode,
        ast_wrappers.ElseBody: ElseBodyNode,
        ast_wrappers.TryBody: TryBodyNode,
        ast_wrappers.ExceptBody: ExceptBodyNode,
        ast_wrappers.ForBody: ForBodyNode,
        ast_wrappers.WhileBody: WhileBodyNode,
        ast_wrappers.FinallyBody: FinallyBodyNode,
        ast_wrappers.Exit: ExitNode,
        }

    def __init__(self):
        self.entry = ModuleEntryNode()
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

    # returns the correct Node Type,
    def _create_node(self, ast_node: ast.AST) -> Node:
        ast_type = type(ast_node)
        node_class = self.mapping[ast_type]
        node = node_class(block=ast_node)

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
        if node.block is None:
            return f"Entry({nid})"
        if isinstance(node, ExitNode):
            return f"{''.join(word.capitalize() for word in node.block.kind.name.split('_'))}Exit({nid})"
        return node.block.__class__.__name__ + f"({nid})"
       