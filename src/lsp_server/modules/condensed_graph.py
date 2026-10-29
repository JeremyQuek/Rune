import ast
from collections import defaultdict
from dataclasses import dataclass, field

from control_flow_graph import ControlFlowGraph, Node, visualize_graph

"""
CondensedGraph: the CFG with every strongly connected component (a loop, nested loops
included) collapsed into one SCCNode, so the SCCs form a DAG that Kahn's algorithm can walk.

The CFG itself is not modified: an SCCNode only references the CFG's nodes.
  - A plain node is an SCC of size 1 (no internal edges).
  - A loop is one SCC: the cycle and everything in it. Nested loops are a single SCC,
    since the outer back edge connects the inner loop's nodes to the outer ones.
  - An SCC has one entry (Python has no goto, so a loop is only entered through
    ForEntry/WhileEntry) but can have several exits (the loop exit, breaks, returns, raises).
"""

# eq=False: SCCNodes are dict keys (adj, indeg), so they hash by identity
@dataclass(eq=False)
class SCCNode():
    entry_node: Node                                           # where the SCC is entered from outside
    cluster_size: int
    nodes: list[Node]                                          # forward order from the entry: the order a fixpoint pass visits them
    adj: dict[Node, list[Node]]                                # only the edges inside the SCC, back edges included
    out_edges: list[tuple[Node, Node]] = field(default_factory=list)   # (inside, outside): where envs go once the SCC settles

    def is_loop(self) -> bool:
        return self.cluster_size > 1


class CondensedGraph():
    """
    Takes an control flow graph and outputs a condensed DAG version of it
    """

    def __init__(self, cfg: ControlFlowGraph) -> None:
        self.cfg = cfg
        self.sccs: list[SCCNode] = []
        self.scc_of: dict[Node, SCCNode] = {}
        self.adj: dict[SCCNode, list[SCCNode]] = defaultdict(list)    # edges between SCCs: a DAG

        succ: dict[Node, list[Node]] = defaultdict(list)
        nodes = list(dict.fromkeys(n for edge in cfg.edges for n in edge))   # every connected node, in insertion order
        for u, v in cfg.edges:
            succ[u].append(v)

        for component in self._run_tarjan(nodes, succ):
            self._add_scc(component, succ)

        # edges between SCCs, once per pair
        for scc in self.sccs:
            self.adj[scc] = list(dict.fromkeys(self.scc_of[v] for _, v in scc.out_edges))

    def count_indeg(self) -> dict[SCCNode, int]:
        """A fresh count per call, since Kahn's algorithm consumes it."""
        indeg = {scc: 0 for scc in self.sccs}   # roots have indeg 0
        for targets in self.adj.values():
            for target in targets:
                indeg[target] += 1
        return indeg

    def _run_tarjan(self, nodes: list[Node], succ: dict[Node, list[Node]]) -> list[list[Node]]:
        """
        Tarjan's algorithm, iterative (a recursive DFS would hit the recursion limit on a long file).
        index: discovery order. low: the smallest index reachable from the node's DFS subtree through
        nodes still on the stack. A node whose low equals its index is the root of an SCC: everything
        above it on the stack belongs to that SCC.
        """
        index: dict[Node, int] = {}
        low: dict[Node, int] = {}
        on_stack: set[Node] = set()
        stack: list[Node] = []
        components: list[list[Node]] = []

        for root in nodes:
            if root in index:
                continue
            work = [(root, 0)]   # (node, position in its successor list)
            index[root] = low[root] = len(index)
            stack.append(root); on_stack.add(root)
            while work:
                u, i = work[-1]
                if i < len(succ[u]):
                    work[-1] = (u, i + 1)
                    v = succ[u][i]
                    if v not in index:
                        index[v] = low[v] = len(index)
                        stack.append(v); on_stack.add(v)
                        work.append((v, 0))
                    elif v in on_stack:
                        low[u] = min(low[u], index[v])
                    continue
                work.pop()
                if work:   # pass u's low up to its DFS parent
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[u])
                if low[u] == index[u]:
                    component = []
                    while True:
                        w = stack.pop(); on_stack.discard(w)
                        component.append(w)
                        if w is u:
                            break
                    components.append(component)
        return components

    def _add_scc(self, component: list[Node], succ: dict[Node, list[Node]]) -> None:
        members = set(component)
        adj = {u: [v for v in succ[u] if v in members] for u in component}
        out_edges = [(u, v) for u in component for v in succ[u] if v not in members]

        # the entry is the member with a predecessor outside (a root SCC has none: take any member)
        preds_outside = {v for u, vs in succ.items() if u not in members for v in vs if v in members}
        entry = next((n for n in component if n in preds_outside), component[0])

        scc = SCCNode(entry, len(component), self._forward_order(entry, adj), adj, out_edges)
        self.sccs.append(scc)
        for n in component:
            self.scc_of[n] = scc

    def _forward_order(self, entry: Node, adj: dict[Node, list[Node]]) -> list[Node]:
        """
        Kahn over the SCC's edges minus its back edges, which leaves a DAG. The back edges are found
        by a DFS from the entry (an edge into a node still on the DFS stack): the outer loop's, and
        those of any loop nested inside it.
        """
        back: set[tuple[Node, Node]] = set()
        state = {entry: 1}   # 1 on the DFS stack, 2 done
        work = [(entry, 0)]
        while work:
            u, i = work[-1]
            if i < len(adj[u]):
                work[-1] = (u, i + 1)
                v = adj[u][i]
                if state.get(v) == 1:
                    back.add((u, v))
                elif v not in state:
                    state[v] = 1
                    work.append((v, 0))
            else:
                state[u] = 2
                work.pop()

        indeg = {u: 0 for u in adj}
        for u, vs in adj.items():
            for v in vs:
                if (u, v) not in back:
                    indeg[v] += 1
        order, queue = [], [entry]
        while queue:
            u = queue.pop(0)
            order.append(u)
            for v in adj[u]:
                if (u, v) in back:
                    continue
                indeg[v] -= 1
                if indeg[v] == 0:
                    queue.append(v)
        return order + [n for n in adj if n not in order]   # safety: a second entry would leave some unordered

    def _pretty_print(self) -> None:
        for k, scc in enumerate(self.sccs):
            if scc.is_loop():
                print(f"SCC {k} ({scc.cluster_size} nodes, entry {self.cfg._label(scc.entry_node)}): "
                      + ", ".join(self.cfg._label(n) for n in scc.nodes))
                print("  exits: " + ", ".join(f"{self.cfg._label(u)}->{self.cfg._label(v)}" for u, v in scc.out_edges))


def visualize_condensed(cg: CondensedGraph, source: str | None = None, name: str = "graph",
                        path: str | None = None) -> str:
    """The CFG view with each loop SCC collapsed into one node; click it to expand its nodes in place."""
    nid = lambda n: cg.cfg._node_ids[id(n)]
    loops = [[nid(n) for n in scc.nodes] for scc in cg.sccs if scc.is_loop()]
    # the condenser's own output, drawn as is by the page's SCC graph toggle
    k = {scc: i for i, scc in enumerate(cg.sccs)}
    scc_graph = {
        "sccs": [{"k": i, "members": [nid(n) for n in scc.nodes], "entry": nid(scc.entry_node),
                  "out_edges": [[nid(u), nid(v)] for u, v in scc.out_edges]} for i, scc in enumerate(cg.sccs)],
        "adj": [[k[scc], k[target]] for scc in cg.sccs for target in cg.adj[scc]],
    }
    return visualize_graph(cg.cfg, source, name=name, path=path, sccs=loops, scc_graph=scc_graph)


if __name__ == "__main__":
    path = "/Users/jeremyquek/Desktop/rune/tests/unit_test/cfg_graph/testcases/break_continue.py"
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()

    cg = CondensedGraph(ControlFlowGraph(ast.parse(source)))
    cg._pretty_print()
    visualize_condensed(cg, source, name=path)
