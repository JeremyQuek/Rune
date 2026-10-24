import * as path from 'path';
import * as vscode from 'vscode';
import { LanguageClient, LanguageClientOptions, ServerOptions } from 'vscode-languageclient/node';
import { TraceGraph, jumpToLine, registerTraceTree, showTraceTree } from './trace_tree';
import { showTraceWebview } from './trace_webview';

/*
 * Minimal Rune VS Code client.
 *
 * All it does is launch src/lsp_server/server.py and let vscode-languageclient
 * handle the LSP traffic (document sync, hover requests, rendering replies).
 */

let client: LanguageClient;

export function activate(context: vscode.ExtensionContext) {
  // This extension lives in src/ide_client, the server in src/lsp_server
  const serverScript = path.join(context.extensionPath, '..', 'lsp_server', 'server.py');

  // Set RUNE_PYTHON to a venv's python if pygls isn't installed in python3
  const python = process.env.RUNE_PYTHON || 'python3';

  const serverOptions: ServerOptions = {
    command: python,
    args: [serverScript],
  };

  const clientOptions: LanguageClientOptions = {
    documentSelector: [{ scheme: 'file', language: 'python' }],
    // Lets the "Show trace" link in hovers run our rune.showTrace command
    markdown: { isTrusted: true },
  };

  // showTrace / showGraph are run from hover links with [uri, graph],
  // jumpToLine from clicks on the trace tree
  registerTraceTree(context);
  context.subscriptions.push(
    vscode.commands.registerCommand('rune.showTrace', (uri: string, graph: TraceGraph) => showTrace(context, uri, graph)),
    vscode.commands.registerCommand('rune.showGraph', (uri: string, graph: TraceGraph) => showGraph(context, uri, graph)),
    vscode.commands.registerCommand('rune.jumpToLine', jumpToLine),
  );

  client = new LanguageClient('rune', 'Rune', serverOptions, clientOptions);
  client.start();
}

// Shows the trace as a dropdown list; picking a step jumps to its line,
// picking "View as graph" opens the graph views instead
async function showTrace(context: vscode.ExtensionContext, uri: string, graph: TraceGraph) {
  const viewAsGraph = { label: '$(type-hierarchy) View as graph', description: '', line: 0 };
  const steps = graph.nodes.map((node) => ({
    label: node.code,
    description: `${node.type} · this file, line ${node.line}`,
    line: node.line,
  }));

  const picked = await vscode.window.showQuickPick([viewAsGraph, ...steps], {
    placeHolder: 'Variable trace: pick a step to jump to it',
  });
  if (!picked) {
    return;
  }
  if (picked === viewAsGraph) {
    await showGraph(context, uri, graph);
    return;
  }
  await jumpToLine(uri, picked.line);
}

// "View as graph": the tree in the Explorer and the drawn DAG beside the code
async function showGraph(context: vscode.ExtensionContext, uri: string, graph: TraceGraph) {
  showTraceWebview(context, uri, graph);
  await showTraceTree(uri, graph);
}

export function deactivate() {
  return client?.stop();
}
