import json
import os
import sys
import urllib.parse
from collections import deque
from dataclasses import asdict
from pathlib import Path

from lsprotocol import types
from pygls.lsp.server import LanguageServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "modules"))
from simple_file_analyzer import TableEntry, analyze

"""

Minimal Rune LSP server.

Keeps one type table per open file and answers hover requests from it.
Launched by the VS Code client over stdio.

Never print() in this process: stdout is the LSP channel. Log to stderr instead.

"""

server = LanguageServer("rune", "0.1.0")
file_dict = {}  # file uri -> {(col, line): TableEntry}
TRACE_PREVIEW_LENGTH = 3  # trace steps shown directly in the hover
FAKE_CROSS_FILE = True    # TEMP: graft a chain from tests/random_source.py onto every graph (preview cross-file UI before imports exist)
FAKE_FILE = (Path(__file__).parents[2] / "tests" / "integration/random_source.py").as_uri()


def create_type_table(uri: str, source: str):
    try:
        file_dict[uri] = analyze(source)
    except SyntaxError:
        pass  # mid-edit code often doesn't parse, so keep the last good table


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: LanguageServer, params: types.DidOpenTextDocumentParams):
    uri = params.text_document.uri
    if uri not in file_dict:
        create_type_table(uri, params.text_document.text)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: types.DidChangeTextDocumentParams):
    uri = params.text_document.uri
    create_type_table(uri, ls.workspace.get_text_document(uri).source)


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(ls: LanguageServer, params: types.HoverParams):
    uri = params.text_document.uri
    doc = ls.workspace.get_text_document(uri)
    line = params.position.line  # LSP lines are 0-based
    col = params.position.character

    # Table keys are where a name starts, so match any key on this line whose
    # name span covers the cursor (hovering anywhere on `suffix`, not just the `s`)
    name = doc.word_at_position(params.position)
    entry = next(
        (e for (c, l), e in file_dict.get(uri, {}).items()
         if l == line + 1 and c <= col < c + len(name)),  # ast lines are 1-based
        None,
    )
    if entry is None:
        return None
    graph = trace_graph(name, entry, uri)
    if FAKE_CROSS_FILE:
        graft_fake_file(graph)
    steps = graph["nodes"]

    # Preview the first few steps, each a link that jumps to its line (#L<line>)
    preview = "\n".join(
        f"- [`{step['code']}`]({uri}#L{step['line']}) (this file, line {step['line']})"
        for step in steps[:TRACE_PREVIEW_LENGTH]
    )

    # Both links run a client command with [uri, graph]
    command_args = urllib.parse.quote(json.dumps([uri, graph]))
    full_trace_link = f"[Show full trace ({len(steps)} steps)](command:rune.showTrace?{command_args})"
    graph_link = f"[View as graph](command:rune.showGraph?{command_args})"

    return types.Hover(
        contents=types.MarkupContent(
            kind=types.MarkupKind.Markdown,
            value=f"```python\n{name}: {entry.type}\n```\n\n**Trace**\n\n{preview}\n\n{full_trace_link} · {graph_link}",
        )
    )


def trace_graph(name: str, entry: TableEntry, file: str) -> dict:
    """
    Walks the parents breadth-first from the hovered entry. This is the
    contract with the client (TraceGraph in trace_tree.ts):

        {
          "name":  "x",                                       # hovered symbol
          "nodes": [{"id", "code", "line", "type",            # id 0 is the hovered entry, then BFS order
                     "file",                                  # uri of the file the entry is in
                     "operands": [{"name", "type", "line"}]}, # rhs names/literals, line None for literals
                    ...],
          "edges": [[parent_id, child_id], ...],              # the type flows parent -> child
        }

    Entries reached twice (a diamond) become one node with two edges.
    The node list in BFS order doubles as the flat trace (hover preview, dropdown).
    Single-file for now, so every node gets the hovered file.
    """
    def node(e: TableEntry, node_id: int) -> dict:
        return {"id": node_id, "code": e.code, "line": e.line, "type": e.type, "file": file,
                "operands": [asdict(o) for o in e.operands]}

    ids = {id(entry): 0}   # entry identity -> node id
    nodes = [node(entry, 0)]
    edges = []

    queue = deque([entry])
    while queue:
        child = queue.popleft()
        for parent in child.parents:
            if id(parent) not in ids:
                ids[id(parent)] = len(nodes)
                nodes.append(node(parent, len(nodes)))
                queue.append(parent)
            edges.append([ids[id(parent)], ids[id(child)]])

    return {"name": name, "nodes": nodes, "edges": edges}


def graft_fake_file(graph: dict):
    """
    TEMP (FAKE_CROSS_FILE): pretends the deepest source node was imported from
    tests/random_source.py, so the graph shows a second file. Delete once imports work.

        seed = 7  ->  offset = seed * 2  ->  base = offset + seed  ->  deepest source
    """
    has_parents = {child for _, child in graph["edges"]}
    target = [n for n in graph["nodes"] if n["id"] not in has_parents][-1]["id"]

    first = len(graph["nodes"])
    seed, offset, base = first, first + 1, first + 2
    fake = [
        ("seed = 7", 1, []),
        ("offset = seed * 2", 2, [("seed", "int", 1), ("2", "int", None)]),
        ("base = offset + seed", 3, [("offset", "int", 2), ("seed", "int", 1)]),
    ]
    for i, (code, line, operands) in enumerate(fake):
        if not operands:
            operands = [("7", "int", None)]
        graph["nodes"].append({
            "id": first + i, "code": code, "line": line, "type": "int", "file": FAKE_FILE,
            "operands": [{"name": n, "type": t, "line": l} for n, t, l in operands],
        })
    graph["edges"] += [[seed, offset], [offset, base], [seed, base], [base, target]]


# @server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
# def did_close(ls: LanguageServer, params: types.DidCloseTextDocumentParams):
#     file_dict.pop(params.text_document.uri, None)

if __name__ == "__main__":
    server.start_io()
