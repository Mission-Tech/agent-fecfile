#!/bin/bash
#
# Build script for Claude Code plugin (.plugin file)
# Creates a local plugin archive for testing before marketplace release
#
set -e

# Extract version from plugin.json
VERSION=$(jq -r '.version' .claude-plugin/plugin.json)
if [ -z "$VERSION" ] || [ "$VERSION" = "null" ]; then
    echo "Error: Could not read version from .claude-plugin/plugin.json"
    exit 1
fi

OUTPUT_DIR="dist"
OUTPUT_FILE="${OUTPUT_DIR}/fecfile-${VERSION}.plugin"

echo "Building Claude Code plugin v${VERSION}..."
echo ""

mkdir -p "$OUTPUT_DIR"

# Archive from committed content (HEAD), never the working tree, so untracked
# or gitignored files can't leak into the artifact.
echo "Creating plugin archive..."
git archive --format=zip HEAD \
    .claude-plugin skills README.md LICENSE CHANGELOG.md \
    -o "$OUTPUT_FILE"

echo ""
echo "✓ Built: $OUTPUT_FILE"
echo ""
echo "To test locally:"
echo "  claude plugin install $OUTPUT_FILE"
echo ""
echo "Note: This plugin requires the fecfile-mcp MCP server for FEC data."
echo "      See README for installation instructions."
