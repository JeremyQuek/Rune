import json
import urllib.parse
from pathlib import Path

from lsprotocol import types
from pygls.lsp.server import LanguageServer
from pygls.uris import from_fs_path, to_fs_path

from engine import Engine
from simple_engine import SimpleEngine

"""

Minimal Rune LSP server.

Speaks LSP and nothing else: uris and 0-based positions in, markdown out. The analysis is ENGINE's
(engine.py), which works in absolute paths and ast positions; the conversions happen here only.
Launched by the VS Code client over stdio.

Never print() in this process: stdout is the LSP channel. Log to stderr instead.

"""

server = LanguageServer("rune", "0.1.0")
ENGINE = Engine()   # or SimpleEngine(): same interface
TRACE_PREVIEW_LENGTH = 3  # trace steps shown directly in the hover
FAKE_CROSS_FILE = True    # TEMP: graft a chain from tests/random_source.py onto every graph (preview cross-file UI before imports exist)
FAKE_FILE = (Path(__file__).parents[2] / "tests" / "integration/random_source.py").as_uri()


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: LanguageServer, params: types.DidOpenTextDocumentParams):
    ENGINE.open_file(to_fs_path(params.text_document.uri), params.text_document.text)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: types.DidChangeTextDocumentParams):
    uri = params.text_document.uri
    ENGINE.open_file(to_fs_path(uri), ls.workspace.get_text_document(uri).source)


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(ls: LanguageServer, params: types.HoverParams):
    uri = params.text_document.uri
    path = to_fs_path(uri)
    # LSP lines are 0-based, ast lines 1-based; columns are passed as is (UTF-16 vs UTF-8: TODO known gap 3)
    result = ENGINE.hover(path, params.position.line + 1, params.position.character)
    if result is None:
        return None
    graph = ENGINE.trace_graph(path, result.key)
    for node in graph["nodes"]:
        node["file"] = from_fs_path(node["file"])   # the client opens files by uri
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
            value=f"```python\n{result.name}: {result.type}\n```\n\n**Trace**\n\n{preview}\n\n{full_trace_link} · {graph_link}",
        )
    )


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
#     closed files stay cached for now

if __name__ == "__main__":
    server.start_io()
