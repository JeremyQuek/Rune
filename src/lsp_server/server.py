import json
import os
import sys
import urllib.parse

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

    entry = file_dict.get(uri, {}).get((col, line + 1))  # ast lines are 1-based
    if entry is None:
        return None

    name = doc.word_at_position(params.position)
    steps = trace_steps(entry)

    # Preview the first few steps, each a link that jumps to its line (#L<line>)
    preview = "\n".join(
        f"- [`{step['code']}`]({uri}#L{step['line']}) (this file, line {step['line']})"
        for step in steps[:TRACE_PREVIEW_LENGTH]
    )

    # Clicking this link runs the client's rune.showTrace command with [uri, steps]
    command_args = urllib.parse.quote(json.dumps([uri, steps]))
    full_trace_link = f"[Show full trace ({len(steps)} steps)](command:rune.showTrace?{command_args})"

    return types.Hover(
        contents=types.MarkupContent(
            kind=types.MarkupKind.Markdown,
            value=f"```python\n{name}: {entry.type}\n```\n\n**Trace**\n\n{preview}\n\n{full_trace_link}",
        )
    )

def trace_steps(entry: TableEntry) -> list[dict]:
    """Follow the prev pointers back to where the type started, one step per entry."""
    steps = []
    while entry is not None:
        steps.append({"code": entry.code, "line": entry.line})
        entry = entry.prev
    return steps


# @server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
# def did_close(ls: LanguageServer, params: types.DidCloseTextDocumentParams):
#     file_dict.pop(params.text_document.uri, None)

if __name__ == "__main__":
    server.start_io()
