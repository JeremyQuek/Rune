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


# Test function
def visualize_graph(cfg: ControlFlowGraph, source: str | None = None, name: str = "graph",
                 path: str | None = None) -> str:
    """
    Debug view of the CFG: the _pretty_print edges laid out as a layered graph (top to bottom,
    crossings reduced), with draggable nodes, pan and zoom. If source is given, the file is shown
    at the side: hovering a node highlights its lines, hovering a line highlights its nodes.
    Writes the page to `path` (default: the temp dir), opens it and returns its path.
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
    data = {"name": name, "nodes": nodes, "edges": edges, "source": source_lines}

    template = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Control Flow: __TITLE__</title>
<style>
:root {
    --bg: #f7f8fa; --panel: #ffffff; --border: #dfe2e7; --text: #1f2328; --muted: #6b7280;
    --grid: #e4e7ec; --edge: #b4bbc6; --card: #ffffff; --code-bg: #f5f6f8; --code: #374151; --gutter: #a3a9b3;
    --shadow: 0 1px 2px rgba(15, 23, 42, .06), 0 4px 14px rgba(15, 23, 42, .06);
    --module: #475569; --branch: #d97706; --arm: #0d9488; --body: #2563eb; --def: #7c3aed; --exit: #9ca3af;
    --in: #ea580c; --out: #0891b2; --hl: rgba(234, 88, 12, .12);
}
@media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
    --bg: #0d0f13; --panel: #14171d; --border: #262b35; --text: #e6e8eb; --muted: #8b93a1;
    --grid: #181c23; --edge: #4a5262; --card: #171b22; --code-bg: #11141a; --code: #c9d1d9; --gutter: #545c69;
    --shadow: 0 1px 2px rgba(0, 0, 0, .5), 0 6px 18px rgba(0, 0, 0, .35);
    --module: #94a3b8; --branch: #fbbf24; --arm: #2dd4bf; --body: #60a5fa; --def: #a78bfa; --exit: #6b7280;
    --in: #fb923c; --out: #22d3ee; --hl: rgba(251, 146, 60, .14);
    }
}
:root[data-theme="dark"] {
    --bg: #0d0f13; --panel: #14171d; --border: #262b35; --text: #e6e8eb; --muted: #8b93a1;
    --grid: #181c23; --edge: #4a5262; --card: #171b22; --code-bg: #11141a; --code: #c9d1d9; --gutter: #545c69;
    --shadow: 0 1px 2px rgba(0, 0, 0, .5), 0 6px 18px rgba(0, 0, 0, .35);
    --module: #94a3b8; --branch: #fbbf24; --arm: #2dd4bf; --body: #60a5fa; --def: #a78bfa; --exit: #6b7280;
    --in: #fb923c; --out: #22d3ee; --hl: rgba(251, 146, 60, .14);
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body { margin: 0; background: var(--bg); color: var(--text); display: flex; flex-direction: column;
       font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
header { padding: 10px 16px; border-bottom: 1px solid var(--border); background: var(--panel); display: flex;
         gap: 16px; align-items: center; flex-wrap: wrap; }
header h1 { font-size: 14px; margin: 0; font-weight: 600; }
.legend { display: flex; gap: 12px; color: var(--muted); flex-wrap: wrap; }
.legend span::before { content: ""; display: inline-block; width: 8px; height: 8px; border-radius: 50%;
                       margin-right: 6px; vertical-align: 1px; background: var(--c); }
.tools { margin-left: auto; display: flex; gap: 6px; flex-wrap: wrap; }
button { background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 6px;
         padding: 3px 10px; font: inherit; cursor: pointer; }
button:hover { border-color: var(--muted); }
main { flex: 1; display: flex; min-height: 0; }
#stage { flex: 1; position: relative; overflow: hidden; cursor: grab; min-width: 0;
         background-image: radial-gradient(var(--grid) 1.3px, transparent 1.3px); background-size: 22px 22px; }
#stage.panning { cursor: grabbing; }
svg { width: 100%; height: 100%; display: block; }
.edge { fill: none; stroke: var(--edge); stroke-width: 1.6; }
.edge.in { stroke: var(--in); stroke-width: 2.4; }
.edge.out { stroke: var(--out); stroke-width: 2.4; }
.node { cursor: pointer; transition: opacity .15s; }
.node.dragging { cursor: grabbing; }
.card { width: 100%; height: 100%; border-radius: 10px; background: var(--card); box-shadow: var(--shadow);
        border: 1px solid var(--border); overflow: hidden; display: flex; flex-direction: column;
        border-top: 3px solid var(--c); transition: border-color .15s, box-shadow .15s; }
.head { height: 38px; flex: none; display: flex; align-items: center; gap: 8px; padding: 0 8px 0 12px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--c); flex: none; }
.title { font: 600 12px ui-monospace, SFMono-Regular, Menlo, monospace; white-space: nowrap; }
.lines { margin-left: auto; color: var(--muted); font-size: 11px; white-space: nowrap; }
.chev { width: 22px; height: 22px; border-radius: 6px; border: 0; padding: 0; background: transparent;
        color: var(--muted); display: grid; place-items: center; flex: none; }
.chev:hover { background: var(--code-bg); color: var(--text); }
.chev svg { width: 12px; height: 12px; transition: transform .15s; }
.collapsed .chev svg { transform: rotate(-90deg); }
.code { flex: 1; background: var(--code-bg); border-top: 1px solid var(--border); padding: 6px 0;
        font: 11.5px/17px ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--code); overflow: hidden; }
.collapsed .code { display: none; }
.row { display: flex; white-space: pre; padding-right: 12px; }
.row .g { width: 34px; flex: none; text-align: right; padding-right: 10px; color: var(--gutter); user-select: none; }
.row.synthetic .t { color: var(--muted); font-style: italic; }
.row.more .t { color: var(--muted); }
.node.self .card { border-color: var(--c); box-shadow: 0 0 0 2px var(--c), var(--shadow); }
.node.in .card { box-shadow: 0 0 0 2px var(--in), var(--shadow); }
.node.out .card { box-shadow: 0 0 0 2px var(--out), var(--shadow); }
.node.line .card { box-shadow: 0 0 0 2px var(--in), var(--shadow); }
.dim .node:not(.self):not(.in):not(.out):not(.line) { opacity: .3; }
.dim .edge:not(.in):not(.out) { opacity: .2; }
aside { width: 400px; border-left: 1px solid var(--border); background: var(--panel); display: flex;
        flex-direction: column; min-height: 0; }
#detail { padding: 14px 16px; border-bottom: 1px solid var(--border); min-height: 104px; max-height: 40%; overflow: auto; }
#detail h2 { font-size: 13px; margin: 0 0 8px; font-family: ui-monospace, Menlo, monospace; }
#detail .meta { color: var(--muted); }
.hint { color: var(--muted); }
#source { flex: 1; overflow: auto; padding: 8px 0; font: 12.5px/20px ui-monospace, SFMono-Regular, Menlo, monospace; }
.ln { display: flex; padding-right: 12px; }
.ln:hover { background: color-mix(in srgb, var(--text) 5%, transparent); }
.ln.hl { background: var(--hl); box-shadow: inset 3px 0 0 var(--in); }
.ln .n { width: 44px; text-align: right; padding-right: 14px; color: var(--muted); opacity: .6; flex: none; user-select: none; }
.ln .t { white-space: pre; }
@media (max-width: 760px) {
    main { flex-direction: column; }
    #stage { min-height: 60vh; }
    aside { width: auto; border-left: 0; border-top: 1px solid var(--border); max-height: 50vh; }
}
</style>
</head>
<body>
<header>
<h1 id="title"></h1>
<div class="legend">
    <span style="--c: var(--module)">module</span><span style="--c: var(--branch)">branch</span>
    <span style="--c: var(--arm)">arm</span><span style="--c: var(--body)">body</span>
    <span style="--c: var(--def)">def / class</span><span style="--c: var(--exit)">exit</span>
    <span style="--c: var(--in)">into</span><span style="--c: var(--out)">out of</span>
</div>
<div class="tools">
    <button id="all" type="button"></button>
    <button id="fit" type="button">Fit</button>
    <button id="relayout" type="button">Re-layout</button>
    <button id="theme" type="button"></button>
</div>
</header>
<main>
<div id="stage"><svg id="svg"><defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill="var(--edge)"></path></marker>
    <marker id="arrow-in" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill="var(--in)"></path></marker>
    <marker id="arrow-out" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill="var(--out)"></path></marker>
</defs><g id="world"><g id="edges"></g><g id="nodes"></g></g></svg></div>
<aside>
    <div id="detail"></div>
    <div id="source"></div>
</aside>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
const data = JSON.parse(document.getElementById("data").textContent);
const NS = "http://www.w3.org/2000/svg";
const HEAD_H = 41, ROW_H = 17, CODE_PAD = 13, MAX_ROWS = 16, MAX_CHARS = 64, LAYER_GAP = 64, NODE_GAP = 30;
const svg = document.getElementById("svg"), world = document.getElementById("world");
const edgeLayer = document.getElementById("edges"), nodeLayer = document.getElementById("nodes");
const stage = document.getElementById("stage"), detail = document.getElementById("detail");
const sourceBox = document.getElementById("source"), allButton = document.getElementById("all");
const byId = new Map(data.nodes.map(n => [n.id, n]));
const outs = new Map(data.nodes.map(n => [n.id, []])), ins = new Map(data.nodes.map(n => [n.id, []]));
for (const [u, v] of data.edges) { outs.get(u).push(v); ins.get(v).push(u); }
document.getElementById("title").textContent = `${data.name} · ${data.nodes.length} nodes, ${data.edges.length} edges`;
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const spanText = n => !n.span ? "" : n.span[0] === n.span[1] ? `L${n.span[0]}` : `L${n.span[0]}–${n.span[1]}`;

// theme: auto (follows the OS) -> light -> dark, remembered when storage allows
const themes = ["auto", "light", "dark"], themeButton = document.getElementById("theme");
function applyTheme(theme) {
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.dataset.theme = theme;
    themeButton.textContent = { auto: "◐ auto", light: "☀ light", dark: "☾ dark" }[theme];
    themeButton.dataset.theme = theme;
}
let savedTheme = "auto";
try { savedTheme = localStorage.getItem("rune-theme") || "auto"; } catch (e) {}
applyTheme(themes.includes(savedTheme) ? savedTheme : "auto");
themeButton.onclick = () => {
    const next = themes[(themes.indexOf(themeButton.dataset.theme) + 1) % themes.length];
    applyTheme(next);
    try { localStorage.setItem("rune-theme", next); } catch (e) {}
};

// ---------- sizes ----------
const measure = document.createElement("canvas").getContext("2d");
const textWidth = (text, font) => { measure.font = font; return Math.ceil(measure.measureText(text).width); };
const TITLE_FONT = "600 12px ui-monospace, SFMono-Regular, Menlo, monospace";
const CODE_FONT = "11.5px ui-monospace, SFMono-Regular, Menlo, monospace";
const SUB_FONT = "11px -apple-system, BlinkMacSystemFont, sans-serif";
for (const n of data.nodes) {
    n.rows = n.code.slice(0, MAX_ROWS).map(([line, text, real]) => ({
        line, real, text: text.length > MAX_CHARS ? text.slice(0, MAX_CHARS - 1) + "…" : text }));
    if (n.code.length > MAX_ROWS) n.rows.push({ line: null, text: `… ${n.code.length - MAX_ROWS} more lines`, more: true });
    n.headW = textWidth(n.label, TITLE_FONT) + textWidth(spanText(n), SUB_FONT) + (n.rows.length ? 22 : 0) + 58;
    n.codeW = n.rows.length ? Math.max(...n.rows.map(r => textWidth(r.text || " ", CODE_FONT))) + 34 + 26 : 0;
    n.open = n.rows.length > 0;
}
const size = n => ({ w: Math.max(130, n.headW, n.open ? n.codeW : 0),
                     h: HEAD_H + (n.open ? n.rows.length * ROW_H + CODE_PAD : 0) });

// ---------- layered layout ----------
function layout() {
    // layers: longest path from the roots (the CFG is a DAG)
    const indeg = new Map(data.nodes.map(n => [n.id, ins.get(n.id).length]));
    const layer = new Map(), order = [];
    const queue = data.nodes.filter(n => indeg.get(n.id) === 0).map(n => n.id);
    for (const id of queue) layer.set(id, 0);
    while (queue.length) {
        const u = queue.shift(); order.push(u);
        for (const v of outs.get(u)) {
            layer.set(v, Math.max(layer.get(v) ?? 0, layer.get(u) + 1));
            indeg.set(v, indeg.get(v) - 1);
            if (indeg.get(v) === 0) queue.push(v);
        }
    }
    for (const n of data.nodes) if (!layer.has(n.id)) layer.set(n.id, 0);

    // long edges get a dummy point per skipped layer, so they route between nodes
    const items = new Map(data.nodes.map(n => [n.id, { id: n.id, layer: layer.get(n.id), ...size(n), real: true }]));
    const routes = [];
    let dummy = 0;
    for (const [u, v] of data.edges) {
        const chain = [u];
        for (let l = layer.get(u) + 1; l < layer.get(v); l++) {
            const id = "d" + (dummy++);
            items.set(id, { id, layer: l, w: 12, h: 0, real: false });
            chain.push(id);
        }
        chain.push(v);
        routes.push({ u, v, chain });
    }
    const up = new Map([...items.keys()].map(k => [k, []])), down = new Map([...items.keys()].map(k => [k, []]));
    for (const r of routes) for (let i = 0; i + 1 < r.chain.length; i++) {
        down.get(r.chain[i]).push(r.chain[i + 1]); up.get(r.chain[i + 1]).push(r.chain[i]);
    }

    // order within layers: discovery order, then barycenter sweeps to reduce crossings
    const depth = Math.max(0, ...[...items.values()].map(it => it.layer)) + 1;
    const layers = Array.from({ length: depth }, () => []);
    const seen = new Set();
    const visit = id => { if (seen.has(id)) return; seen.add(id); layers[items.get(id).layer].push(id); down.get(id).forEach(visit); };
    order.forEach(visit); [...items.keys()].forEach(visit);
    const pos = new Map();
    layers.forEach(row => row.forEach((id, i) => pos.set(id, i)));
    const bary = (id, nbrs) => { const ns = nbrs.get(id); return ns.length ? ns.reduce((s, n) => s + pos.get(n), 0) / ns.length : pos.get(id); };
    for (let sweep = 0; sweep < 12; sweep++) {
        const goingDown = sweep % 2 === 0;
        const range = goingDown ? [...Array(depth).keys()].slice(1) : [...Array(depth).keys()].reverse().slice(1);
        for (const l of range) {
            const nbrs = goingDown ? up : down;
            layers[l].sort((a, b) => bary(a, nbrs) - bary(b, nbrs));
            layers[l].forEach((id, i) => pos.set(id, i));
        }
    }

    // x: pack each layer, then pull nodes toward their neighbours' average, keeping the gaps
    const x = new Map();
    for (const row of layers) {
        let cursor = 0;
        for (const id of row) { const w = items.get(id).w; x.set(id, cursor + w / 2); cursor += w + NODE_GAP; }
    }
    for (let it = 0; it < 24; it++) {
        const nbrs = it % 2 === 0 ? up : down;
        for (const row of layers) {
            const want = row.map(id => {
                const ns = [...nbrs.get(id), ...(it % 4 < 2 ? [] : (nbrs === up ? down : up).get(id))];
                return ns.length ? ns.reduce((s, n) => s + x.get(n), 0) / ns.length : x.get(id);
            });
            row.forEach((id, i) => x.set(id, (x.get(id) + want[i]) / 2));
            for (let i = 1; i < row.length; i++) {
                const a = row[i - 1], b = row[i];
                const min = x.get(a) + items.get(a).w / 2 + NODE_GAP + items.get(b).w / 2;
                if (x.get(b) < min) x.set(b, min);
            }
            for (let i = row.length - 2; i >= 0; i--) {
                const a = row[i], b = row[i + 1];
                const max = x.get(b) - items.get(b).w / 2 - NODE_GAP - items.get(a).w / 2;
                if (x.get(a) > max) x.set(a, max);
            }
        }
    }

    // y: each layer is as tall as its tallest node; nodes hang from the layer's top
    let top = 0;
    for (const row of layers) {
        const tallest = Math.max(HEAD_H, ...row.map(id => items.get(id).h));
        for (const id of row) {
            const it = items.get(id);
            it.x = x.get(id);
            it.top = it.real ? top : top + HEAD_H / 2;
        }
        top += tallest + LAYER_GAP;
    }
    return { items, routes };
}

// ---------- rendering ----------
let model, view = { x: 40, y: 30, k: 1 };
const offsets = new Map();   // node id -> {dx, dy} from dragging, kept across re-layouts
const nodeEls = new Map(), edgeEls = [];
const box = id => {
    const it = model.items.get(id), o = offsets.get(id) || { dx: 0, dy: 0 };
    return { x: it.x + o.dx, top: it.top + o.dy, w: it.w, h: it.h };
};

function edgePath(r) {
    const a = box(r.u), b = box(r.v);
    const points = [[a.x, a.top + a.h], ...r.chain.slice(1, -1).map(id => { const p = box(id); return [p.x, p.top]; }),
                    [b.x, b.top - 2]];
    let d = `M${points[0][0]},${points[0][1]}`;
    for (let i = 1; i < points.length; i++) {
        const [x0, y0] = points[i - 1], [x1, y1] = points[i], my = (y0 + y1) / 2;
        d += ` C${x0},${my} ${x1},${my} ${x1},${y1}`;
    }
    return d;
}

const CHEVRON = `<svg viewBox="0 0 12 12"><path d="M2.5 4.5 L6 8 L9.5 4.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function cardHTML(n) {
    const rows = n.rows.map(r => `<div class="row${r.more ? " more" : r.real ? "" : " synthetic"}"><span class="g">${r.line ?? ""}</span><span class="t">${esc(r.text || " ")}</span></div>`).join("");
    return `<div class="card${n.open ? "" : " collapsed"}" style="--c: var(--${n.kind})" xmlns="http://www.w3.org/1999/xhtml">
        <div class="head"><span class="dot"></span><span class="title">${esc(n.label)}</span>
        <span class="lines">${spanText(n)}</span>
        ${n.rows.length ? `<button class="chev" type="button" title="Show or hide code">${CHEVRON}</button>` : ""}</div>
        ${n.rows.length ? `<div class="code">${rows}</div>` : ""}</div>`;
}

function render() {
    model = layout();
    edgeLayer.textContent = ""; nodeLayer.textContent = ""; nodeEls.clear(); edgeEls.length = 0;
    for (const r of model.routes) {
        const path = document.createElementNS(NS, "path");
        path.setAttribute("class", "edge"); path.setAttribute("marker-end", "url(#arrow)");
        edgeLayer.appendChild(path); edgeEls.push({ r, path });
    }
    for (const n of data.nodes) {
        const g = document.createElementNS(NS, "g");
        g.setAttribute("class", "node");
        const fo = document.createElementNS(NS, "foreignObject");
        fo.innerHTML = cardHTML(n);
        g.appendChild(fo);
        nodeLayer.appendChild(g); nodeEls.set(n.id, g);
        attachNode(n, g);
    }
    data.nodes.forEach(n => place(n.id));
    edgeEls.forEach(({ r, path }) => path.setAttribute("d", edgePath(r)));
    paintFocus();
    allButton.textContent = data.nodes.some(n => n.open) ? "Hide all code" : "Show all code";
}

function place(id) {
    const b = box(id), fo = nodeEls.get(id).firstChild;
    nodeEls.get(id).setAttribute("transform", `translate(${b.x - b.w / 2},${b.top})`);
    fo.setAttribute("width", b.w); fo.setAttribute("height", b.h);
}
function redrawEdges(id) { for (const { r, path } of edgeEls) if (r.u === id || r.v === id) path.setAttribute("d", edgePath(r)); }
function applyView() { world.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`); }

function fit() {
    const bs = data.nodes.map(n => box(n.id));
    const minX = Math.min(...bs.map(b => b.x - b.w / 2)), maxX = Math.max(...bs.map(b => b.x + b.w / 2));
    const minY = Math.min(...bs.map(b => b.top)), maxY = Math.max(...bs.map(b => b.top + b.h));
    const W = stage.clientWidth, H = stage.clientHeight, pad = 40;
    // fit the width; a tall graph keeps a readable zoom and starts at the top (drag or scroll to pan)
    view.k = Math.min(1.3, (W - pad * 2) / Math.max(1, maxX - minX), Math.max(0.75, (H - pad * 2) / Math.max(1, maxY - minY)));
    view.x = (W - (maxX - minX) * view.k) / 2 - minX * view.k;
    view.y = pad - minY * view.k;
    applyView();
}

// ---------- interaction ----------
let pinned = null, hovered = null, lineFocus = null;

function toggle(n, open) { n.open = open; render(); }

function attachNode(n, g) {
    let start = null, moved = false;
    const chev = g.querySelector(".chev");
    if (chev) {
        chev.addEventListener("pointerdown", e => e.stopPropagation());
        chev.addEventListener("click", e => { e.stopPropagation(); toggle(n, !n.open); });
    }
    g.addEventListener("pointerdown", e => {
        e.stopPropagation(); g.setPointerCapture(e.pointerId);
        const o = offsets.get(n.id) || { dx: 0, dy: 0 };
        start = { px: e.clientX, py: e.clientY, dx: o.dx, dy: o.dy }; moved = false;
        g.classList.add("dragging");
    });
    g.addEventListener("pointermove", e => {
        if (!start) return;
        const dx = (e.clientX - start.px) / view.k, dy = (e.clientY - start.py) / view.k;
        if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
        offsets.set(n.id, { dx: start.dx + dx, dy: start.dy + dy });
        place(n.id); redrawEdges(n.id);
    });
    g.addEventListener("pointerup", () => {
        g.classList.remove("dragging");
        if (start && !moved) { pinned = pinned === n.id ? null : n.id; paintFocus(); scrollToSpan(byId.get(pinned)); }
        start = null;
    });
    g.addEventListener("pointerenter", () => { hovered = n.id; paintFocus(); });
    g.addEventListener("pointerleave", () => { hovered = null; paintFocus(); });
}

let pan = null;
stage.addEventListener("pointerdown", e => {
    pan = { px: e.clientX, py: e.clientY, x: view.x, y: view.y, moved: false };
    stage.setPointerCapture(e.pointerId); stage.classList.add("panning");
});
stage.addEventListener("pointermove", e => {
    if (!pan) return;
    const dx = e.clientX - pan.px, dy = e.clientY - pan.py;
    if (Math.abs(dx) + Math.abs(dy) > 2) pan.moved = true;
    view.x = pan.x + dx; view.y = pan.y + dy; applyView();
});
stage.addEventListener("pointerup", () => {
    if (pan && !pan.moved) { pinned = null; paintFocus(); }
    pan = null; stage.classList.remove("panning");
});
stage.addEventListener("wheel", e => {
    e.preventDefault();
    if (!e.ctrlKey && !e.metaKey) { view.x -= e.deltaX; view.y -= e.deltaY; applyView(); return; }   // scroll pans
    const rect = stage.getBoundingClientRect(), mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const k = Math.min(3, Math.max(0.15, view.k * Math.exp(-e.deltaY * 0.01)));
    view.x = mx - (mx - view.x) * (k / view.k); view.y = my - (my - view.y) * (k / view.k); view.k = k;
    applyView();
}, { passive: false });
document.addEventListener("keydown", e => { if (e.key === "Escape") { pinned = null; lineFocus = null; paintFocus(); } });
document.getElementById("fit").onclick = fit;
document.getElementById("relayout").onclick = () => { offsets.clear(); render(); fit(); };
allButton.onclick = () => {
    const open = !data.nodes.some(n => n.open);
    data.nodes.forEach(n => { n.open = open && n.rows.length > 0; });
    render();
};

function paintFocus() {
    const focus = hovered ?? pinned;
    const lineNodes = lineFocus === null ? new Set() : new Set(data.nodes
        .filter(n => n.span && n.span[0] <= lineFocus && lineFocus <= n.span[1]).map(n => n.id));
    svg.classList.toggle("dim", focus !== null || lineNodes.size > 0);
    for (const [id, g] of nodeEls) {
        g.classList.toggle("self", id === focus);
        g.classList.toggle("in", focus !== null && outs.get(id).includes(focus));
        g.classList.toggle("out", focus !== null && ins.get(id).includes(focus));
        g.classList.toggle("line", lineNodes.has(id));
    }
    for (const { r, path } of edgeEls) {
        const isIn = focus !== null && r.v === focus, isOut = focus !== null && r.u === focus;
        path.classList.toggle("in", isIn); path.classList.toggle("out", isOut);
        path.setAttribute("marker-end", isIn ? "url(#arrow-in)" : isOut ? "url(#arrow-out)" : "url(#arrow)");
    }
    showDetail(focus === null ? null : byId.get(focus));
    highlightLines(focus === null ? null : byId.get(focus));
}

function showDetail(n) {
    if (!n) {
        detail.innerHTML = `<h2>Control flow graph</h2><div class="hint">Hover a node to see where it flows
            (orange: into it, cyan: out of it). Click to pin, drag to move, the chevron shows or hides its code.
            Scroll or drag the background to pan, pinch or ⌘/ctrl + scroll to zoom. Hover a source line to find its nodes. Esc clears.</div>`;
        return;
    }
    const lines = n.span ? (n.span[0] === n.span[1] ? `line ${n.span[0]}` : `lines ${n.span[0]}–${n.span[1]}`) : "no source position";
    const name = id => esc(byId.get(id).label);
    detail.innerHTML = `<h2>${esc(n.label)}</h2>
        <div class="meta">${esc(n.type)} · ${n.kind} · ${lines}<br>
        from: ${ins.get(n.id).map(name).join(", ") || "—"}<br>
        to: ${outs.get(n.id).map(name).join(", ") || "—"}</div>`;
}

// ---------- source panel ----------
const lineEls = [];
if (data.source) {
    data.source.forEach((text, i) => {
        const row = document.createElement("div");
        row.className = "ln";
        const num = document.createElement("span"); num.className = "n"; num.textContent = i + 1;
        const t = document.createElement("span"); t.className = "t"; t.textContent = text || " ";
        row.append(num, t);
        row.addEventListener("pointerenter", () => { lineFocus = i + 1; paintFocus(); });
        row.addEventListener("pointerleave", () => { lineFocus = null; paintFocus(); });
        sourceBox.appendChild(row); lineEls.push(row);
    });
} else {
    sourceBox.innerHTML = `<div class="hint" style="padding: 8px 16px">No source given: pass source= to visualize_graph.</div>`;
}
function highlightLines(n) {
    lineEls.forEach((row, i) => row.classList.toggle("hl", !!(n && n.span && n.span[0] <= i + 1 && i + 1 <= n.span[1])));
}
function scrollToSpan(n) {
    if (n && n.span && lineEls[n.span[0] - 1]) lineEls[n.span[0] - 1].scrollIntoView({ block: "center", behavior: "smooth" });
}

render();
requestAnimationFrame(fit);
</script>
</body>
</html>
"""
    page = template.replace("__TITLE__", html.escape(name)).replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    out = pathlib.Path(path) if path else pathlib.Path(tempfile.gettempdir()) / f"rune_cfg_{pathlib.Path(name).stem}.html"
    out.write_text(page, encoding="utf-8")
    webbrowser.open(out.resolve().as_uri())
    return str(out)


if __name__ == "__main__":
    path = "tests/cfg_graph_test_cases/class.py"
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()

    cfg = ControlFlowGraph(ast.parse(source))
    cfg._pretty_print()
    visualize_graph(cfg, source, name=path)
