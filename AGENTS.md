# Claude Code Plugin: fecfile

This repo contains a Claude Code plugin for analyzing FEC (Federal Election Commission) campaign finance filings. It includes an Agent Skill and an MCP server that handles all FEC data access.

## Key Details

- **Plugin name**: `fecfile` (ships the Agent Skill only)
- **Skill name**: `fecfile`
- **MCP server**: `fec-api`, distributed as the `fecfile-mcp` MCPB bundle (desktop app) or run manually. Tools: `search_committees`, `get_filings`, `fetch_filing`, `analyze_filing`, `get_version`
- **Dependencies**: `mcp`, `httpx`, `fecfile` - managed via inline script metadata (PEP 723), auto-installed by `uv run`
- **Data sources** (reached only from inside the MCP server):
  - Public: `docquery.fec.gov` (fetch_filing, analyze_filing — no key)
  - Authenticated: `api.open.fec.gov` (search_committees, get_filings — needs `FEC_API_KEY`)
- **Python**: Requires 3.10+

## Project Structure

```
agent-fecfile/
├── .claude-plugin/
│   ├── plugin.json              # Plugin manifest (version source of truth)
│   └── marketplace.json         # Marketplace catalog for plugin distribution
├── manifest.json                # MCPB manifest for the MCP server bundle
├── mcp-server/
│   └── server.py                # MCP server (all FEC data access)
├── skills/fecfile/
│   ├── SKILL.md                 # Agent Skill instructions
│   └── references/              # Form and schedule documentation
│       ├── FORMS.md             # Reference for FEC form types (F1, F2, F3, F99)
│       └── SCHEDULES.md         # Field mappings for Schedules A, B, C, D, E
├── scripts/
│   ├── build-mcpb.sh            # Build the .mcpb bundle
│   └── build-plugin.sh          # Build the .plugin archive
├── .github/workflows/
│   └── mcpb-release.yml         # CI: build, verify, and release the .mcpb
├── README.md                    # Installation and usage for end users
├── CHANGELOG.md                 # Version history
└── release.sh                   # Automated release script
```

## Development Commands

**MCP server (manual run):**

- `FEC_API_KEY=your-key uv run mcp-server/server.py` — run from a clone (key optional; without it only the filing tools work)
- `uvx --from git+https://github.com/hodgesmr/agent-fecfile fecfile-mcp` — run straight from git (the `[project.scripts]` entry in pyproject.toml)

**Bundles:**

- `scripts/build-mcpb.sh` — validate the manifest and pack `dist/fecfile-mcp-<version>.mcpb` (runs the mcpb CLI via npx; needs Node.js)
- `scripts/build-plugin.sh` — build `dist/fecfile-<version>.plugin` for local testing

## Coding Style & Naming Conventions

- Python uses 4-space indentation and standard library `argparse` conventions
- MCP server uses the official `mcp` Python SDK with async/await
- Keep functions small and descriptive (e.g., `build_options`, `stream_filing`)
- Prefer straightforward, readable logic over clever abstractions
- No formatter is enforced; keep code PEP 8–friendly

## Testing Guidelines

- There is no automated test suite in this repository
- Validate changes manually by exercising the MCP tools with a known filing ID
- For skill changes, test with `claude --plugin-dir .` from the repo root
- For large filings, verify `fetch_filing` (`summary_only`, `min_amount`) and `analyze_filing` behavior

## Releases

Releases use semver tags (e.g., `3.0.0`) plus a `latest` tag that always points to the most recent stable release. The GitHub Actions workflow (`.github/workflows/mcpb-release.yml`) builds and verifies the `.mcpb` on every PR, and attaches it to a GitHub Release on pushes to main and version tags.

### Versioning Strategy

The version is tracked in **several places** that must stay in sync:

1. `.claude-plugin/plugin.json` - Primary source of truth
2. `skills/fecfile/SKILL.md` - Metadata frontmatter
3. `manifest.json` - MCPB bundle version
4. `pyproject.toml` - Python project version
5. `mcp-server/server.py` - `SERVER_VERSION` constant (what `get_version` reports)
6. `CHANGELOG.md` - Version history

### Release Process

1. Bump the version in all the files listed above

2. Update `CHANGELOG.md`:
   - Add a new section at the top (below the header) for the new version
   - Use the format `## [X.Y.Z] - YYYY-MM-DD`
   - Document changes under `### Added`, `### Changed`, `### Fixed`, or `### Removed`
   - Add a comparison link at the bottom: `[X.Y.Z]: https://github.com/hodgesmr/agent-fecfile/compare/PREV...X.Y.Z`

3. Commit the version bump and changelog update

4. Run the release script:
   ```bash
   ./release.sh
   ```

The script extracts the version from plugin.json, creates the version tag, updates the `latest` tag, and pushes both. The tag push triggers the CI workflow, which builds the `.mcpb` and attaches it to the Release.

## Architecture Notes

### MCP Server

The MCP server (`mcp-server/server.py`) handles all FEC network access:

- Reads the FEC API key from the `FEC_API_KEY` environment variable **on first tool use** (lazy loading); the key is optional and only gates the search tools
- MCPB's `user_config` handles keychain storage and injects the key via env var
- Key held in memory, never exposed to the model
- `fetch_filing` and `analyze_filing` stream filings from the public archive with the `fecfile` library — pagination, `min_amount` filtering, top-N, and group-totals all run server-side so large filings never enter the model's context
- Uses stdio transport; works with any MCP-compatible runtime

### Agent Skill

The skill (`skills/fecfile/SKILL.md`) provides:

- Instructions for analyzing FEC filings through the MCP tools only (it makes no network calls itself)
- A first-time check that detects a missing server and walks the user through installing it
- Field reference for forms and schedules
- Large filing handling strategies (server-side reduction first)

## Acknowledgments

- Built on the [fecfile](https://github.com/esonderegger/fecfile) library by Evan Sonderegger
- Inspired by [llm-fecfile](https://github.com/dwillis/llm-fecfile) by Derek Willis
