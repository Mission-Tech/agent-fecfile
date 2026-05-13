#!/bin/bash
#
# Build script for FEC Filing MCPB bundle
# Tested with @anthropic-ai/mcpb@2.1.2
#
set -e

# Extract version from manifest.json
VERSION=$(jq -r '.version' manifest.json)
if [ -z "$VERSION" ] || [ "$VERSION" = "null" ]; then
    echo "Error: Could not read version from manifest.json"
    exit 1
fi

OUTPUT_DIR="dist"
OUTPUT_FILE="${OUTPUT_DIR}/fecfile-mcp-${VERSION}.mcpb"

echo "Building MCPB bundle v${VERSION}..."
echo ""

# Validate manifest before packing
echo "Validating manifest..."
if ! mcpb validate manifest.json; then
    echo "Error: Manifest validation failed"
    exit 1
fi
echo "✓ Manifest valid"
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Pack the bundle
echo "Packing bundle..."
mcpb pack . "$OUTPUT_FILE"

echo ""
echo "✓ Built: $OUTPUT_FILE"
echo ""
echo "To test:"
echo "  1. Double-click $OUTPUT_FILE"
echo "  2. Enter FEC API key when prompted"
echo "  3. Test in Claude Desktop"
