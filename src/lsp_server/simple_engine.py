import re
from collections import deque
from dataclasses import asdict

from engine import HoverResult   # also puts modules/ on sys.path
from lexical_environment import Key
from simple_file_analyzer import TableEntry as SimpleEntry, analyze

"""
The old single-pass simple_file_analyzer behind the engine interface (see engine.py), kept to compare against.
"""


class SimpleEngine():
    """The old simple_file_analyzer behind the engine interface: a table of (line, col) -> entry per file."""

    def __init__(self) -> None:
        self.files: dict[str, dict[tuple[int, int], SimpleEntry]] = {}
        self.lines: dict[str, list[str]] = {}

    def open_file(self, path: str, source: str) -> None:
        try:
            self.files[path] = analyze(source)
        except SyntaxError:
            return   # keep the last good table
        self.lines[path] = source.splitlines()

    def hover(self, path: str, line: int, col: int) -> HoverResult | None:
        """Keys are where a name starts, so any key on the line whose name spans col matches."""
        source_line = self.lines.get(path, [])[line - 1] if line <= len(self.lines.get(path, [])) else ""
        for (l, c), entry in self.files.get(path, {}).items():
            name = re.match(r"\w*", source_line[c:]).group()
            if l == line and c <= col < c + len(name):
                return HoverResult((l, c), name, entry.type)
        return None

    def trace_graph(self, path: str, key: Key) -> dict:
        """Same contract as Engine.trace_graph; parents here are entries, so nodes are deduplicated by identity."""
        entry = self.files[path][key]
        line, col = key
        name = re.match(r"\w*", self.lines[path][line - 1][col:]).group()

        def node(e: SimpleEntry, node_id: int) -> dict:
            return {"id": node_id, "code": e.code, "line": e.line, "type": e.type, "file": path,
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
