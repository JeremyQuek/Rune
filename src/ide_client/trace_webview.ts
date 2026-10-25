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
 * Hovering a node shows its rhs broken into operands and their types.
 * The Filter by file dropdown dims every node outside the chosen file; "Group by file" redraws
 * the graph with one box per file.
 *
 * Node kinds:
 *   hovered  the variable you hovered (node 0)
 *   step     derived from other entries (has parents)
 *   source   where a type starts (no parents, e.g. a literal)
 */

let panel: vscode.WebviewPanel | undefined; // one panel, reused for every graph

type NodeKind = 'hovered' | 'step' | 'source';

export function showTraceWebview(context: vscode.ExtensionContext, graph: TraceGraph) {
  const mermaidDir = vscode.Uri.file(path.join(context.extensionPath, 'node_modules', 'mermaid', 'dist'));

  if (!panel) {
    panel = vscode.window.createWebviewPanel('runeTraceGraph', 'Rune trace', vscode.ViewColumn.Beside, {
      enableScripts: true,
      localResourceRoots: [mermaidDir],
    });
    panel.onDidDispose(() => (panel = undefined));
    // The webview posts { file, line } when a node is clicked; open it in the code column
    panel.webview.onDidReceiveMessage((message: { file: string; line: number }) =>
      jumpToLine(message.file, message.line, vscode.ViewColumn.One),
    );
  }

  panel.title = `Type Graph: ${graph.name}`;
  panel.webview.html = renderHtml(panel.webview, vscode.Uri.joinPath(mermaidDir, 'mermaid.min.js'), graph);
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

function baseName(file: string): string {
  return decodeURIComponent(path.posix.basename(vscode.Uri.parse(file).path));
}

// A node card: the code on top, a type pill, file and line underneath
function nodeLabel(node: TraceNode): string {
  return (
    `<div class='code'>${escapeLabel(node.code)}</div>` +
    `<div class='meta'><span class='type'>${escapeLabel(node.type)}</span><span class='line'>line ${node.line}</span></div>` +
    `<div class='file'>${escapeLabel(baseName(node.file))}</div>`
  );
}

// grouped: wrap each file's nodes in a subgraph f<index into files>
function toMermaid(graph: TraceGraph, kinds: Map<number, NodeKind>, files: string[], grouped: boolean): string {
  const lines = ['flowchart TD'];
  const declare = (node: TraceNode) => lines.push(`  n${node.id}("${nodeLabel(node)}")`);
  if (grouped) {
    files.forEach((file, i) => {
      lines.push(`  subgraph f${i}["${escapeLabel(baseName(file))}"]`);
      graph.nodes.filter((node) => node.file === file).forEach(declare);
      lines.push('  end');
    });
  } else {
    graph.nodes.forEach(declare);
  }
  for (const node of graph.nodes) {
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

function renderHtml(webview: vscode.Webview, mermaidUri: vscode.Uri, graph: TraceGraph): string {
  const nonce = Math.random().toString(36).slice(2);
  // JSON goes inside a <script>, so escape "<" to keep "</script>" in code from closing it
  const toScript = (value: unknown) => JSON.stringify(value).replace(/</g, '\\u003c');

  const kinds = nodeKinds(graph);
  const sourceCount = [...kinds.values()].filter((kind) => kind === 'source').length;
  const files = [...new Set(graph.nodes.map((node) => node.file))]; // in BFS order, hovered file first
  const fileNames = files.map(baseName);
  const nodeById = Object.fromEntries(graph.nodes.map((node) => [`n${node.id}`, { ...node, kind: kinds.get(node.id) }]));
  const hovered = graph.nodes[0];
  const fileOptions = files
    .map((file, i) => `<option value="${i}" title="${escapeHtml(file)}">${escapeHtml(fileNames[i])}</option>`)
    .join('');

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; script-src 'nonce-${nonce}'; style-src ${webview.cspSource} 'unsafe-inline'; img-src ${webview.cspSource} data:; font-src ${webview.cspSource};">
  <style>
    :root {
      /* a few shades darker than the editor so the panel stands out */
      --bg: color-mix(in srgb, var(--vscode-editor-background, #1e1e1e) 72%, black);
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
    .tools button.on { border-color: var(--accent); color: var(--fg); }

    /* ----- filter by file: focus one file ----- */
    .filter { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; }
    .filter select {
      max-width: 220px;
      padding: 4px 8px;
      border: 1px solid var(--vscode-dropdown-border, var(--border));
      border-radius: 6px;
      background: var(--vscode-dropdown-background, var(--card));
      color: var(--vscode-dropdown-foreground, var(--fg));
      font: inherit;
      font-size: 12px;
      cursor: pointer;
    }
    .filter select:focus { outline: 1px solid var(--accent); }
    .filter select.active { border-color: var(--accent); }
    #canvas .dim { opacity: 0.15; }
    #canvas .node, #canvas .cluster, #canvas path { transition: opacity 0.2s ease; }

    /* ----- file boxes (Group by file) ----- */
    #canvas .cluster rect {
      fill: color-mix(in srgb, var(--fg) 4%, transparent) !important;
      stroke: var(--border) !important;
      stroke-dasharray: 5 4;
      rx: 12px;
      ry: 12px;
    }
    #canvas .cluster-label, #canvas .cluster .nodeLabel { color: var(--muted) !important; font-size: 12px; }

    /* ----- node hover: the rhs broken into operands ----- */
    #tip {
      position: absolute;
      z-index: 5;
      min-width: 210px;
      max-width: 380px;
      padding: 10px 12px;
      border: 1px solid var(--vscode-editorHoverWidget-border, var(--border));
      border-radius: 8px;
      background: var(--vscode-editorHoverWidget-background, var(--card));
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
      font-size: 12px;
      pointer-events: none;
      opacity: 0;
      transition: opacity 0.12s ease;
    }
    #tip.show { opacity: 1; }
    #tip .head {
      margin-bottom: 6px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--border);
      font-family: var(--vscode-editor-font-family, monospace);
      font-size: 13px;
      white-space: nowrap;
    }
    #tip .label { margin-bottom: 4px; color: var(--muted); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.06em; }
    #tip .row { display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: center; padding: 3px 0; }
    #tip .row code { font-family: var(--vscode-editor-font-family, monospace); }
    #tip .where { min-width: 52px; color: var(--muted); text-align: right; }
    #tip .empty { color: var(--muted); }
    #tip .result {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 6px;
      padding-top: 8px;
      border-top: 1px solid var(--border);
      color: var(--muted);
    }

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
    <div class="sub">${graph.nodes.length} steps · ${sourceCount} source${sourceCount === 1 ? '' : 's'} · ${files.length} file${files.length === 1 ? '' : 's'}</div>
    <label class="filter">Filter by file
      <select id="fileFilter"><option value="">All files</option>${fileOptions}</select>
    </label>
    <div class="legend">
      <span><i class="dot hovered"></i>hovered</span>
      <span><i class="dot step"></i>derived</span>
      <span><i class="dot source"></i>source</span>
    </div>
    <div class="tools">
      <button id="group" title="Draw one box per file">Group by file</button>
      <button id="zoomOut" title="Zoom out">−</button>
      <button id="fit" title="Fit to view">Fit</button>
      <button id="zoomIn" title="Zoom in">+</button>
    </div>
  </header>

  <div id="viewport">
    <div id="canvas"></div>
    <div id="tip"></div>
    <div class="hint">Hover a node for its operands · click to jump · drag to pan · scroll to zoom</div>
  </div>

  <script nonce="${nonce}" src="${webview.asWebviewUri(mermaidUri)}"></script>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const nodeById = ${toScript(nodeById)};
    const files = ${toScript(files)};
    const diagrams = { flat: ${toScript(toMermaid(graph, kinds, files, false))}, grouped: ${toScript(toMermaid(graph, kinds, files, true))} };
    const viewport = document.getElementById('viewport');
    const canvas = document.getElementById('canvas');
    const tip = document.getElementById('tip');

    const esc = (text) => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

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
      hideTip();
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
      const node = nodeById[id];
      if (!dragged && node) vscode.postMessage({ file: node.file, line: node.line });
    };

    // Mermaid ids DOM elements as [prefix-]flowchart-n3-<k> (nodes), L_n1_n3_<k> (edges)
    // and [prefix-]f0 (file boxes), so map them back to graph ids
    const nodeIdOf = (el) => (el.id.match(/flowchart-(n\\d+)-\\d+$/) || [])[1];
    const edgeEndsOf = (el) => el.id.match(/L[-_](n\\d+)[-_](n\\d+)[-_]\\d+$/);
    const fileIndexOf = (el) => (el.id.match(/(?:^|-)f(\\d+)$/) || [])[1];

    // ----- node hover: operands ----- //
    function tipHtml(node) {
      const rows = node.operands.map((op) =>
        '<div class="row"><code>' + esc(op.name) + '</code>' +
        '<span class="type">' + esc(op.type) + '</span>' +
        '<span class="where">' + (op.line != null ? 'line ' + op.line : op.type === 'Unknown' ? 'unresolved' : 'literal') + '</span></div>'
      ).join('');
      return '<div class="head">' + esc(node.code) + '</div>' +
        '<div class="label">operands</div>' +
        (rows || '<div class="empty">none: the type comes from the annotation</div>') +
        '<div class="result"><span>result</span><span class="type">' + esc(node.type) + '</span></div>';
    }

    function showTip(id, event) {
      const node = nodeById[id];
      if (!node || viewport.classList.contains('dragging')) return;
      tip.innerHTML = tipHtml(node);
      tip.className = 'show ' + node.kind; // kind recolours the type pills like the card
      moveTip(event);
    }

    function moveTip(event) {
      const rect = viewport.getBoundingClientRect();
      const left = Math.min(event.clientX - rect.left + 16, viewport.clientWidth - tip.offsetWidth - 8);
      const top = Math.min(event.clientY - rect.top + 16, viewport.clientHeight - tip.offsetHeight - 8);
      tip.style.left = Math.max(8, left) + 'px';
      tip.style.top = Math.max(8, top) + 'px';
    }

    function hideTip() { tip.className = ''; }

    function wireNodes() {
      canvas.querySelectorAll('g.node').forEach((el) => {
        const id = nodeIdOf(el);
        if (!id) return;
        el.addEventListener('mouseenter', (event) => showTip(id, event));
        el.addEventListener('mousemove', moveTip);
        el.addEventListener('mouseleave', hideTip);
      });
    }

    // ----- focus a file: everything else goes dark ----- //
    let focus = null; // file uri, or null for all

    function applyFocus() {
      const outside = (id) => focus !== null && nodeById[id]?.file !== focus;
      canvas.querySelectorAll('g.node').forEach((el) => {
        const id = nodeIdOf(el);
        if (id) el.classList.toggle('dim', outside(id));
      });
      canvas.querySelectorAll('path').forEach((el) => {
        const ends = edgeEndsOf(el);
        if (ends) el.classList.toggle('dim', outside(ends[1]) || outside(ends[2]));
      });
      canvas.querySelectorAll('g.cluster').forEach((el) => {
        const i = fileIndexOf(el);
        if (i !== undefined) el.classList.toggle('dim', focus !== null && files[i] !== focus);
      });
      fileFilter.classList.toggle('active', focus !== null);
    }

    const fileFilter = document.getElementById('fileFilter');
    fileFilter.onchange = () => {
      focus = fileFilter.value === '' ? null : files[fileFilter.value]; // '' is All files
      applyFocus();
    };

    // ----- group by file ----- //
    let grouped = false;
    const groupButton = document.getElementById('group');
    groupButton.onclick = () => {
      grouped = !grouped;
      groupButton.classList.toggle('on', grouped);
      draw();
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

    let renders = 0; // each render needs a fresh id
    async function draw() {
      hideTip();
      const { svg, bindFunctions } = await mermaid.render('trace' + renders++, grouped ? diagrams.grouped : diagrams.flat);
      canvas.innerHTML = svg;
      const element = canvas.querySelector('svg');
      element.setAttribute('width', element.viewBox.baseVal.width);
      element.setAttribute('height', element.viewBox.baseVal.height);
      bindFunctions?.(canvas); // wires up the click directives
      wireNodes();
      applyFocus();
      fit(false);
    }
    draw();
  </script>
</body>
</html>`;
}
