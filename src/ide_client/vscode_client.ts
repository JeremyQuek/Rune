import * as path from 'path';
import * as vscode from 'vscode';
import { LanguageClient, LanguageClientOptions, ServerOptions } from 'vscode-languageclient/node';

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

  context.subscriptions.push(vscode.commands.registerCommand('rune.showTrace', showTrace));

  client = new LanguageClient('rune', 'Rune', serverOptions, clientOptions);
  client.start();
}

type TraceStep = { code: string; line: number };

// Shows the trace as a dropdown list; picking a step jumps to its line
async function showTrace(uri: string, steps: TraceStep[]) {
  const picked = await vscode.window.showQuickPick(
    steps.map((step) => ({
      label: step.code,
      description: `this file, line ${step.line}`,
      step,
    })),
    { placeHolder: 'Variable trace: pick a step to jump to it' },
  );
  if (!picked) {
    return;
  }

  const position = new vscode.Position(picked.step.line - 1, 0); // ast lines are 1-based
  const editor = await vscode.window.showTextDocument(vscode.Uri.parse(uri));
  editor.selection = new vscode.Selection(position, position);
  editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
}

export function deactivate() {
  return client?.stop();
}
