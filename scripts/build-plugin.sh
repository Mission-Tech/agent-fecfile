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

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Create temporary staging directory
STAGING=$(mktemp -d)
trap "rm -rf $STAGING" EXIT

echo "Copying plugin files to staging..."

# Copy plugin structure
cp -r .claude-plugin "$STAGING/"
cp -r skills "$STAGING/"
cp .mcp.json "$STAGING/"
cp README.md "$STAGING/"
cp LICENSE "$STAGING/"
cp CHANGELOG.md "$STAGING/"

# Create plugin archive (zip with .plugin extension)
echo "Creating plugin archive..."
FULL_OUTPUT_PATH="$(pwd)/$OUTPUT_FILE"
cd "$STAGING"
zip -r -q "$FULL_OUTPUT_PATH" .
cd - > /dev/null

echo ""
echo "✓ Built: $OUTPUT_FILE"
echo ""
echo "To test locally:"
echo "  claude plugin install $OUTPUT_FILE"
echo ""
echo "Note: This plugin requires the fecfile-mcp MCPB to be installed"
echo "      for MCP tools. See README for installation instructions."
