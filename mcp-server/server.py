#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "mcp>=1.27.0,<2",
#     "httpx>=0.28.0",
#     "fecfile>=0.9.1",
# ]
# ///
"""
FEC API MCP Server

An MCP server that provides all FEC network access for the fecfile skill:
committee/filing search against the authenticated FEC API, and filing
retrieval/analysis from the public filing archive. Because every FEC request
runs inside this server process, the calling agent needs neither the API key
nor network access to FEC hosts.

The API key is loaded from the FEC_API_KEY environment variable on first tool
use and cached, preventing the LLM from ever seeing or accessing the
credential. Filing retrieval (fetch_filing, analyze_filing) uses the public
archive and needs no key.

Tools:
    - search_committees: Search for FEC committees by name (requires API key)
    - get_filings: List filings for a committee (requires API key)
    - fetch_filing: Fetch a filing's summary or a page of schedule items
    - analyze_filing: Stream a whole filing server-side for top-N / group totals
    - get_version: Report the running server version

The server uses stdio transport for communication with MCP clients.
"""

import asyncio
import heapq
import json
import os
import re
from collections import defaultdict
from typing import Optional

import fecfile
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Constants
FEC_API_BASE = "https://api.open.fec.gov/v1"
SERVER_VERSION = "3.0.0"

# Schedule letter -> fecfile itemization filter code, and each schedule's
# dollar-amount field (names per skills/fecfile/references/SCHEDULES.md).
SCHEDULE_CODES = {"A": "SA", "B": "SB", "C": "SC", "D": "SD", "E": "SE"}
AMOUNT_FIELDS = {
    "A": "contribution_amount",
    "B": "expenditure_amount",
    "C": "loan_amount",
    "D": "debt_amount",
    "E": "expenditure_amount",
}

MAX_PAGE_ITEMS = 500
MAX_TOP_N = 100
MAX_GROUPS = 200


def sanitize_api_key(text: str) -> str:
    """Remove API key from text to prevent accidental exposure."""
    return re.sub(r"api_key=[^&\s]+", "api_key=REDACTED", text)


def _norm_schedule(value) -> Optional[str]:
    """Normalize 'a' / 'SA' / 'Schedule A' to the single letter, or None."""
    v = str(value or "").strip().upper()
    if v.startswith("SCHEDULE"):
        v = v.split()[-1]
    if len(v) == 2 and v.startswith("S"):
        v = v[1]
    return v if v in SCHEDULE_CODES else None


def _amount(item: dict, field: str) -> float:
    try:
        return float(item.get(field) or 0)
    except (TypeError, ValueError):
        return 0.0


def _iter_items(filing_id: int, schedule: str):
    """Yield itemization dicts for one schedule, streaming the filing."""
    options = {"filter_itemizations": [SCHEDULE_CODES[schedule]]}
    for row in fecfile.iter_http(filing_id, options=options):
        if row.data_type == "itemization":
            yield row.data


def _fetch_summary(filing_id: int) -> dict:
    """Fetch just the filing header + summary, stopping the stream early."""
    out = {}
    for row in fecfile.iter_http(filing_id, options={"filter_itemizations": []}):
        if row.data_type in ("header", "summary"):
            out[row.data_type] = row.data
        if "summary" in out:
            break
    return out


def _fetch_page(filing_id: int, schedule: str, offset: int, limit: int,
                min_amount: Optional[float]) -> dict:
    # ponytail: stateless — each page re-streams the filing from the start.
    # Fine for the first pages; deep paging on huge filings should use
    # min_amount or analyze_filing instead (the tool description says so).
    field = AMOUNT_FIELDS[schedule]
    items, skipped, has_more = [], 0, False
    for item in _iter_items(filing_id, schedule):
        if min_amount is not None and _amount(item, field) < min_amount:
            continue
        if skipped < offset:
            skipped += 1
            continue
        if len(items) < limit:
            items.append(item)
        else:
            has_more = True
            break
    return {
        "filing_id": filing_id,
        "schedule": schedule,
        "offset": offset,
        "returned": len(items),
        "has_more": has_more,
        "items": items,
    }


def _analyze(filing_id: int, schedule: str, operation: str, n: int,
             group_by: Optional[str]) -> dict:
    """Full streaming pass over one schedule; constant memory."""
    field = AMOUNT_FIELDS[schedule]
    if operation == "top_items":
        top = heapq.nlargest(
            n, _iter_items(filing_id, schedule), key=lambda i: _amount(i, field)
        )
        return {
            "filing_id": filing_id,
            "schedule": schedule,
            "operation": "top_items",
            "amount_field": field,
            "items": top,
        }
    # totals_by_field
    totals: dict = defaultdict(float)
    counts: dict = defaultdict(int)
    for item in _iter_items(filing_id, schedule):
        key = str(item.get(group_by) or "Unknown")
        totals[key] += _amount(item, field)
        counts[key] += 1
    groups = sorted(totals, key=lambda k: -totals[k])
    return {
        "filing_id": filing_id,
        "schedule": schedule,
        "operation": "totals_by_field",
        "group_by": group_by,
        "amount_field": field,
        "groups": {
            g: {"count": counts[g], "total": round(totals[g], 2)}
            for g in groups[:MAX_GROUPS]
        },
        "truncated": len(groups) > MAX_GROUPS,
    }


class FECAPIServer:
    """MCP server for FEC API access with secure credential handling."""

    def __init__(self):
        self.server = Server("fec-api")
        self._api_key: Optional[str] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self._setup_handlers()

    @property
    def api_key(self) -> Optional[str]:
        """Lazily load and cache the API key on first access."""
        if self._api_key is None:
            self._api_key = self._load_api_key()
        return self._api_key

    def _load_api_key(self) -> Optional[str]:
        """
        Load the FEC API key from the FEC_API_KEY environment variable.

        Returns None if the key is unset or empty (an MCPB host may inject an
        empty string when the optional field is left blank), allowing the
        server to start and serve the keyless filing tools.
        """
        return os.getenv("FEC_API_KEY") or None

    def _setup_handlers(self):
        """Configure MCP server handlers."""

        @self.server.list_tools()
        async def list_tools():
            return [
                Tool(
                    name="get_version",
                    description=(
                        "Returns the running MCP server version. Use this to confirm "
                        "which version of the fecfile-mcp server is active."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                ),
                Tool(
                    name="search_committees",
                    description=(
                        "Search for FEC committees by name. Returns committee IDs "
                        "that can be used with get_filings. Requires FEC API key "
                        "to be configured. For detailed filing analysis, invoke the "
                        "fecfile skill which provides the proper workflow."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Committee name or partial name to search for",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results (default: 20)",
                                "default": 20,
                            },
                        },
                        "required": ["query"],
                    },
                ),
                Tool(
                    name="get_filings",
                    description=(
                        "Get FEC filings for a committee. Returns filing IDs, dates, "
                        "and financial summaries. Use search_committees first to find "
                        "the committee ID. Requires FEC API key to be configured. "
                        "For detailed filing analysis, invoke the fecfile skill which "
                        "provides the proper workflow."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "committee_id": {
                                "type": "string",
                                "description": "FEC committee ID (e.g., C00089482)",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results (default: 10)",
                                "default": 10,
                            },
                            "form_type": {
                                "type": "string",
                                "description": "Filter by form type (F3, F3P, F3X)",
                            },
                            "cycle": {
                                "type": "integer",
                                "description": "Filter by two-year election cycle (e.g., 2024)",
                            },
                            "report_type": {
                                "type": "string",
                                "description": "Filter by report type (Q1, Q2, Q3, YE, MY, 12G, 30G)",
                            },
                            "sort": {
                                "type": "string",
                                "description": "Sort field with optional '-' prefix for descending (default: -receipt_date)",
                                "default": "-receipt_date",
                            },
                            "include_amended": {
                                "type": "boolean",
                                "description": "Include superseded amendments (default: false)",
                                "default": False,
                            },
                        },
                        "required": ["committee_id"],
                    },
                ),
                Tool(
                    name="fetch_filing",
                    description=(
                        "Fetch data from one FEC filing (public archive, no API key "
                        "needed). Call with summary_only=true first to see the "
                        "filing's financial totals and gauge its size, then pull "
                        "schedule itemizations in pages. min_amount filters items "
                        "before offset/limit apply. Each page re-streams the filing "
                        "from the start, so prefer min_amount or analyze_filing over "
                        "paging deep into a large filing."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "filing_id": {
                                "type": "integer",
                                "description": "FEC filing ID (positive integer)",
                            },
                            "summary_only": {
                                "type": "boolean",
                                "description": "Return only the filing header and summary (no itemizations)",
                                "default": False,
                            },
                            "schedule": {
                                "type": "string",
                                "description": (
                                    "Schedule letter to fetch: A (contributions), B "
                                    "(disbursements), C (loans), D (debts), E (independent "
                                    "expenditures). Required unless summary_only."
                                ),
                            },
                            "offset": {
                                "type": "integer",
                                "description": "Number of (post-filter) items to skip (default: 0)",
                                "default": 0,
                            },
                            "limit": {
                                "type": "integer",
                                "description": f"Maximum items to return (default: 100, max: {MAX_PAGE_ITEMS})",
                                "default": 100,
                            },
                            "min_amount": {
                                "type": "number",
                                "description": "Only include items with an amount at or above this value",
                            },
                        },
                        "required": ["filing_id"],
                    },
                ),
                Tool(
                    name="analyze_filing",
                    description=(
                        "Analyze one schedule of an FEC filing server-side without "
                        "returning every item (public archive, no API key needed). "
                        "operation=top_items returns the N largest items by dollar "
                        "amount; operation=totals_by_field returns count and total "
                        "grouped by a field (e.g. contributor_state). Streams the "
                        "entire schedule in constant memory — the right tool for "
                        "large filings; may take a while on very large ones."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "filing_id": {
                                "type": "integer",
                                "description": "FEC filing ID (positive integer)",
                            },
                            "schedule": {
                                "type": "string",
                                "description": "Schedule letter to analyze: A, B, C, D, or E",
                            },
                            "operation": {
                                "type": "string",
                                "enum": ["top_items", "totals_by_field"],
                                "description": (
                                    "top_items: N largest items by amount. "
                                    "totals_by_field: count/total per value of group_by."
                                ),
                            },
                            "n": {
                                "type": "integer",
                                "description": f"How many top items to return (default: 10, max: {MAX_TOP_N})",
                                "default": 10,
                            },
                            "group_by": {
                                "type": "string",
                                "description": (
                                    "Field to group by for totals_by_field (e.g. "
                                    "contributor_state, payee_organization_name). Field "
                                    "names are documented in the fecfile skill's "
                                    "SCHEDULES.md reference."
                                ),
                            },
                        },
                        "required": ["filing_id", "schedule", "operation"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict):
            if name == "get_version":
                return [TextContent(type="text", text=SERVER_VERSION)]
            elif name == "search_committees":
                return await self._search_committees(arguments)
            elif name == "get_filings":
                return await self._get_filings(arguments)
            elif name == "fetch_filing":
                return await self._fetch_filing(arguments)
            elif name == "analyze_filing":
                return await self._analyze_filing(arguments)
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

    @staticmethod
    def _filing_error(e: Exception):
        return [
            TextContent(
                type="text",
                text=(
                    f"Error fetching filing ({type(e).__name__}): "
                    f"{sanitize_api_key(str(e))}"
                ),
            )
        ]

    async def _fetch_filing(self, arguments: dict):
        """Fetch a filing summary or a page of schedule itemizations."""
        try:
            filing_id = int(arguments.get("filing_id", 0))
            offset = max(int(arguments.get("offset", 0)), 0)
            limit = min(max(int(arguments.get("limit", 100)), 1), MAX_PAGE_ITEMS)
            min_amount = arguments.get("min_amount")
            min_amount = float(min_amount) if min_amount is not None else None
        except (TypeError, ValueError):
            return [
                TextContent(
                    type="text",
                    text="filing_id, offset, and limit must be integers; min_amount must be a number.",
                )
            ]
        if filing_id <= 0:
            return [TextContent(type="text", text="filing_id must be a positive integer.")]

        if arguments.get("summary_only", False):
            try:
                # fecfile is synchronous; run it off the event loop.
                summary = await asyncio.to_thread(_fetch_summary, filing_id)
            except Exception as e:
                return self._filing_error(e)
            return [TextContent(type="text", text=json.dumps(summary, indent=2, default=str))]

        schedule = _norm_schedule(arguments.get("schedule"))
        if schedule is None:
            return [
                TextContent(
                    type="text",
                    text=(
                        "Provide either summary_only=true or a schedule letter "
                        "(A, B, C, D, or E). Fetching a whole filing at once is "
                        "not supported — check the summary first, then pull the "
                        "schedule you need."
                    ),
                )
            ]

        try:
            page = await asyncio.to_thread(
                _fetch_page, filing_id, schedule, offset, limit, min_amount
            )
        except Exception as e:
            return self._filing_error(e)
        return [TextContent(type="text", text=json.dumps(page, indent=2, default=str))]

    async def _analyze_filing(self, arguments: dict):
        """Server-side top-N / group-totals over one schedule of a filing."""
        try:
            filing_id = int(arguments.get("filing_id", 0))
            n = min(max(int(arguments.get("n", 10)), 1), MAX_TOP_N)
        except (TypeError, ValueError):
            return [TextContent(type="text", text="filing_id and n must be integers.")]
        if filing_id <= 0:
            return [TextContent(type="text", text="filing_id must be a positive integer.")]

        schedule = _norm_schedule(arguments.get("schedule"))
        if schedule is None:
            return [TextContent(type="text", text="schedule must be A, B, C, D, or E.")]

        operation = arguments.get("operation", "")
        if operation not in ("top_items", "totals_by_field"):
            return [
                TextContent(
                    type="text",
                    text="operation must be top_items or totals_by_field.",
                )
            ]
        group_by = arguments.get("group_by")
        if operation == "totals_by_field" and not group_by:
            return [
                TextContent(
                    type="text",
                    text=(
                        "totals_by_field requires group_by (a field name, e.g. "
                        "contributor_state)."
                    ),
                )
            ]

        try:
            result = await asyncio.to_thread(
                _analyze, filing_id, schedule, operation, n, group_by
            )
        except Exception as e:
            return self._filing_error(e)
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    async def _search_committees(self, arguments: dict):
        """Search for committees by name."""
        if not self.api_key:
            return [
                TextContent(
                    type="text",
                    text=(
                        "FEC API key not configured. Please set your FEC_API_KEY "
                        "in the server configuration. Get a free API key at "
                        "https://api.open.fec.gov/developers"
                    ),
                )
            ]

        query = arguments.get("query", "")
        limit = arguments.get("limit", 20)

        try:
            params = {
                "api_key": self.api_key,
                "q": query,
            }

            response = await self.http_client.get(
                f"{FEC_API_BASE}/names/committees/",
                params=params,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            results = data.get("results", [])[:limit]

            if not results:
                return [
                    TextContent(
                        type="text",
                        text=f"No committees found matching '{query}'",
                    )
                ]

            return [
                TextContent(
                    type="text",
                    text=json.dumps(results, indent=2),
                )
            ]

        except httpx.HTTPStatusError as e:
            body_snippet = e.response.text[:300].strip() if e.response else ""
            return [
                TextContent(
                    type="text",
                    text=(
                        f"HTTP {e.response.status_code} error from FEC API: "
                        f"{sanitize_api_key(str(e))}"
                        + (f"\nResponse body: {body_snippet}" if body_snippet else "")
                    ),
                )
            ]
        except httpx.HTTPError as e:
            cause = repr(e.__cause__) if e.__cause__ else ""
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Connection error ({type(e).__name__}): {sanitize_api_key(str(e))}"
                        + (f"\nCaused by: {cause}" if cause else "")
                    ),
                )
            ]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"Unexpected error ({type(e).__name__}): {sanitize_api_key(str(e))}",
                )
            ]

    async def _get_filings(self, arguments: dict):
        """Get filings for a committee."""
        if not self.api_key:
            return [
                TextContent(
                    type="text",
                    text=(
                        "FEC API key not configured. Please set your FEC_API_KEY "
                        "in the server configuration. Get a free API key at "
                        "https://api.open.fec.gov/developers"
                    ),
                )
            ]

        committee_id = arguments.get("committee_id", "")
        limit = arguments.get("limit", 10)
        form_type = arguments.get("form_type")
        cycle = arguments.get("cycle")
        report_type = arguments.get("report_type")
        sort = arguments.get("sort", "-receipt_date")
        include_amended = arguments.get("include_amended", False)

        try:
            params = {
                "api_key": self.api_key,
                "per_page": min(limit, 100),
                "sort": sort,
                "most_recent": not include_amended,
            }

            if form_type:
                params["form_type"] = form_type
            if cycle:
                params["cycle"] = cycle
            if report_type:
                params["report_type"] = report_type

            response = await self.http_client.get(
                f"{FEC_API_BASE}/committee/{committee_id}/filings/",
                params=params,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            results = data.get("results", [])

            if not results:
                return [
                    TextContent(
                        type="text",
                        text=f"No filings found for committee '{committee_id}'",
                    )
                ]

            # Extract key fields for each filing
            output = []
            for r in results:
                output.append(
                    {
                        "filing_id": r.get("file_number"),
                        "form_type": r.get("form_type"),
                        "receipt_date": r.get("receipt_date"),
                        "coverage_start_date": r.get("coverage_start_date"),
                        "coverage_end_date": r.get("coverage_end_date"),
                        "total_receipts": r.get("total_receipts"),
                        "total_disbursements": r.get("total_disbursements"),
                        "amendment_indicator": r.get("amendment_indicator"),
                    }
                )

            return [
                TextContent(
                    type="text",
                    text=json.dumps(output, indent=2),
                )
            ]

        except httpx.HTTPStatusError as e:
            body_snippet = e.response.text[:300].strip() if e.response else ""
            return [
                TextContent(
                    type="text",
                    text=(
                        f"HTTP {e.response.status_code} error from FEC API: "
                        f"{sanitize_api_key(str(e))}"
                        + (f"\nResponse body: {body_snippet}" if body_snippet else "")
                    ),
                )
            ]
        except httpx.HTTPError as e:
            cause = repr(e.__cause__) if e.__cause__ else ""
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Connection error ({type(e).__name__}): {sanitize_api_key(str(e))}"
                        + (f"\nCaused by: {cause}" if cause else "")
                    ),
                )
            ]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"Unexpected error ({type(e).__name__}): {sanitize_api_key(str(e))}",
                )
            ]

    async def run(self):
        """Start the MCP server."""
        async with httpx.AsyncClient() as self.http_client:
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    self.server.create_initialization_options(),
                )


async def main():
    server = FECAPIServer()
    await server.run()


def cli():
    """Console entry point (see [project.scripts] in pyproject.toml)."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
