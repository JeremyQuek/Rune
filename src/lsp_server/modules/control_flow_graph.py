import ast
from enum import Enum, auto
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import ast_node_wrappers
from cfg_generator import CFGGenerator

if TYPE_CHECKING:  # annotation only, so the CFG doesn't import the type layer at runtime
    from lexical_environment import Environment

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

# eq=False: nodes are dict keys (adj, indeg), so they hash by identity
@dataclass(eq=False)
class Node():
    node_type: NodeType
    ast_node: ast.AST | None = None
    incoming_environments: list["Environment"] = field(default_factory=list)   # pushed by the parents, joined when popped
    enviroment: "Environment | None" = None
    next: list["Node"] = field(default_factory=list)

    def __repr__(self) -> str:
        return self.node_type.name

class ControlFlowGraph():
    mapping: dict[type[ast.AST], NodeType] = {
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

    def __init__(self, tree: ast.AST) -> None:
        self.entry = Node(NodeType.MODULE_ENTRY)
        self.nodes: dict[ast.AST | Node, Node] = {self.entry: self.entry}   # ast node -> its CFG node
        self.edges: list[list[Node]] = []
        self.adj: defaultdict[Node, list[Node]] = defaultdict(list)
        self.indeg: defaultdict[Node, int] = defaultdict(int)

        # For pretty print
        self._id_counter = 0
        self._node_ids: dict[int, int] = {id(self.entry): 0}

        # first node of each function body -> its def, so the walk knows where to push the function's scope
        self.function_bodies: dict[Node, ast.FunctionDef | ast.AsyncFunctionDef] = {}

        self.generator = CFGGenerator(tree, self)
        self.generator.make_graph()

    def insert(self, parent: ast.AST | None, child: ast.AST) -> None:
        u = self.entry if parent is None else self._get_node(parent) 
        v = self._get_node(child)
        u.next.append(v)
        self.edges.append([u,v])
    
    def create_adjacency_list(self) -> defaultdict[Node, list[Node]]:
        for (u,v) in self.edges:
            self.adj[u].append(v)
        
        return self.adj
    
    def count_indeg(self) -> defaultdict[Node, int]:
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
        node = Node(node_type, ast_node=ast_node)

        # For pretty print
        self._id_counter += 1
        self._node_ids[id(node)] = self._id_counter
        return node
    
    """
    Prints the edge list in a format pasteable into 
    graphonline.top/create_graph_by_edge_list for visual debugging.
    """
    def _pretty_print(self) -> None:
        
        for u, v in self.edges:
            print(f"{self._label(u)}-{self._label(v)}")

    def _label(self, node: Node) -> str:
        nid = self._node_ids[id(node)]
        if node.ast_node is None:
            return f"Entry({nid})"
        if node.node_type == NodeType.EXIT:
            return f"{''.join(word.capitalize() for word in node.ast_node.kind.name.split('_'))}Exit({nid})"
        return node.ast_node.__class__.__name__ + f"({nid})"


if __name__ == "__main__":
    with open("tests/cfg_graph_test_cases/class.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    cfg = ControlFlowGraph(tree)
    cfg._pretty_print()
