import * as path from 'path';
import * as vscode from 'vscode';
import { TraceGraph, TraceNode, jumpToLine } from './trace_tree';

/*
 * Draws a variable's trace as a DAG in a webview panel beside the code.
 *
 * Takes the same TraceGraph as the tree (see trace_graph() in server.py),
 * turns it into Mermaid text, and Mermaid (bundled from node_modules, since
 * webviews block remote scripts) lays it out. The page is styled from VS Code's
 * theme variables, supports pan/zoom, and clicking a node jumps to its line.
 *
 * Node kinds:
 *   hovered  the variable you hovered (node 0)
 *   step     derived from other entries (has parents)
 *   source   where a type starts (no parents, e.g. a literal)
 */

let panel: vscode.WebviewPanel | undefined; // one panel, reused for every graph
let panelUri = '';                          // file the current graph belongs to

type NodeKind = 'hovered' | 'step' | 'source';

export function showTraceWebview(context: vscode.ExtensionContext, uri: string, graph: TraceGraph) {
  const mermaidDir = vscode.Uri.file(path.join(context.extensionPath, 'node_modules', 'mermaid', 'dist'));

  if (!panel) {
    panel = vscode.window.createWebviewPanel('runeTraceGraph', 'Rune trace', vscode.ViewColumn.Beside, {
      enableScripts: true,
      localResourceRoots: [mermaidDir],
    });
    panel.onDidDispose(() => (panel = undefined));
    // The webview posts { line } when a node is clicked; open it in the code column
    panel.webview.onDidReceiveMessage((message: { line: number }) => jumpToLine(panelUri, message.line, vscode.ViewColumn.One));
  }

  panelUri = uri;
  panel.title = `Type Graph: ${graph.name}`;
  panel.webview.html = renderHtml(panel.webview, vscode.Uri.joinPath(mermaidDir, 'mermaid.min.js'), uri, graph);
  panel.reveal(vscode.ViewColumn.Beside, true); // true: keep focus on the code
}

// ---------- graph -> Mermaid ---------- //

function nodeKinds(graph: TraceGraph): Map<number, NodeKind> {
  const hasParents = new Set(graph.edges.map(([, child]) => child));
  return new Map(
    graph.nodes.map((node): [number, NodeKind] => [
      node.id,
      node.id === 0 ? 'hovered' : hasParents.has(node.id) ? 'step' : 'source',
    ]),
  );
}

// A node card: the code on top, a type pill, file and line underneath
function nodeLabel(node: TraceNode, fileName: string): string {
  return (
    `<div class='code'>${escapeLabel(node.code)}</div>` +
    `<div class='meta'><span class='type'>${escapeLabel(node.type)}</span><span class='line'>line ${node.line}</span></div>` +
    `<div class='file'>${escapeLabel(fileName)}</div>`
  );
}

function toMermaid(graph: TraceGraph, kinds: Map<number, NodeKind>, fileName: string): string {
  const lines = ['flowchart TD'];
  for (const node of graph.nodes) {
    lines.push(`  n${node.id}("${nodeLabel(node, fileName)}")`);
    lines.push(`  class n${node.id} ${kinds.get(node.id)}`);
    lines.push(`  click n${node.id} runeJump`); // calls window.runeJump("n<id>")
  }
  for (const [parent, child] of graph.edges) {
    lines.push(`  n${parent} --> n${child}`);
  }
  // Real colours come from the page CSS; these only register the class names
  lines.push('  classDef hovered stroke-width:2px', '  classDef step stroke-width:1px', '  classDef source stroke-width:1px');
  return lines.join('\n');
}

// Mermaid labels are quoted, so these characters become Mermaid entities
function escapeLabel(text: string): string {
  return text
    .replace(/&/g, '#amp;')
    .replace(/"/g, '#quot;')
    .replace(/</g, '#lt;')
    .replace(/>/g, '#gt;');
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ---------- page ---------- //

function renderHtml(webview: vscode.Webview, mermaidUri: vscode.Uri, uri: string, graph: TraceGraph): string {
  const nonce = Math.random().toString(36).slice(2);
  // JSON goes inside a <script>, so escape "<" to keep "</script>" in code from closing it
  const toScript = (value: unknown) => JSON.stringify(value).replace(/</g, '\\u003c');

  const kinds = nodeKinds(graph);
  const sourceCount = [...kinds.values()].filter((kind) => kind === 'source').length;
  const fileName = decodeURIComponent(path.posix.basename(vscode.Uri.parse(uri).path));
  const lineById = Object.fromEntries(graph.nodes.map((node) => [`n${node.id}`, node.line]));
  const hovered = graph.nodes[0];

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; script-src 'nonce-${nonce}'; style-src ${webview.cspSource} 'unsafe-inline'; img-src ${webview.cspSource} data:; font-src ${webview.cspSource};">
  <style>
    :root {
      --bg: var(--vscode-editor-background, #1e1e1e);
      --fg: var(--vscode-editor-foreground, #d4d4d4);
      --muted: var(--vscode-descriptionForeground, #9d9d9d);
      --card: var(--vscode-editorWidget-background, #252526);
      --border: var(--vscode-widget-border, rgba(128, 128, 128, 0.35));
      --accent: var(--vscode-focusBorder, #3794ff);
      --step: var(--vscode-charts-blue, #3794ff);
      --source: var(--vscode-charts-green, #89d185);
      --hovered: var(--vscode-charts-purple, #b180d7);
    }

    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
      display: flex;
      flex-direction: column;
      overflow: hidden;
      background: var(--bg);
      color: var(--fg);
      font-family: var(--vscode-font-family, system-ui, sans-serif);
    }

    /* ----- header ----- */
    header {
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
      padding: 14px 18px;
      border-bottom: 1px solid var(--border);
    }
    .title { display: flex; align-items: center; gap: 10px; }
    .name {
      font-family: var(--vscode-editor-font-family, monospace);
      font-size: 18px;
      font-weight: 600;
    }
    .pill {
      padding: 2px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-family: var(--vscode-editor-font-family, monospace);
      color: var(--hovered);
      background: color-mix(in srgb, var(--hovered) 18%, transparent);
    }
    .sub { color: var(--muted); font-size: 12px; }
    .legend { display: flex; gap: 14px; margin-left: auto; color: var(--muted); font-size: 12px; }
    .legend span { display: flex; align-items: center; gap: 6px; }
    .dot { width: 9px; height: 9px; border-radius: 50%; }
    .dot.hovered { background: var(--hovered); }
    .dot.step { background: var(--step); }
    .dot.source { background: var(--source); }
    .tools { display: flex; gap: 4px; }
    .tools button {
      min-width: 30px;
      padding: 4px 10px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--vscode-button-secondaryBackground, transparent);
      color: var(--vscode-button-secondaryForeground, var(--fg));
      font: inherit;
      font-size: 12px;
      cursor: pointer;
    }
    .tools button:hover { background: var(--vscode-button-secondaryHoverBackground, rgba(128, 128, 128, 0.2)); }

    /* ----- canvas: dotted grid, pan/zoom ----- */
    #viewport {
      position: relative;
      flex: 1;
      overflow: hidden;
      cursor: grab;
      background-image: radial-gradient(var(--border) 1px, transparent 1px);
      background-size: 22px 22px;
    }
    #viewport.dragging { cursor: grabbing; }
    #canvas { position: absolute; top: 0; left: 0; transform-origin: 0 0; }
    #canvas.animate { transition: transform 0.25s ease; }
    #canvas svg { display: block; animation: appear 0.35s ease-out; }
    @keyframes appear { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

    .hint {
      position: absolute;
      right: 14px;
      bottom: 12px;
      color: var(--muted);
      font-size: 11px;
      pointer-events: none;
    }

    /* ----- nodes: cards with a coloured edge per kind ----- */
    #canvas .node { cursor: pointer; }
    #canvas .node rect, #canvas .node path {
      fill: var(--card) !important;
      stroke: var(--border) !important;
      stroke-width: 1px !important;
      filter: drop-shadow(0 3px 8px rgba(0, 0, 0, 0.25));
      transition: stroke 0.15s ease, filter 0.15s ease;
    }
    #canvas .node.step rect, #canvas .node.step path { stroke: color-mix(in srgb, var(--step) 70%, transparent) !important; }
    #canvas .node.source rect, #canvas .node.source path { stroke: color-mix(in srgb, var(--source) 80%, transparent) !important; }
    #canvas .node.hovered rect, #canvas .node.hovered path {
      stroke: var(--hovered) !important;
      stroke-width: 2px !important;
      filter: drop-shadow(0 0 12px color-mix(in srgb, var(--hovered) 55%, transparent));
    }
    #canvas .node:hover rect, #canvas .node:hover path {
      stroke: var(--accent) !important;
      filter: drop-shadow(0 0 10px color-mix(in srgb, var(--accent) 45%, transparent));
    }

    .code {
      color: var(--fg);
      font-family: var(--vscode-editor-font-family, monospace);
      font-size: 13px;
      white-space: nowrap;
    }
    .meta { display: flex; justify-content: center; gap: 8px; margin-top: 6px; font-size: 11px; }
    .type {
      padding: 1px 8px;
      border-radius: 999px;
      font-family: var(--vscode-editor-font-family, monospace);
      color: var(--step);
      background: color-mix(in srgb, var(--step) 16%, transparent);
    }
    .source .type { color: var(--source); background: color-mix(in srgb, var(--source) 16%, transparent); }
    .hovered .type { color: var(--hovered); background: color-mix(in srgb, var(--hovered) 18%, transparent); }
    .line { color: var(--muted); }
    .file { margin-top: 3px; color: var(--muted); font-size: 10.5px; opacity: 0.8; }

    /* ----- edges ----- */
    #canvas .flowchart-link, #canvas .edgePath path {
      stroke: var(--muted) !important;
      stroke-width: 1.5px !important;
      opacity: 0.8;
    }
    #canvas .arrowMarkerPath { fill: var(--muted) !important; stroke: var(--muted) !important; }
  </style>
</head>
<body>
  <header>
    <div class="title">
      <span class="name">${escapeHtml(graph.name)}</span>
      <span class="pill">${escapeHtml(hovered.type)}</span>
    </div>
    <div class="sub">${graph.nodes.length} steps · ${sourceCount} source${sourceCount === 1 ? '' : 's'} · ${escapeHtml(fileName)}</div>
    <div class="legend">
      <span><i class="dot hovered"></i>hovered</span>
      <span><i class="dot step"></i>derived</span>
      <span><i class="dot source"></i>source</span>
    </div>
    <div class="tools">
      <button id="zoomOut" title="Zoom out">−</button>
      <button id="fit" title="Fit to view">Fit</button>
      <button id="zoomIn" title="Zoom in">+</button>
    </div>
  </header>

  <div id="viewport">
    <div id="canvas"></div>
    <div class="hint">Click a node to jump to it · drag to pan · scroll to zoom</div>
  </div>

  <script nonce="${nonce}" src="${webview.asWebviewUri(mermaidUri)}"></script>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const lineById = ${toScript(lineById)};
    const viewport = document.getElementById('viewport');
    const canvas = document.getElementById('canvas');

    // ----- pan / zoom ----- //
    let scale = 1, x = 0, y = 0;
    let dragged = false; // a drag must not count as a click on a node

    function apply(animate) {
      canvas.classList.toggle('animate', !!animate);
      canvas.style.transform = 'translate(' + x + 'px, ' + y + 'px) scale(' + scale + ')';
    }

    function fit(animate) {
      const svg = canvas.querySelector('svg');
      if (!svg) return;
      const width = svg.viewBox.baseVal.width, height = svg.viewBox.baseVal.height, pad = 40;
      scale = Math.min((viewport.clientWidth - pad * 2) / width, (viewport.clientHeight - pad * 2) / height, 1.4);
      x = (viewport.clientWidth - width * scale) / 2;
      y = (viewport.clientHeight - height * scale) / 2;
      apply(animate);
    }

    // Zoom by factor k around a point in the viewport
    function zoom(k, px, py, animate) {
      const next = Math.min(4, Math.max(0.15, scale * k));
      x = px - (px - x) * next / scale;
      y = py - (py - y) * next / scale;
      scale = next;
      apply(animate);
    }

    viewport.addEventListener('wheel', (event) => {
      event.preventDefault();
      const rect = viewport.getBoundingClientRect();
      zoom(Math.exp(-event.deltaY * 0.0015), event.clientX - rect.left, event.clientY - rect.top, false);
    }, { passive: false });

    viewport.addEventListener('mousedown', (event) => {
      const startX = event.clientX - x, startY = event.clientY - y, originX = event.clientX, originY = event.clientY;
      dragged = false;
      viewport.classList.add('dragging');
      const move = (e) => {
        if (Math.abs(e.clientX - originX) + Math.abs(e.clientY - originY) > 3) dragged = true;
        x = e.clientX - startX;
        y = e.clientY - startY;
        apply(false);
      };
      const up = () => {
        viewport.classList.remove('dragging');
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', up);
      };
      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', up);
    });

    const center = () => [viewport.clientWidth / 2, viewport.clientHeight / 2];
    document.getElementById('zoomIn').onclick = () => zoom(1.25, ...center(), true);
    document.getElementById('zoomOut').onclick = () => zoom(0.8, ...center(), true);
    document.getElementById('fit').onclick = () => fit(true);
    window.addEventListener('resize', () => fit(false));

    // ----- clicks ----- //
    window.runeJump = (id) => {
      if (!dragged) vscode.postMessage({ line: lineById[id] });
    };

    // ----- render ----- //
    // Mermaid needs real colours for its own maths, so read them from the theme
    const css = getComputedStyle(document.documentElement);
    const color = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
    const dark = document.body.classList.contains('vscode-dark') || document.body.classList.contains('vscode-high-contrast');

    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'loose', // lets click directives call window.runeJump and keeps HTML in labels
      theme: 'base',
      themeVariables: {
        darkMode: dark,
        background: color('--vscode-editor-background', dark ? '#1e1e1e' : '#ffffff'),
        primaryColor: color('--vscode-editorWidget-background', dark ? '#252526' : '#f3f3f3'),
        primaryTextColor: color('--vscode-editor-foreground', dark ? '#d4d4d4' : '#333333'),
        lineColor: color('--vscode-descriptionForeground', '#9d9d9d'),
        fontFamily: color('--vscode-font-family', 'system-ui, sans-serif'),
        fontSize: '13px',
      },
      flowchart: { curve: 'basis', htmlLabels: true, useMaxWidth: false, nodeSpacing: 36, rankSpacing: 56, padding: 14 },
    });

    mermaid.render('trace', ${toScript(toMermaid(graph, kinds, fileName))}).then(({ svg, bindFunctions }) => {
      canvas.innerHTML = svg;
      const element = canvas.querySelector('svg');
      element.setAttribute('width', element.viewBox.baseVal.width);
      element.setAttribute('height', element.viewBox.baseVal.height);
      bindFunctions?.(canvas); // wires up the click directives
      fit(false);
    });
  </script>
</body>
</html>`;
}
