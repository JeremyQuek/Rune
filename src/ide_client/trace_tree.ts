import * as vscode from 'vscode';

/*
 * Shows a variable's trace as a native tree in the Explorer sidebar ("Rune Trace").
 *
 * The server sends a TraceGraph (see Engine.trace_graph in engine.py). The hovered
 * entry is the root, and expanding a row shows the entries its type came from.
 * The graph can be cyclic (loops) and shares parents (diamonds), so the tree is a spanning
 * tree: each node expands once, where it first appears; later appearances are leaves
 * marked "↻ shown above". Without this a cycle expands forever and crashes the window.
 * Clicking a row jumps to its line.
 */

// Contract with server.py
export type Operand = { name: string; type: string; line: number | null }; // line is null for literals
export type TraceNode = {
  id: number;
  code: string;
  line: number;
  type: string;
  file: string;          // uri of the file the entry is in
  source?: string | null; // no operands: where the type comes from ("literal", "builtin", ...)
  operands: Operand[];   // names and literals the rhs is built from
};
export type TraceGraph = {
  name: string;               // hovered symbol
  nodes: TraceNode[];         // id 0 is the hovered entry, then BFS order; nodes[id].id === id
  edges: [number, number][];  // [parent_id, child_id]: the type flows parent -> child
};

export const TRACE_VIEW_ID = 'runeTrace';

// One row of the tree. Rows are distinct objects even when they show the same node.
type Row = {
  node: TraceNode;
  repeat: boolean;   // the node already expanded elsewhere in the tree: shown as a leaf
  children?: Row[];  // cached, so collapsing and re-expanding a row gives the same rows
};

class TraceTreeProvider implements vscode.TreeDataProvider<Row> {
  private uri = '';
  private graph: TraceGraph | undefined;
  private parentsOf = new Map<number, number[]>(); // child id -> parent ids
  private expanded = new Set<number>();            // node ids that already have a full (non-repeat) row
  private root: Row | undefined;                   // cached: VS Code asks for the root again when the view reappears

  private changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;

  setGraph(uri: string, graph: TraceGraph) {
    this.uri = uri;
    this.graph = graph;
    this.parentsOf = new Map();
    this.expanded = new Set();
    this.root = undefined;
    for (const [parent, child] of graph.edges) {
      this.parentsOf.set(child, [...(this.parentsOf.get(child) ?? []), parent]);
    }
    this.changed.fire();
  }

  // No element: the root (the hovered entry). Otherwise: the entries its type came from,
  // each a full row the first time its node appears and a repeat after that.
  getChildren(row?: Row): Row[] {
    if (!this.graph) {
      return [];
    }
    if (!row) {
      this.root ??= this.makeRow(0);
      return [this.root];
    }
    if (row.repeat) {
      return [];
    }
    row.children ??= (this.parentsOf.get(row.node.id) ?? []).map((id) => this.makeRow(id));
    return row.children;
  }

  private makeRow(id: number): Row {
    const repeat = this.expanded.has(id);
    this.expanded.add(id);
    return { node: this.graph!.nodes[id], repeat };
  }

  getTreeItem(row: Row): vscode.TreeItem {
    const node = row.node;
    const hasParents = !row.repeat && (this.parentsOf.get(node.id) ?? []).length > 0;
    const item = new vscode.TreeItem(
      node.code,
      hasParents ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None,
    );
    item.description = `${row.repeat ? '↻ shown above · ' : ''}${node.type} · line ${node.line}`;
    item.tooltip = `${node.code}\n${node.type}, this file, line ${node.line}`;
    item.command = { command: 'rune.jumpToLine', title: 'Jump to line', arguments: [node.file ?? this.uri, node.line] };
    return item;
  }
}

const provider = new TraceTreeProvider();
let treeView: vscode.TreeView<Row> | undefined;

// Called once from activate()
export function registerTraceTree(context: vscode.ExtensionContext) {
  treeView = vscode.window.createTreeView(TRACE_VIEW_ID, { treeDataProvider: provider });
  treeView.message = 'Hover a variable and click "View as graph".';
  context.subscriptions.push(treeView);
}

// Fill the tree and bring the view into focus
export async function showTraceTree(uri: string, graph: TraceGraph) {
  provider.setGraph(uri, graph);
  if (treeView) {
    treeView.message = undefined;
    treeView.description = graph.name;
  }
  await vscode.commands.executeCommand(`${TRACE_VIEW_ID}.focus`);
}

// Opens the file and puts the cursor on `line` (1-based, as in ast)
export async function jumpToLine(uri: string, line: number, viewColumn?: vscode.ViewColumn) {
  const position = new vscode.Position(line - 1, 0);
  const editor = await vscode.window.showTextDocument(vscode.Uri.parse(uri), { viewColumn });
  editor.selection = new vscode.Selection(position, position);
  editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
}
