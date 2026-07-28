import ast
from collections import defaultdict

import ast_custom
from lexical_environment import LexicalEnvironment

class Node():
    def __init__(self, block = None, enviroment = None):
        self.block = block
        self.enviroment = enviroment
        self.next = []

# Environmental boundaries, clone before passing down the child
class TerminalNode(Node): pass
class EntryNode(TerminalNode): pass 
class ExitNode(TerminalNode):pass 
class BranchEntryNode(TerminalNode): pass

# Splinter into subgraph
class FunctionDefinitionNode(TerminalNode): pass

# Does not splinter
class ClassDefinitionNode(Node): pass

# Regular code node
class BodyNode(Node):pass


class ControlFlowGraph():
    mapping= {
        ast.FunctionDef : FunctionDefinitionNode,
        ast.ClassDef : ClassDefinitionNode,
        ast.For: BranchEntryNode,
        ast.While: BranchEntryNode,
        ast.If: BranchEntryNode,
        ast_custom.Body: BodyNode,
        ast_custom.FunctionBody: BodyNode,
        ast_custom.ClassBody: BodyNode,
        ast_custom.IfBody: BodyNode,
        ast_custom.ElseBody: BodyNode,
        }

    def __init__(self):
        self.entry = EntryNode()
        self.nodes = {self.entry: self.entry}
        self.edges=[]

        # For pretty print
        self._id_counter = 0
        self._node_ids = {id(self.entry): 0}
    
    def insert(self, parent: ast.AST, child: ast.AST)->None:
        u = self.entry if parent is None else self._get_node(parent) 
        v = self._get_node(child)
        u.next.append(v)
        self.edges.append([u,v])


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
        if isinstance(node, EntryNode):
            return f"Entry({nid})"
        if isinstance(node, ExitNode):
            return f"Exit({nid})"
        block = node.block
        if isinstance(block, ast_custom.IfBody):
            return f"IfBody({nid})"
        if isinstance(block, ast_custom.ElseBody):
            return f"ElseBody({nid})"
        if isinstance(block, ast_custom.FunctionBody):
            return f"FuncBody({nid})"
        if isinstance(block, ast_custom.ClassBody):
            return f"ClassBody({nid})"
        if isinstance(block, ast_custom.Body):
            return f"Body({nid})"
        if isinstance(block, ast.FunctionDef):
            return f"FuncDef({nid})"
        if isinstance(block, ast.ClassDef):
            return f"ClassDef({nid})"
        if isinstance(block, ast.If) or isinstance(block, ast.For) or isinstance(block, ast.While):
            return f"Branch({nid})"
        return f"Node({nid})"
    


