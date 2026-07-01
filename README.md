# agent-fecfile

![agent-fecfile](./agent-fecfile.jpeg)

## FEC Filing Plugin for Claude

A [Claude Code plugin](https://docs.anthropic.com/en/docs/claude-code/plugins) for analyzing Federal Election Commission (FEC) campaign finance filings. Includes an [Agent Skill](https://agentskills.io) and an [MCP server](https://modelcontextprotocol.io) that handles all FEC data access.

This project enables AI agents to fetch, parse, and analyze FEC filings directly within agent sessions. Filing retrieval and heavy reduction (top items, group totals) happen inside the MCP server — outside the model context — so agents can work with filings of any size without flooding their context window, and without needing network access to FEC hosts or a copy of the API key.

The skill includes detailed field mappings for common form types and schedules, helping agents accurately interpret campaign finance data like contributions, disbursements, and committee information.

## Features

- Search for committees and filings via the FEC API (`search_committees`, `get_filings`)
- Fetch filing summaries and schedule itemizations by filing ID, no API key needed (`fetch_filing`)
- Server-side analysis of whole filings — top N items by amount, totals grouped by any field — in constant memory (`analyze_filing`)
- Support for major form types (F1, F2, F3, F99) with detailed field mappings
- API key stored in your system keychain (Claude desktop app) or an environment variable — never visible to the model

## Two Components

| Component | What it is | Installed as |
|---|---|---|
| **Agent Skill** (`fecfile`) | The analysis workflow and form/schedule references | Claude Code plugin (CLI or desktop app) |
| **MCP server** (`fecfile-mcp`) | All FEC data access: search, fetch, analyze | MCPB bundle (desktop app) or manual MCP config (Claude Code, other runtimes) |

The skill tells the agent *how* to analyze filings; the MCP server provides the tools that actually touch the FEC. You need both. If the server isn't installed, the skill stops and walks you through setting it up.

## Installation

### 1. The plugin (Agent Skill)

**Claude Code (terminal):**

```bash
# Add the marketplace
claude plugin marketplace add hodgesmr/agent-fecfile

# Install the plugin
claude plugin install fecfile@agent-fecfile
```

You may need to restart your Claude Code session to properly load the Agent Skill.

**Updating:**

```bash
claude plugin marketplace update agent-fecfile
claude plugin update fecfile@agent-fecfile
```

**Claude desktop app / Cowork (Customize menu, no terminal):**

In the Claude desktop app you add the marketplace and install the plugin through the **Customize** menu instead of the CLI. Anthropic's [Use plugins in Claude](https://support.claude.com/en/articles/13837440-use-plugins-in-claude) help article is the full walkthrough; the short version:

1. Open **Customize** in the left sidebar, then the **Plugins** tab.
2. Under **Personal plugins**, click **+** → **Add marketplace** → **Add from a repository**.
3. Paste this repo's Git URL — `https://github.com/hodgesmr/agent-fecfile` — and add it.
4. Click **Browse plugins**, find **fecfile**, and click **Install**.

The `fecfile` skill is then available in chat and Cowork tasks — type `/` or click **+** to use it.

### 2. The MCP server

**Claude desktop app (MCPB — recommended for desktop/Cowork):**

1. Download the latest `fecfile-mcp-*.mcpb` from the [releases page](https://github.com/hodgesmr/agent-fecfile/releases)
2. Open the `.mcpb` file (double-click), or drag it into **Settings → Extensions**
3. Optionally enter your FEC API key when prompted (get one free at [api.open.fec.gov/developers](https://api.open.fec.gov/developers)) — it's stored in your system keychain and needed only for committee/filing search; analyzing a filing you already have the ID for works without it

Installed this way, the server is its own extension you can enable or disable independently of the plugin, and its network calls to the FEC run from the app — not from the agent's sandbox.

Requires [uv](https://docs.astral.sh/uv/) (the bundle's `uv` runtime launches the server; dependencies install automatically).

**Claude Code (terminal):**

The `.mcpb` format is desktop-only — Claude Code can't install it, and desktop-installed extensions aren't visible to the CLI. Register the server directly instead:

```bash
claude mcp add fec-api --env FEC_API_KEY=YOUR_KEY -- uvx --from git+https://github.com/hodgesmr/agent-fecfile fecfile-mcp
```

Omit `--env FEC_API_KEY=...` if you only analyze filings by ID and don't need committee search. Requires [uv](https://docs.astral.sh/uv/).

**Other MCP-compatible runtimes:**

The server is a stdio MCP server configured by environment variable:

```bash
export FEC_API_KEY="your-api-key-here"   # optional
uv run mcp-server/server.py               # from a clone, or: uvx --from git+https://github.com/hodgesmr/agent-fecfile fecfile-mcp
```

### Upgrading from 2.x or 1.x

v3.0.0 is a breaking change: the plugin no longer bundles an MCP server or the `fetch_filing.py` script — **all** FEC access now comes from the separately installed `fecfile-mcp` server. After upgrading the plugin, install the server per [The MCP server](#2-the-mcp-server) above. Until you do, the skill will detect the missing tools and show these same instructions instead of analyzing anything. The old keychain item from 1.x's `keyring` setup is no longer read and can be deleted.

## Usage

Once installed, ask your agent to analyze FEC filings.

> [!TIP]
> For best results, use the most capable models available in your agent runtime (e.g., Claude Opus 4.5 or comparable frontier models). More capable models produce better analysis and more accurate field interpretations.

### Basic Usage (With A Filing ID)

If you already have an FEC filing ID, you can work with it directly, without needing an API key:

```text
❯ What are the largest expenditures in filing 1896830?
```

```text
⏺ FEC Filing 1896830 - Largest Expenditures

  | #   | Recipient                  |    Amount | Date       | Purpose          |
  |-----|----------------------------|-----------|------------|------------------|
  | 1   | Trump National Doral Hotel | $1,013.61 | 2025-05-19 | RNC training     |
  | 2   | Uber.com                   |    $19.77 | 2025-05-06 | Travel - Cabfare |
  |     | TOTAL (itemized)           | $1,033.38 |            |                  |

  Note

  Only 2 expenditures are itemized on Schedule B. The filing shows $21,283.49 in total
  disbursements, meaning most spending (~$20,250) was below the $200 itemization
  threshold and appears only in summary totals.

  The largest single itemized expense was for RNC training at Trump National Doral Hotel
  in May 2025.
```

```text
❯ Show me a table of the contribution counts and totals, by state, in fec filing 1896830
```

```text
⏺ FEC Filing 1896830 - Contributions by State

  | State | Count |      Total | % of Total |
  |-------|-------|------------|------------|
  | UT    |    32 | $35,042.25 |      87.0% |
  | VA    |     2 |  $2,400.00 |       6.0% |
  | GA    |     1 |    $750.00 |       1.9% |
  | MI    |     1 |    $750.00 |       1.9% |
  | MD    |     2 |    $750.00 |       1.9% |
  | FL    |     1 |    $600.00 |       1.5% |
  | TOTAL |    39 | $40,292.25 |       100% |

  Utah dominates with 87% of the total contributions. The committee received from
  6 states total, with only 7 out-of-state contributions.
```

### Searching For Committees and Filings

With an API key configured, queries become more powerful. You can search for committees and filings without knowing the filing ID in advance.

```text
❯ What are the top expenditures in Utah Republican Party's most recent filing?
```

```text
⏺ Top Expenditures - Utah Republican Party (December 2025)

  Filing 1942957 | Coverage: Dec 1-31, 2025 | Total Disbursements: $20,500.65
  ┌─────────────────────────┬───────────┬────────────────────────┬────────┐
  │          Payee          │  Amount   │        Purpose         │  Date  │
  ├─────────────────────────┼───────────┼────────────────────────┼────────┤
  │ USPS                    │ $4,699.58 │ Direct Mail            │ Dec 23 │
  ├─────────────────────────┼───────────┼────────────────────────┼────────┤
  │ CPMI Solutions          │ $4,396.30 │ Direct Mailing         │ Dec 22 │
  ├─────────────────────────┼───────────┼────────────────────────┼────────┤
  │ NationBuilder           │ $2,925.00 │ Office Subscriptions   │ Dec 1  │
  ├─────────────────────────┼───────────┼────────────────────────┼────────┤
  │ NationBuilder           │ $2,646.00 │ Office Subscriptions   │ Dec 29 │
  ├─────────────────────────┼───────────┼────────────────────────┼────────┤
  │ Chartwells              │ $1,907.24 │ Event Registration Fee │ Dec 17 │
  ├─────────────────────────┼───────────┼────────────────────────┼────────┤
  │ Buckeye Premium Finance │ $1,071.48 │ Rent                   │ Dec 26 │
  ├─────────────────────────┼───────────┼────────────────────────┼────────┤
  │ Extra Space Storage     │ $487.00   │ Storage                │ Dec 2  │
  ├─────────────────────────┼───────────┼────────────────────────┼────────┤
  │ Extra Space Storage     │ $487.00   │ Storage                │ Dec 30 │
  ├─────────────────────────┼───────────┼────────────────────────┼────────┤
  │ Ring Central            │ $170.31   │ Telephone              │ Dec 11 │
  ├─────────────────────────┼───────────┼────────────────────────┼────────┤
  │ Intuit                  │ $123.57   │ Office Subscriptions   │ Dec 24 │
  └─────────────────────────┴───────────┴────────────────────────┴────────┘
  The bulk of December spending was on direct mail operations (~$9,100 combined
  to USPS and CPMI Solutions) and NationBuilder software subscriptions (~$5,600).
```

### FEC API Setup

Committee and filing search (`search_committees`, `get_filings`) uses the authenticated FEC API and needs a key. Filing analysis by ID does not.

1. Visit https://api.open.fec.gov/developers/
2. Go to "Sign up for an API key" and fill out the form
3. You'll receive your API key via email
4. Enter it where your runtime expects it: the extension's settings in the Claude desktop app (stored in your system keychain), or the `FEC_API_KEY` environment variable for manual configurations

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

The MCP server:

- Handles every FEC network request (`api.open.fec.gov` for search, `docquery.fec.gov` for filings) — the agent never talks to FEC hosts
- Loads the FEC API key from the `FEC_API_KEY` environment variable **on first tool use**, holds it in memory, and never exposes it to the model
- Provides `search_committees`, `get_filings`, `fetch_filing`, `analyze_filing`, and `get_version`

## Security Notes

- **Network access**: All FEC requests (`docquery.fec.gov`, `api.open.fec.gov`) run inside the MCP server process. In the Claude desktop app that's the app itself — the agent's sandbox needs no network access to FEC hosts, and no FEC credentials ever enter it.

- **Untrusted content**: FEC filings should be considered [untrusted content](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/). A malicious campaign sneaking prompt injections into the memo text field of their F99 is probably unlikely, but not impossible.

- **API key handling**: In the desktop app, the key is collected at install time and stored in your operating system's keychain/credential manager; the server receives it as an environment variable and sanitizes error output so it can't leak into the transcript. The model never sees the key.

## Acknowledgments

- Built on the excellent [fecfile](https://github.com/esonderegger/fecfile) library by Evan Sonderegger
- Inspired by Derek Willis's [llm-fecfile](https://github.com/dwillis/llm-fecfile) LLM plugin
- Uses data from the Federal Election Commission

## License

[MIT License](./LICENSE)
