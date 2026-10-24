import * as vscode from 'vscode';

/*
 * Shows a variable's trace as a native tree in the Explorer sidebar ("Rune Trace").
 *
 * The server sends a TraceGraph (see trace_graph() in server.py). The hovered
 * entry is the root, and expanding a row shows the entries its type came from.
 * A DAG shown as a tree repeats shared parents under each child.
 * Clicking a row jumps to its line.
 */

// Contract with server.py
export type TraceNode = { id: number; code: string; line: number; type: string };
export type TraceGraph = {
  name: string;               // hovered symbol
  nodes: TraceNode[];         // id 0 is the hovered entry, then BFS order; nodes[id].id === id
  edges: [number, number][];  // [parent_id, child_id]: the type flows parent -> child
};

export const TRACE_VIEW_ID = 'runeTrace';

class TraceTreeProvider implements vscode.TreeDataProvider<TraceNode> {
  private uri = '';
  private graph: TraceGraph | undefined;
  private parentsOf = new Map<number, number[]>(); // child id -> parent ids

  private changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;

  setGraph(uri: string, graph: TraceGraph) {
    this.uri = uri;
    this.graph = graph;
    this.parentsOf = new Map();
    for (const [parent, child] of graph.edges) {
      this.parentsOf.set(child, [...(this.parentsOf.get(child) ?? []), parent]);
    }
    this.changed.fire();
  }

  // No element: the root (the hovered entry). Otherwise: the entries its type came from.
  getChildren(node?: TraceNode): TraceNode[] {
    if (!this.graph) {
      return [];
    }
    const ids = node ? this.parentsOf.get(node.id) ?? [] : [0];
    return ids.map((id) => this.graph!.nodes[id]);
  }

  getTreeItem(node: TraceNode): vscode.TreeItem {
    const hasParents = (this.parentsOf.get(node.id) ?? []).length > 0;
    const item = new vscode.TreeItem(
      node.code,
      hasParents ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None,
    );
    item.description = `${node.type} · line ${node.line}`;
    item.tooltip = `${node.code}\n${node.type}, this file, line ${node.line}`;
    item.command = { command: 'rune.jumpToLine', title: 'Jump to line', arguments: [this.uri, node.line] };
    return item;
  }
}

const provider = new TraceTreeProvider();
let treeView: vscode.TreeView<TraceNode> | undefined;

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
