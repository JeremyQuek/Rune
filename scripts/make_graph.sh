#!/bin/bash
# Pretty-prints a CFG edge list (paste into graphonline.top). Run from anywhere.
cd "$(dirname "$0")/.." && python3 src/lsp_server/modules/cfg_generator.py
