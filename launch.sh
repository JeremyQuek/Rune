#!/bin/zsh
set -e

# Launches a VS Code window with the Rune extension loaded.
# The extension starts src/lsp_server/server.py, which imports the analyzer.

root="${0:A:h}"
python="$root/src/lsp_server/.venv/bin/python"

if [[ ! -x "$python" ]]; then
  echo "Error: no venv at $root/src/lsp_server/.venv (run: cd src/lsp_server && python3 -m venv .venv && .venv/bin/pip install pygls)" >&2
  exit 1
fi

cd "$root/src/ide_client"
[[ -d node_modules ]] || npm install
npm run compile
echo "- Compiled client"

# Own profile (.vscode-dev) so the dev window doesn't share webview/service
# worker state with your main VS Code, which breaks webviews in the dev window
workspace="${1:-$HOME/Desktop/rune}"

RUNE_PYTHON="$python" code --user-data-dir "$root/.vscode-dev" \
  --extensionDevelopmentPath="$root/src/ide_client" \
  "$workspace"
echo "- Launched Rune extension"
