import json
import os
import sys
import urllib.parse
from collections import deque

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
    graph = trace_graph(name, entry)
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


def trace_graph(name: str, entry: TableEntry) -> dict:
    """
    Walks the parents breadth-first from the hovered entry. This is the
    contract with the client (TraceGraph in trace_graph.ts):

        {
          "name":  "x",                                       # hovered symbol
          "nodes": [{"id", "code", "line", "type"}, ...],     # id 0 is the hovered entry, then BFS order
          "edges": [[parent_id, child_id], ...],              # the type flows parent -> child
        }

    Entries reached twice (a diamond) become one node with two edges.
    The node list in BFS order doubles as the flat trace (hover preview, dropdown).
    """
    ids = {id(entry): 0}   # entry identity -> node id
    nodes = [{"id": 0, "code": entry.code, "line": entry.line, "type": entry.type}]
    edges = []

    queue = deque([entry])
    while queue:
        child = queue.popleft()
        for parent in child.parents:
            if id(parent) not in ids:
                ids[id(parent)] = len(nodes)
                nodes.append({"id": len(nodes), "code": parent.code, "line": parent.line, "type": parent.type})
                queue.append(parent)
            edges.append([ids[id(parent)], ids[id(child)]])

    return {"name": name, "nodes": nodes, "edges": edges}


# @server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
# def did_close(ls: LanguageServer, params: types.DidCloseTextDocumentParams):
#     file_dict.pop(params.text_document.uri, None)

if __name__ == "__main__":
    server.start_io()
