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
    JUMP = auto()

# eq=False: nodes are dict keys (adj, indeg), so they hash by identity
@dataclass(eq=False)
class Node():
    node_type: NodeType
    ast_node: ast.AST | None = None
    incoming_environments: list["Environment"] = field(default_factory=list)   # pushed by the parents, joined when popped
    enviroment: "Environment | None" = None

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
        ast_node_wrappers.LoopNeverRanEntry: NodeType.ELSE_BODY,
        ast_node_wrappers.ForElseEntry: NodeType.ELSE_BODY,
        ast_node_wrappers.WhileElseEntry: NodeType.ELSE_BODY,
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
        ast_node_wrappers.Break: NodeType.JUMP,
        ast_node_wrappers.Continue: NodeType.JUMP,
        ast_node_wrappers.Return: NodeType.JUMP,
        ast_node_wrappers.Raise: NodeType.JUMP,
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


# Test function
def visualize_graph(cfg: ControlFlowGraph, source: str | None = None, name: str = "graph",
                 path: str | None = None, sccs: list[list[int]] | None = None,
                 scc_graph: dict | None = None) -> str:
    """
    Debug view of the CFG: the _pretty_print edges laid out as a layered graph (top to bottom,
    crossings reduced), with draggable nodes, pan and zoom. If source is given, the file is shown
    at the side: hovering a node highlights its lines, hovering a line highlights its nodes.
    Writes the page to `path` (default: the temp dir), opens it and returns its path.
    sccs (node ids per loop SCC, see condensed_graph.py) starts each loop collapsed into one node.
    scc_graph (the CondensedGraph's own SCCs and adj) enables the pure SCC graph toggle.
    """
    import html, json, pathlib, tempfile, webbrowser

    def category(node: Node) -> str:
        a = node.ast_node
        if a is None or isinstance(a, ast_node_wrappers.ModuleEntry):
            return "module"
        if isinstance(a, ast_node_wrappers.Exit):
            return "exit"
        if isinstance(a, (ast_node_wrappers.FunctionDefinitionEntry, ast_node_wrappers.ClassDefinitionEntry)):
            return "def"
        if isinstance(a, ast_node_wrappers.BranchEntry):
            return "branch"
        if isinstance(a, ast_node_wrappers.Entry):
            return "arm"
        return "body"

    def describe(stmt: ast.AST) -> str:
        value = getattr(stmt, "value", None)
        target = stmt.targets[0] if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else None
        if isinstance(value, ast_node_wrappers.ParameterOf):
            return f"{value.arg.arg} = <param>"
        if isinstance(value, ast_node_wrappers.CaughtAs):
            return f"{value.name} = <caught {ast.unparse(value.type)}>"
        if isinstance(value, ast_node_wrappers.EnteredFrom) and target is not None:
            return f"{ast.unparse(target)} = {ast.unparse(value.value)}.__enter__()"
        if isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return f"def {value.name}(...)"
        if isinstance(value, ast.ClassDef):
            return f"class {value.name}"
        try:
            text = ast.unparse(stmt)
        except Exception:
            text = type(stmt).__name__
        return text.splitlines()[0][:80] if text else type(stmt).__name__

    def span(node: Node) -> list[int] | None:
        start, end = getattr(node.ast_node, "lineno", 0), getattr(node.ast_node, "end_lineno", 0)
        return [start, end or start] if start and start > 0 else None

    source_lines = source.splitlines() if source is not None else None
    real = {id(n) for n in ast.walk(cfg.generator.ast)}   # nodes of the parsed file, as opposed to the CFG's synthetic ones

    def synthetic(owner: ast.AST, stmt: ast.AST) -> str:
        """A statement the CFG made up (desugared), written the way it reads in the source."""
        value = getattr(stmt, "value", None)
        if isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return source_lines[value.lineno - 1].strip() if source_lines else describe(stmt)
        if isinstance(value, ast_node_wrappers.ParameterOf):
            arg = value.arg
            text = {"vararg": "*", "kwarg": "**"}.get(value.kind, "") + arg.arg
            if arg.annotation is not None:
                text += f": {ast.unparse(arg.annotation)}"
            if value.default is not None:
                text += f" = {ast.unparse(value.default)}"
            return f"param {text}"
        if isinstance(value, ast_node_wrappers.CaughtAs):
            return f"except {ast.unparse(value.type)} as {value.name}:"
        if isinstance(value, ast_node_wrappers.EnteredFrom):
            return f"with {ast.unparse(value.value)} as {ast.unparse(stmt.targets[0])}:"
        if isinstance(owner, ast_node_wrappers.ForEntry) and isinstance(stmt, ast.Assign):
            return f"for {ast.unparse(stmt.targets[0])} in {ast.unparse(stmt.value)}:"
        if isinstance(stmt, ast.Expr):
            test = ast.unparse(stmt.value)
            for wrapper, text in ((ast_node_wrappers.IfElseEntry, f"if {test}:"),
                                  (ast_node_wrappers.WhileLoopEntry, f"while {test}:"),
                                  (ast_node_wrappers.MatchEntry, f"match {test}:"),
                                  (ast_node_wrappers.CaseEntry, f"case _ if {test}:")):
                if isinstance(owner, wrapper):
                    return text
        return describe(stmt)

    def code(node: Node) -> list[list]:
        """[line number, text, real] per line the node runs: source lines for real statements, a readable
        line for synthetic ones (real=False). Real lines are dedented together."""
        rows = []
        for stmt in getattr(node.ast_node, "body", None) or []:
            if not isinstance(stmt, ast.AST) or isinstance(stmt, (ast_node_wrappers.Body, ast_node_wrappers.Entry)):
                continue   # placeholders (an empty loop else holds an empty ElseBody)
            if id(stmt) in real and source_lines and getattr(stmt, "lineno", 0) > 0:
                rows += [[n, source_lines[n - 1], True] for n in range(stmt.lineno, stmt.end_lineno + 1)]
            else:
                rows.append([getattr(stmt, "lineno", None) or None, synthetic(node.ast_node, stmt), False])
        indents = [len(t) - len(t.lstrip()) for _, t, is_real in rows if is_real and t.strip()]
        cut = min(indents) if indents else 0
        return [[n, (t[cut:] if is_real else t).rstrip(), is_real] for n, t, is_real in rows]

    used = {n for edge in cfg.edges for n in edge}
    nodes = [{
        "id": cfg._node_ids[id(n)],
        "label": cfg._label(n),
        "kind": category(n),
        "type": type(n.ast_node).__name__ if n.ast_node is not None else "Entry",
        "span": span(n),
        "code": code(n),
    } for n in used]
    edges = [[cfg._node_ids[id(u)], cfg._node_ids[id(v)]] for u, v in cfg.edges]
    data = {"name": name, "nodes": nodes, "edges": edges, "source": source_lines, "sccs": sccs or [], "scc_graph": scc_graph}

    # the page lives in tests/unit_test_html_templates; only the placeholders are filled in here
    template = (pathlib.Path(__file__).resolve().parents[3] / "tests" / "unit_test_html_templates"
                / "cfg_graph.html").read_text(encoding="utf-8")
    page = template.replace("__TITLE__", html.escape(name)).replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    out = pathlib.Path(path) if path else pathlib.Path(tempfile.gettempdir()) / f"rune_cfg_{pathlib.Path(name).stem}.html"
    out.write_text(page, encoding="utf-8")
    webbrowser.open(out.resolve().as_uri())
    return str(out)


if __name__ == "__main__":
    path = "/Users/jeremyquek/Desktop/rune/tests/unit_test/cfg_graph/testcases/jump_finally.py"
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()

    cfg = ControlFlowGraph(ast.parse(source))
    cfg._pretty_print()
    visualize_graph(cfg, source, name=path)
