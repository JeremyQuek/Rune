import os
import sys
from collections import deque
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "modules"))
from global_namespace_table import GlobalNamespaceTable
from lexical_environment import Key
from module_file_object import ModuleFileObject

"""

The analysis side of the server: server.py speaks LSP (uris, 0-based lines), an engine speaks files.
Paths are absolute filesystem paths; positions are ast coordinates (1-based line, 0-based col).

Both engines have the same three methods, so server.py swaps them with one line:

    open_file(path, source)       create or replace the file's analysis; on a SyntaxError the last good one stays
    hover(path, line, col)        HoverResult for the name under the cursor, or None
    trace_graph(path, key)        the trace graph of key, the client contract (see trace_graph below)

Engine        ModuleFileObject per file, one GlobalNamespaceTable for the session, which they share
SimpleEngine  the old single-pass simple_file_analyzer, kept to compare against (simple_engine.py)

"""


@dataclass
class HoverResult():
    key: Key      # pass back to trace_graph
    name: str     # the hovered name
    type: str     # as hover shows it


class Engine():
    """
    One GlobalNamespaceTable for the session, one ModuleFileObject per open file. The files never see each
    other: anything one needs from another goes through the namespace table.
    """

    def __init__(self) -> None:
        self.global_namespace_table = GlobalNamespaceTable()
        self.files: dict[str, ModuleFileObject] = {}   # path -> its analysis
        self.lines: dict[str, list[str]] = {}          # path -> its source lines, the code column of the trace

    def open_file(self, path: str, source: str) -> None:
        try:
            self.files[path] = ModuleFileObject(path, source, self.global_namespace_table)
        except SyntaxError:
            return   # mid-edit code often doesn't parse, so keep the last good analysis
        self.lines[path] = source.splitlines()

    def hover(self, path: str, line: int, col: int) -> HoverResult | None:
        mfo = self.files.get(path)
        key = mfo.key_at(line, col) if mfo else None
        if key is None:
            return None
        return HoverResult(key, mfo.symbol(key), repr(mfo.get_type(key)))

    def trace_graph(self, path: str, key: Key) -> dict:
        """
        Walks the parent keys breadth-first from key. This is the contract with the client (TraceGraph in trace_tree.ts):

            {
              "name":  "x",                                       # hovered symbol
              "nodes": [{"id", "code", "line", "type", "kind",    # id 0 is the hovered entry, then BFS order
                         "source",                                # no operands: where the type comes from ("literal", ...), else None
                         "file",                                  # path of the file the entry is in (server.py makes it a uri)
                         "operands": [{"name", "type", "line"}]}, # the node's drawn parents, line None for builtins
                        ...],
              "edges": [[parent_id, child_id], ...],              # the type flows parent -> child
            }

        kind: "def" (a write), "read" (a read drawn because it does work, e.g. the .c lookup of a.b.c), "builtin".
        Builtin nodes have line None: they aren't in the file.

        Drawn: positional keys and builtins. Walked through, never drawn:
            joins, modules, unbound   no line and nothing to show; a join's arms link straight to its reader
            plain reads               rhs keys whose parents are all the same symbol (a in c = a + b → a = 1)
        The hovered key is always drawn. Keys reached twice (a diamond, a loop) become one node with several edges.
        Single-file for now, so every node gets path.
        """
        mfo = self.files[path]
        mfo.get_type(key)   # resolves everything the trace will show

        def positional(k: Key) -> bool:
            return len(k) == 2 and all(isinstance(n, int) for n in k)

        def builtin(k: Key) -> bool:
            return k[0] == "builtins"

        def drawn(k: Key) -> bool:
            if builtin(k):
                return True
            if not positional(k):
                return False
            parents = mfo.parents(k)
            plain_read = mfo.side(k) == "rhs" and parents and all(mfo.symbol(p) == mfo.symbol(k) for p in parents)
            return not plain_read

        def drawn_parents(k: Key) -> list[Key]:
            found, seen, stack = [], {k}, list(reversed(mfo.parents(k)))
            while stack:
                p = stack.pop()
                if p in seen:
                    continue
                seen.add(p)
                if drawn(p):
                    found.append(p)
                else:
                    stack.extend(reversed(mfo.parents(p)))
            return found

        def line_of(k: Key) -> int | None:
            return k[0] if positional(k) else None

        def node(k: Key, node_id: int, parents: list[Key]) -> dict:
            line = line_of(k)
            code = (f"builtins.{mfo.symbol(k)}" if line is None
                    else self.lines[path][line - 1].strip() if line <= len(self.lines[path]) else mfo.symbol(k))
            kind = "builtin" if builtin(k) else "read" if mfo.side(k) == "rhs" else "def"
            return {"id": node_id, "code": code, "line": line, "type": repr(mfo.get_type(k)), "kind": kind, "file": path,
                    "source": None if parents else mfo.source(k),
                    "operands": [{"name": mfo.symbol(p), "type": repr(mfo.get_type(p)), "line": line_of(p)} for p in parents]}

        ids = {key: 0}
        first_parents = drawn_parents(key)
        nodes = [node(key, 0, first_parents)]
        edges = []

        queue = deque([(key, first_parents)])
        while queue:
            child, parents = queue.popleft()
            for parent in parents:
                if parent not in ids:
                    ids[parent] = len(nodes)
                    grand = drawn_parents(parent)
                    nodes.append(node(parent, len(nodes), grand))
                    queue.append((parent, grand))
                edges.append([ids[parent], ids[child]])

        return {"name": mfo.symbol(key), "nodes": nodes, "edges": edges}
