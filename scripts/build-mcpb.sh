#!/usr/bin/env bash
#
# Build the fecfile-mcp MCPB bundle — the MCP server packaged for Claude Desktop
# (and other MCPB-compatible hosts). The bundle exposes search_committees and
# get_filings, and prompts the user for an FEC API key at install time.
#
# Needs Node.js. The mcpb CLI is run via `npx` (no global install required); a
# global `mcpb` on your PATH is used instead if present.
# Tested against @anthropic-ai/mcpb 2.x.
#
set -euo pipefail

# This script lives in <repo-root>/scripts/. Move to the repo root so that
# `mcpb pack .` packs the right files (and reads .mcpbignore).
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# The mcpb CLI ships on npm and needs Node.js. Prefer a global `mcpb` if present;
# otherwise run it on demand with `npx` (this is what makes CI work without a
# global install). If neither is available, Node.js itself is missing.
if command -v mcpb >/dev/null 2>&1; then
  MCPB=(mcpb)
elif command -v npx >/dev/null 2>&1; then
  # Pinned to major 2 so a release build can't silently jump to a new major.
  MCPB=(npx --yes @anthropic-ai/mcpb@2)
else
  echo "Error: need the 'mcpb' CLI, which requires Node.js (for npx)." >&2
  echo "  Install Node.js (it includes npx):  https://nodejs.org" >&2
  echo "  Or install the CLI globally:  npm install -g @anthropic-ai/mcpb" >&2
  exit 1
fi

command -v jq >/dev/null 2>&1 || { echo "Error: 'jq' is required to read manifest.json." >&2; exit 1; }

NAME="$(jq -r '.name' manifest.json)"
VERSION="$(jq -r '.version' manifest.json)"
[ -n "$NAME" ] && [ "$NAME" != "null" ] || { echo "Error: could not read .name from manifest.json" >&2; exit 1; }
[ -n "$VERSION" ] && [ "$VERSION" != "null" ] || { echo "Error: could not read .version from manifest.json" >&2; exit 1; }

OUTPUT_DIR="dist"
OUTPUT_FILE="${OUTPUT_DIR}/${NAME}-${VERSION}.mcpb"

echo "Building ${NAME} MCPB bundle v${VERSION}..."
echo ""

echo "Validating manifest..."
"${MCPB[@]}" validate manifest.json
echo "OK: manifest valid"
echo ""

mkdir -p "$OUTPUT_DIR"

echo "Packing bundle..."
"${MCPB[@]}" pack . "$OUTPUT_FILE"

echo ""
echo "Built: ${OUTPUT_FILE}"
echo ""
echo "To test in Claude Desktop:"
echo "  1. Open the .mcpb file (double-click) or drag it into Settings -> Extensions"
echo "  2. Enter your FEC API key when prompted"
echo "  3. Ask Claude to search for a committee and pull its filings"
