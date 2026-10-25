"""ALT/FNDATA MCP Server — connects Claude to luxury asset auction data.

Wraps the ALT/FNDATA REST API as MCP tools so Claude can query luxury
asset auction data (watches, jewelry, loose gemstones, handbags, cars,
wine, art, and more) in conversation.

Supports two transport modes:
    - stdio  (default)  — for local Claude Desktop / Claude Code usage
    - streamable-http   — for Anthropic Connectors Directory (Remote MCP)

Environment variables:
    ALTFINANCE_API_URL       — base URL of the AltFinance API
    ALTFINANCE_API_KEY       — your API key (stdio mode only)
    ALTFINANCE_TRANSPORT     — "stdio" (default) or "streamable-http"
    ALTFINANCE_HOST          — HTTP listen host (default: 0.0.0.0)
    ALTFINANCE_PORT          — HTTP listen port (default: 8000)
    ALTFINANCE_ISSUER_URL    — OAuth issuer URL (default: http://localhost:8000)
    ALTFINANCE_RESOURCE_URL  — OAuth resource server URL (default: same as issuer)
    ALTFINANCE_OAUTH_TABLE   — DynamoDB table for OAuth state (HTTP mode; unset = in memory)
    ALTFINANCE_OAUTH_KMS_KEY — KMS key id/alias encrypting stored API keys and client secrets
"""

import asyncio
import os
import sys
import time
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

# ── Configuration ────────────────────────────────────────────────

API_URL = os.environ.get("ALTFINANCE_API_URL", "https://api.altfndata.com")
API_KEY = os.environ.get("ALTFINANCE_API_KEY", "")
TRANSPORT = os.environ.get("ALTFINANCE_TRANSPORT", "stdio")
HOST = os.environ.get("ALTFINANCE_HOST", "0.0.0.0")
PORT = int(os.environ.get("ALTFINANCE_PORT", "8000"))
ISSUER_URL = os.environ.get("ALTFINANCE_ISSUER_URL", f"http://localhost:{PORT}")
RESOURCE_URL = os.environ.get("ALTFINANCE_RESOURCE_URL", ISSUER_URL)

MCP_ROOT_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ALT/FNDATA MCP Server</title>
  <link rel="icon" href="/favicon.ico" type="image/png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;800;900&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #f7f8fc; color: #111827; -webkit-font-smoothing: antialiased; }
    .nav { display: flex; align-items: center; justify-content: space-between; max-width: 960px; margin: 0 auto; padding: 20px 40px; }
    .nav img { height: 32px; }
    .nav-links { display: flex; gap: 24px; align-items: center; }
    .nav-links a { font-family: Inter, sans-serif; font-size: 13px; font-weight: 600; color: #4a5568; text-decoration: none; }
    .nav-links a:hover { color: #111827; }
    .nav-btn { background: #111827; color: #fff !important; padding: 8px 18px; border-radius: 8px; }
    .nav-btn:hover { background: #1f2937; }
    .hero { background: #f7f8fc; padding: 60px 40px 72px; text-align: center; position: relative; overflow: hidden; }
    .hero-glow { position: absolute; top: -200px; left: 50%; transform: translateX(-50%); width: 700px; height: 400px; background: radial-gradient(ellipse, rgba(59,107,245,0.08) 0%, transparent 70%); pointer-events: none; }
    .badge { display: inline-flex; align-items: center; gap: 8px; border: 1px solid rgba(59,107,245,0.2); border-radius: 20px; padding: 5px 14px; font-size: 11.5px; font-weight: 600; color: #4a5568; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 28px; font-family: Manrope, sans-serif; }
    .badge-dot { width: 6px; height: 6px; background: #D97757; border-radius: 50%; display: inline-block; }
    .hero h1 { font-family: Manrope, sans-serif; font-size: clamp(36px, 4vw, 50px); font-weight: 900; line-height: 1.12; letter-spacing: -1.5px; color: #111827; margin-bottom: 24px; max-width: 960px; margin-left: auto; margin-right: auto; }
    .hero h1 img { height: 1em; vertical-align: baseline; display: inline-block; position: relative; top: 0.05em; }
    .hero p { font-size: 16px; color: #4a5568; max-width: 520px; margin: 0 auto 36px; line-height: 1.75; font-family: Inter, sans-serif; }
    .hero-actions { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; margin-bottom: 0; }
    .hero-actions a { font-family: Inter, sans-serif; font-size: 14px; font-weight: 600; text-decoration: none; padding: 12px 28px; border-radius: 10px; transition: all 0.2s; }
    .btn-primary { background: #111827; color: #fff; }
    .btn-primary:hover { background: #1f2937; transform: translateY(-1px); }
    .btn-outline { background: #fff; color: #111827; border: 1px solid #d1d5db; }
    .btn-outline:hover { border-color: #9ca3af; transform: translateY(-1px); }
    .cards { background: #f0f2f8; padding: 48px 40px 64px; font-family: Inter, sans-serif; }
    .cards-inner { max-width: 960px; margin: 0 auto; }
    .cards-label { font-size: 11px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: #9ca3af; margin: 0 0 28px; text-align: center; }
    .card-grid { display: flex; gap: 20px; }
    .card { flex: 1; background: #fff; border: 1px solid rgba(59,107,245,0.12); border-radius: 12px; padding: 32px; text-decoration: none; display: block; box-shadow: 0 1px 3px rgba(0,0,0,0.04); transition: border-color 0.2s, transform 0.2s, box-shadow 0.2s; }
    .card:hover { border-color: rgba(59,107,245,0.3); transform: translateY(-2px); box-shadow: 0 4px 12px rgba(59,107,245,0.08); }
    .card-tag { display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; padding: 3px 10px; border-radius: 20px; margin-bottom: 16px; }
    .card-tag-blue { color: #3B6BF5; background: rgba(59,107,245,0.08); }
    .card-tag-orange { color: #D97757; background: rgba(217,119,87,0.08); }
    .card h3 { font-family: Manrope, sans-serif; font-size: 20px; font-weight: 800; color: #111827; margin: 0 0 10px; line-height: 1.3; }
    .card p { font-size: 14px; color: #6b7280; line-height: 1.65; margin: 0 0 20px; }
    .card-link-blue { font-size: 13px; font-weight: 600; color: #3B6BF5; }
    .card-link-orange { font-size: 13px; font-weight: 600; color: #D97757; }
    .footer { text-align: center; padding: 32px 40px; background: #f0f2f8; border-top: 1px solid #e2e5ed; font-family: Inter, sans-serif; font-size: 12px; color: #9ca3af; }
    .footer a { color: #6b7280; text-decoration: none; }
    .footer a:hover { color: #111827; }
    @media (max-width: 680px) { .card-grid { flex-direction: column; } .nav-links { gap: 12px; } }
  </style>
</head>
<body>
  <nav class="nav">
    <a href="https://altfndata.com">
      <img src="https://app.altfndata.com/images/AltFndata_Logo_Transparent.png" alt="ALT/FNDATA" style="height:28px;display:block">
    </a>
    <div class="nav-links">
      <a href="https://altfndata.com/market-news/">Market News</a>
      <a href="https://altfndata.com">Products</a>
      <a href="https://api.altfndata.com/portal/" class="nav-btn">Get API Key</a>
    </div>
  </nav>

  <div class="hero">
    <div class="hero-glow"></div>
    <div class="badge">
      <span class="badge-dot"></span>
      Now live in Anthropic\u2019s Claude \u00b7 MCP Connector
    </div>
    <h1>
      Alternative Asset &amp; Luxury Market<br>
      Intelligence \u2014 Now in
      <img src="https://altfinancedbcontent.s3.us-east-1.amazonaws.com/logos/Claude_Logo_2023-s1280.png" alt="Claude">
    </h1>
    <p>ALT/FNDATA powers your workflow with verified transaction data across luxury watches, fine art, classic cars, jewelry, wine, and more. Now available as an MCP connector inside Anthropic\u2019s Claude.</p>
    <div class="hero-actions">
      <a href="https://api.altfndata.com/portal/" class="btn-primary">Get API Key</a>
      <a href="https://altfndata.com" class="btn-outline">Learn More</a>
    </div>
  </div>

  <div class="cards">
    <div class="cards-inner">
      <p class="cards-label">Resources for Claude Users</p>
      <div class="card-grid">
        <a href="https://altfndata.com/resources/claude-financial-integrations" class="card">
          <span class="card-tag card-tag-blue">MCP Integrations</span>
          <h3>Claude Financial Data Integrations</h3>
          <p>Compare 10 market data providers available as MCP connectors \u2014 features, coverage, and pricing at a glance.</p>
          <span class="card-link-blue">View comparison \u2192</span>
        </a>
        <a href="https://altfndata.com/resources/claude-financial-use-cases" class="card">
          <span class="card-tag card-tag-orange">Use Cases</span>
          <h3>Claude Financial Use Cases</h3>
          <p>34 real-world workflows across portfolio management, valuation, risk, competitive intelligence, and more.</p>
          <span class="card-link-orange">Explore use cases \u2192</span>
        </a>
      </div>
    </div>
  </div>

  <footer class="footer">
    <p>\u00a9 2026 ALT/FNDATA Inc. &nbsp;\u00b7&nbsp; <a href="https://altfndata.com">altfndata.com</a> &nbsp;\u00b7&nbsp; <a href="/.well-known/oauth-authorization-server">OAuth metadata</a> &nbsp;\u00b7&nbsp; MCP endpoint: <code>/mcp</code></p>
  </footer>
</body>
</html>
"""


# ── Landing page: serve the S3-hosted landing (altfndata.com/mcp/landing.html)
# so it can be edited without redeploying the container. Cached in-process for a
# few minutes; falls back to the last good copy, then the baked-in MCP_ROOT_HTML,
# if the fetch fails. ──
_LANDING_URL = "https://altfndata.com/mcp/landing.html"
_LANDING_TTL = 300.0  # seconds
_landing_cache: dict = {"html": None, "ts": 0.0}


async def _get_landing_html() -> str:
    import time

    now = time.time()
    cached = _landing_cache.get("html")
    if cached and (now - _landing_cache.get("ts", 0.0)) < _LANDING_TTL:
        return cached
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            resp = await client.get(_LANDING_URL)
            resp.raise_for_status()
            html = resp.text
            if html and len(html) > 500:
                _landing_cache["html"] = html
                _landing_cache["ts"] = now
                return html
    except Exception:
        pass
    return _landing_cache.get("html") or MCP_ROOT_HTML


SERVER_INSTRUCTIONS = (
    "You have access to the ALT/FNDATA luxury asset auction database, which "
    "spans many categories. ALWAYS call list_tables first to see every table "
    "available; do not assume the set. Two tables both cover gemstones and are "
    "easy to confuse: 'gems' holds LOOSE, unmounted stones (single stones and "
    "parcels, the right table for a gemstone valuation), while 'jewelry' holds "
    "FINISHED pieces (rings, necklaces, bracelets) that happen to be set with "
    "stones. For a loose-stone query (e.g. spessartite, grandidierite, sapphire), "
    "query 'gems'; for a mounted piece, query 'jewelry'. If one table returns "
    "nothing, try the other before concluding there is no data. Use "
    "get_table_schema to learn a table's columns before querying, and query_table "
    "to search and filter. For a fast whole-market keyword search across every "
    "category at once (no table guessing) use search; for a market overview "
    "(median/percentile/count of realized prices, date span, top vendors) use "
    "market_stats; for how prices moved over time use price_trend; for a single "
    "item's fair-value range and comparable sales use price_check; for precomputed "
    "model-level price indices (handbags, watches, cars) use market_index; and "
    "list_alerts surfaces the read-only status of price alerts. A loose-stone "
    "question can span both 'gems' and 'jewelry'; a named-artist question can span "
    "'works_of_art' and 'fine_art' — check both when relevant."
)

# ── OAuth provider (only instantiated in HTTP mode) ──────────────

_oauth_provider = None

if TRANSPORT == "streamable-http":
    from mcp.server.auth.settings import (
        AuthSettings,
        ClientRegistrationOptions,
        RevocationOptions,
    )

    from altfinance_mcp.oauth_provider import AltFinanceOAuthProvider
    from altfinance_mcp.oauth_store import store_from_env

    login_url = f"{ISSUER_URL}/login"
    _oauth_provider = AltFinanceOAuthProvider(
        api_url=API_URL, login_url=login_url, store=store_from_env()
    )

    auth_settings = AuthSettings(
        issuer_url=ISSUER_URL,
        resource_server_url=RESOURCE_URL,
        service_documentation_url="https://altfndata.com/docs",
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["read"],
            default_scopes=["read"],
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=["read"],
    )

    mcp = FastMCP(
        name="ALT/FNDATA",
        instructions=SERVER_INSTRUCTIONS,
        auth_server_provider=_oauth_provider,
        auth=auth_settings,
        host=HOST,
        port=PORT,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )
else:
    mcp = FastMCP(
        name="ALT/FNDATA",
        instructions=SERVER_INSTRUCTIONS,
    )


# ── HTTP client factory ──────────────────────────────────────────

def _client(api_key: str) -> httpx.AsyncClient:
    """Create an HTTP client authenticated with the given API key.

    Every outbound request carries ``X-AFN-Connector: mcp`` so the API can attribute
    the call to the in-assistant connector channel (distinct from a direct REST-API
    caller, which this server is otherwise indistinguishable from — same X-API-Key
    auth, a server-side httpx user agent, and no browser Origin). This is the
    foundation of in-assistant attribution (GROWTH_STRATEGY.md §5.1) and the header
    the taste tier later reuses for connector-only scoping (TASTE_TIER_PLAN.md §4.4).
    """
    return httpx.AsyncClient(
        base_url=API_URL,
        headers={"X-API-Key": api_key, "X-AFN-Connector": "mcp"},
        timeout=60.0,
    )


def _resolve_api_key() -> str:
    """Resolve the ALT/FNDATA API key for the current request.

    In stdio mode, uses the ALTFINANCE_API_KEY env var.
    In HTTP mode, extracts the API key from the authenticated OAuth token.
    """
    if TRANSPORT == "streamable-http" and _oauth_provider is not None:
        from mcp.server.auth.middleware.auth_context import get_access_token

        access_token = get_access_token()
        if access_token:
            api_key = _oauth_provider.get_api_key_for_token(access_token.token)
            if api_key:
                return api_key
        # Fallback (should not happen if auth middleware is working)
        return ""
    return API_KEY


# ── MCP Tools ────────────────────────────────────────────────────

@mcp.tool(annotations={"title": "List Data Tables", "readOnlyHint": True, "openWorldHint": True})
async def list_tables() -> str:
    """List every auction-data table ALT/FNDATA serves, with live descriptions
    and column counts.

    Start here whenever a question names a category and you need the right table
    alias to pass to get_table_schema, query_table, market_stats or price_trend.
    The set spans watches, jewelry (finished/mounted pieces), gems (loose
    stones), handbags, cars, motorcycles, wine & whisky, works of art, fine art,
    coins, and more. Always call this for the current set rather than assuming
    it, and note that loose gemstones live in `gems`, not `jewelry`.

    Example: for "what categories of data do you have?" or before "show me the
    most expensive coins sold at auction" (to confirm the `coins` alias exists).
    """
    api_key = _resolve_api_key()
    async with _client(api_key) as client:
        resp = await client.get("/v1/tables")
        resp.raise_for_status()
        data = resp.json()

    lines = []
    for t in data["tables"]:
        lines.append(
            f"- **{t['name']}** ({t.get('column_count', '?')} columns): {t['description']}"
        )
    return "\n".join(lines)


@mcp.tool(annotations={"title": "Get Table Schema", "readOnlyHint": True, "openWorldHint": True})
async def get_table_schema(table: str) -> str:
    """List a table's column names and types so you can build a precise query.

    Call this before query_table (or before adding `filters` to market_stats /
    price_trend) to learn the exact field names a table exposes — e.g. whether
    prices are in `usd_price_decimal`, how the brand/designer field is named, or
    whether a `carats` column exists. Avoids guessing column names.

    Example: before querying Rolex sales, call get_table_schema("watches") to
    confirm the brand field is `designer` and the price field is
    `usd_price_decimal`.

    Args:
        table: Table alias (call list_tables for the full set). Note: "gems" =
               loose/unmounted stones; "jewelry" = finished/mounted pieces.
    """
    api_key = _resolve_api_key()
    async with _client(api_key) as client:
        resp = await client.get(f"/v1/tables/{table}/schema")
        if resp.status_code == 404:
            return f"Table '{table}' not found. Use list_tables to see available tables."
        resp.raise_for_status()
        data = resp.json()

    lines = [f"Schema for **{data['table']}** ({data['athena_table']}):\n"]
    for col in data["columns"]:
        lines.append(f"- `{col['name']}` ({col['type']})")
    return "\n".join(lines)


@mcp.tool(annotations={"title": "Query a Table", "readOnlyHint": True, "openWorldHint": True})
async def query_table(
    table: str,
    fields: Optional[list[str]] = None,
    filters: Optional[list[dict]] = None,
    sort_field: Optional[str] = None,
    sort_direction: Optional[str] = "desc",
    limit: int = 20,
    offset: int = 0,
) -> str:
    """Query one known table with precise filtering, sorting, and field selection.

    Use this when you already know the target table (from list_tables) and want
    exact control — e.g. "the 10 most expensive Rolex watches sold since 2020"
    becomes table="watches", filters on `designer`/`sale_date`, sort by
    `usd_price_decimal` desc, limit 10. If you don't know which table holds the
    item, use `search` (whole-market) instead; for aggregate figures (median,
    percentiles) use `market_stats`.

    Args:
        table: Table alias (call list_tables for the full set). "gems" = loose
               stones (use for gemstone valuations); "jewelry" = finished pieces.
        fields: List of column names to return (e.g., ["item_title", "vendor", "usd_price_decimal"]).
                If not specified, returns all columns.
        filters: List of filter conditions. Each filter is a dict with:
                 - "field": column name
                 - "op": operator — one of "eq", "neq", "gt", "gte", "lt", "lte",
                   "like", "in", "not_in", "is_null", "is_not_null"
                 - "value": the value to compare against
                 Example: [{"field": "vendor", "op": "eq", "value": "Phillips"},
                           {"field": "usd_price_decimal", "op": "gte", "value": 50000}]
        sort_field: Column name to sort by (e.g., "usd_price_decimal" or "sale_date")
        sort_direction: "asc" or "desc" (default: "desc")
        limit: Maximum rows to return (default: 20, max: 500)
        offset: Number of rows to skip for pagination (default: 0)
    """
    body: dict = {"limit": min(limit, 500), "offset": offset}

    if fields:
        body["fields"] = fields
    if filters:
        body["filters"] = filters
    if sort_field:
        body["sort"] = [{"field": sort_field, "direction": sort_direction or "desc"}]

    api_key = _resolve_api_key()
    async with _client(api_key) as client:
        resp = await client.post(f"/v1/tables/{table}/query", json=body)
        if resp.status_code == 404:
            return f"Table '{table}' not found. Use list_tables to see available tables."
        if resp.status_code == 400:
            return f"Bad request: {resp.json().get('detail', resp.text)}"
        if resp.status_code == 429:
            return f"Rate limit exceeded: {resp.json().get('detail', 'Try again later.')}"
        resp.raise_for_status()
        data = resp.json()

    result_count = data["result_count"]
    exec_time = data["execution_time_ms"]

    if result_count == 0:
        return f"No results found (query took {exec_time}ms)."

    rows = data["data"]
    header = f"**{result_count} results** from `{table}` (query: {exec_time}ms, offset: {offset})\n"

    lines = [header]
    for i, row in enumerate(rows, start=offset + 1):
        row_parts = []
        for key, val in row.items():
            if val is not None:
                row_parts.append(f"  {key}: {val}")
        lines.append(f"**{i}.** \n" + "\n".join(row_parts))

    return "\n\n".join(lines)


# ── Tier resolution + recommendation/upsell layer ────────────────
#
# The MCP stays a thin, read-only proxy. This layer NEVER changes what data is
# returned — it only, occasionally, appends ONE clearly-marked "💡" line
# suggesting a complementary ALT/FNDATA product when a query indicates a real
# fit. Upsell lines appear ONLY at a genuine tier boundary (a gated table or an
# exhausted quota) and NEVER for unlimited/comp accounts.

# Canonical self-serve plan prices. Source of truth: API_Management/app/services/
# price_check_service.py (PLAN_PRICES + plan docstrings). Kept in sync manually
# because the MCP is a separate deployable and cannot import the API package.
PLANS = {
    "starter": {"name": "Starter", "monthly": 49, "yearly": 550,
                "url": "https://altfndata.com/membership"},
    "membership": {"name": "Membership", "monthly": 149, "yearly": 1260,
                   "url": "https://altfndata.com/membership"},
}

# Complementary products (feature recommendations, not upsell).
LINK_PRICE_CHECK = "https://altfndata.com/price-check"
LINK_APP = "https://app.altfndata.com"
LINK_DASHBOARDS = "https://altfndata.com/dashboards"
LINK_LICENSING = "https://altfndata.com/data-licensing"

_TIER_RANK = {"free": 0, "starter": 1, "standard": 2, "premium": 3, "unlimited": 4}

# Tiers that may receive an UPSELL nudge (they can meaningfully upgrade).
# premium/unlimited already have broad access — never upsell them.
_UPSELL_TIERS = {"free", "starter", "standard"}

# Cross-table companions surfaced as a neutral "Related tables" note (NOT upsell).
_SIBLING_TABLES = {
    "gems": ("jewelry", "finished/mounted pieces set with stones"),
    "jewelry": ("gems", "loose, unmounted stones"),
    "works_of_art": ("fine_art", "paintings, prints, photographs, sculpture"),
    "fine_art": ("works_of_art", "stone/jewelry-relevant works of art"),
}

# Per-API-key entitlement cache and suggestion state. Keyed by API key so HTTP
# (multi-tenant) mode keeps callers isolated; stdio mode has a single key.
_ENT_TTL = 300  # seconds
_entitlement_cache: dict[str, dict] = {}
_suggestion_state: dict[str, dict] = {}

# Minimum number of tool calls between two (non-forced) suggestions for one key.
_SUGGESTION_MIN_GAP = 3


def _suggestions_allowed(ent: dict) -> bool:
    """Never nudge unlimited/comp/investor accounts — they already have full
    access and are high-touch relationships. A helpful nudge to everyone else;
    nothing here for the people who'd only feel sold-to."""
    return ent.get("tier") != "unlimited"


def _sug_state(api_key: str) -> dict:
    st = _suggestion_state.get(api_key)
    if st is None:
        st = {"calls": 0, "last_shown": -999, "shown_keys": set(),
              "table_calls": {}}
        _suggestion_state[api_key] = st
    return st


async def _get_entitlements(api_key: str) -> dict:
    """Resolve the caller's tier, subscribed tables, and per-table caps.

    Reads /v1/billing/subscription (X-API-Key auth), cached per key. On any
    failure returns a conservative record (tier "unknown") so the upsell layer
    stays silent rather than guessing.
    """
    now = time.time()
    cached = _entitlement_cache.get(api_key)
    if cached and (now - cached["_ts"] < _ENT_TTL):
        return cached

    record = {"_ts": now, "tier": "unknown", "tables": set(),
              "max_rows": {}, "known": False}
    try:
        async with _client(api_key) as client:
            resp = await client.get("/v1/billing/subscription")
        if resp.status_code == 200:
            data = resp.json()
            tables = data.get("tables", {}) or {}
            best = "free"
            for tname, info in tables.items():
                record["tables"].add(tname)
                tier = str(info.get("tier", "free")).lower()
                record["max_rows"][tname] = int(
                    (info.get("limits") or {}).get("max_rows_per_request", 0) or 0
                )
                if _TIER_RANK.get(tier, 0) > _TIER_RANK.get(best, 0):
                    best = tier
            record["tier"] = best
            record["known"] = True
    except Exception:
        pass

    _entitlement_cache[api_key] = record
    return record


def _register_call(api_key: str, table: Optional[str] = None) -> None:
    st = _sug_state(api_key)
    st["calls"] += 1
    if table:
        st["table_calls"][table] = st["table_calls"].get(table, 0) + 1


def _emit_suggestion(api_key: str, key: str, text: str, force: bool = False) -> Optional[str]:
    """Return a suggestion line if allowed, else None. One per session per key;
    non-forced lines are additionally rate-limited so they aren't on every call."""
    st = _sug_state(api_key)
    if key in st["shown_keys"]:
        return None
    if not force and (st["calls"] - st["last_shown"]) < _SUGGESTION_MIN_GAP:
        return None
    st["shown_keys"].add(key)
    st["last_shown"] = st["calls"]
    return text


def _plan_price(plan: str) -> str:
    p = PLANS[plan]
    return f"${p['monthly']}/mo or ${p['yearly']:,}/yr"


def _tables_line(ent: dict) -> str:
    return (f"ALT/FNDATA Membership ({_plan_price('membership')}) unlocks all "
            f"data tables — {PLANS['membership']['url']}")


def _upsell_for_gated(api_key: str, ent: dict, table: str) -> Optional[str]:
    if ent.get("tier") not in _UPSELL_TIERS:
        return None
    return _emit_suggestion(
        api_key, "upsell_gated",
        f"💡 Tip: `{table}` isn't included in your current plan. {_tables_line(ent)}",
        force=True,
    )


def _upsell_for_quota(api_key: str, ent: dict) -> Optional[str]:
    if ent.get("tier") not in _UPSELL_TIERS:
        return None
    return _emit_suggestion(
        api_key, "upsell_quota",
        f"💡 Tip: You've reached today's row quota on your current plan. "
        f"ALT/FNDATA Membership ({_plan_price('membership')}) raises daily limits "
        f"and includes every table — {PLANS['membership']['url']}",
        force=True,
    )


def _looks_single_item(filters: Optional[list[dict]]) -> bool:
    """Heuristic: does this query target one specific piece (a valuation), rather
    than a market segment? True when it pins value-driving attributes exactly."""
    if not filters:
        return False
    single_attrs = {
        "carats", "carat", "gemstone_clarity", "gemstone_cut", "reference_number",
        "reference", "model", "primary_gem", "gold_karat",
    }
    exact_hits = sum(
        1 for f in filters
        if str(f.get("field", "")).lower() in single_attrs
        and str(f.get("op", "")).lower() in ("eq", "like")
    )
    return exact_hits >= 2


def _rec_single_item(api_key: str) -> Optional[str]:
    return _emit_suggestion(
        api_key, "rec_price_check",
        f"💡 Related: For a single piece's fair-value range and comparable sales, "
        f"try Price Check — {LINK_PRICE_CHECK}",
    )


def _rec_monitoring(api_key: str) -> Optional[str]:
    return _emit_suggestion(
        api_key, "rec_alerts",
        f"💡 Related: Track this market automatically with Saved Searches & Price "
        f"Alerts in the ALT/FNDATA app — {LINK_APP}",
    )


def _rec_trend(api_key: str) -> Optional[str]:
    return _emit_suggestion(
        api_key, "rec_dashboards",
        f"💡 Related: Explore interactive price trends and the ALT/FNDATA Market "
        f"Index — {LINK_DASHBOARDS}",
    )


def _rec_bulk(api_key: str) -> Optional[str]:
    return _emit_suggestion(
        api_key, "rec_licensing",
        f"💡 Related: For bulk extracts or a BigQuery data share, see ALT/FNDATA "
        f"data licensing — {LINK_LICENSING}",
    )


def _rec_alerts_membership(api_key: str) -> Optional[str]:
    """Price alerts are a signed-in (Membership) feature, not an API-key one.
    Nudge once — and never for unlimited/comp accounts (guarded by callers)."""
    return _emit_suggestion(
        api_key, "rec_alerts_membership",
        f"💡 Price alerts are included with ALT/FNDATA Membership "
        f"({_plan_price('membership')}) and managed in the app — "
        f"{PLANS['membership']['url']}",
        force=True,
    )


# ── Advanced MCP Tools ───────────────────────────────────────────

_STATS_AGGS = [
    {"function": "count", "field": "*", "alias": "n"},
    {"function": "min", "field": "usd_price_decimal", "alias": "min_usd"},
    {"function": "max", "field": "usd_price_decimal", "alias": "max_usd"},
    {"function": "avg", "field": "usd_price_decimal", "alias": "avg_usd"},
    {"function": "median", "field": "usd_price_decimal", "alias": "median_usd"},
    {"function": "p25", "field": "usd_price_decimal", "alias": "p25_usd"},
    {"function": "p75", "field": "usd_price_decimal", "alias": "p75_usd"},
]
_PERCENTILE_ALIASES = {"median_usd", "p25_usd", "p75_usd"}


def _fmt_money(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


async def _post_query(api_key: str, table: str, body: dict) -> tuple[int, dict]:
    async with _client(api_key) as client:
        resp = await client.post(f"/v1/tables/{table}/query", json=body)
    try:
        payload = resp.json()
    except Exception:
        payload = {"detail": resp.text}
    return resp.status_code, payload


@mcp.tool(annotations={"title": "Market Statistics", "readOnlyHint": True, "openWorldHint": True})
async def market_stats(
    table: str,
    filters: Optional[list[dict]] = None,
    sold_only: bool = True,
) -> str:
    """Summarize the realized-price market for a table or a filtered segment.

    Returns count of sales, median, 25th/75th percentiles, average, min/max of
    `usd_price_decimal`, the sale-date span, and the top vendors by volume — all
    computed server-side over the full matching set (not a sample).

    Args:
        table: Table alias (call list_tables first). "gems" = LOOSE, unmounted
               stones (use for a gemstone-market read); "jewelry" = FINISHED,
               mounted pieces. A loose-stone question can span both.
        filters: Optional list of filter dicts, same shape as query_table
                 (field/op/value). Narrow to a segment, e.g.
                 [{"field": "designer", "op": "eq", "value": "Patek Philippe"}].
        sold_only: When true (default), restricts to sold lots with a positive
                   USD price so the stats reflect realized transactions.
    """
    api_key = _resolve_api_key()
    _register_call(api_key, table)

    eff_filters = list(filters or [])
    if sold_only:
        eff_filters = eff_filters + [
            {"field": "status", "op": "in", "value": ["Sold", "sold"]},
            {"field": "usd_price_decimal", "op": "gte", "value": 1},
        ]

    body = {"aggregations": _STATS_AGGS, "filters": eff_filters, "limit": 1}
    status, payload = await _post_query(api_key, table, body)

    # Backend without percentile support (pre-redeploy): retry with base stats.
    percentiles_ok = True
    if status in (400, 422):
        percentiles_ok = False
        base_aggs = [a for a in _STATS_AGGS if a["alias"] not in _PERCENTILE_ALIASES]
        body = {"aggregations": base_aggs, "filters": eff_filters, "limit": 1}
        status, payload = await _post_query(api_key, table, body)

    if status == 404:
        return f"Table '{table}' not found. Use list_tables to see available tables."
    if status == 403:
        ent = await _get_entitlements(api_key)
        msg = f"Your plan doesn't include the `{table}` table."
        tip = _upsell_for_gated(api_key, ent, table)
        return msg + (f"\n\n{tip}" if tip else "")
    if status == 429:
        ent = await _get_entitlements(api_key)
        tip = _upsell_for_quota(api_key, ent)
        base = f"Row quota reached: {payload.get('detail', 'try again later.')}"
        return base + (f"\n\n{tip}" if tip else "")
    if status != 200:
        return f"Could not compute market stats: {payload.get('detail', payload)}"

    rows = payload.get("data") or [{}]
    s = rows[0] if rows else {}
    n = s.get("n")
    if not n or int(float(n)) == 0:
        return f"No sold results found in `{table}` for that filter."

    # Date span (min/max sale_date) — a lightweight second aggregate.
    span_body = {
        "aggregations": [
            {"function": "min", "field": "sale_date", "alias": "first_sale"},
            {"function": "max", "field": "sale_date", "alias": "last_sale"},
        ],
        "filters": eff_filters, "limit": 1,
    }
    _, span_payload = await _post_query(api_key, table, span_body)
    span = (span_payload.get("data") or [{}])[0] if span_payload else {}

    # Top vendors by volume.
    vendor_body = {
        "aggregations": [{"function": "count", "field": "*", "alias": "cnt"}],
        "group_by": ["vendor"], "filters": eff_filters,
        "sort": [{"field": "cnt", "direction": "desc"}], "limit": 5,
    }
    _, vendor_payload = await _post_query(api_key, table, vendor_body)
    vendors = vendor_payload.get("data") or []

    lines = [f"**Market stats for `{table}`**"
             + (" (sold lots, USD)" if sold_only else " (all lots, USD)")]
    lines.append(f"- Sales counted: {int(float(n)):,}")
    if percentiles_ok and s.get("median_usd") is not None:
        lines.append(f"- Median: {_fmt_money(s.get('median_usd'))}  "
                     f"(25th {_fmt_money(s.get('p25_usd'))} – "
                     f"75th {_fmt_money(s.get('p75_usd'))})")
    lines.append(f"- Average: {_fmt_money(s.get('avg_usd'))}")
    lines.append(f"- Range: {_fmt_money(s.get('min_usd'))} – {_fmt_money(s.get('max_usd'))}")
    if span.get("first_sale") or span.get("last_sale"):
        lines.append(f"- Date span: {span.get('first_sale', '?')} → {span.get('last_sale', '?')}")
    if vendors:
        top = ", ".join(
            f"{v.get('vendor') or 'Unknown'} ({int(float(v.get('cnt', 0))):,})"
            for v in vendors if v.get("vendor")
        )
        if top:
            lines.append(f"- Top vendors: {top}")
    if not percentiles_ok:
        lines.append("- (Median/percentiles unavailable until the API percentile "
                     "update is deployed.)")

    # Cross-table companion note (disambiguation, not upsell).
    sib = _SIBLING_TABLES.get(table)
    if sib:
        lines.append(f"\nRelated table: `{sib[0]}` covers {sib[1]} — check it too "
                     f"if your subject could appear there.")

    # ── One suggestion, if it fits (never for unlimited/comp accounts) ──
    ent = await _get_entitlements(api_key)
    if _suggestions_allowed(ent):
        capped = ent.get("tier") in ("free", "starter", "standard")
        n_int = int(float(n))
        suggestion = None
        # Priority: single-item valuation > bulk (large segment, capped tier) >
        # repeated-monitoring intent.
        if _looks_single_item(filters):
            suggestion = _rec_single_item(api_key)
        if not suggestion and capped and n_int >= 50000:
            suggestion = _rec_bulk(api_key)
        if not suggestion and _sug_state(api_key)["table_calls"].get(table, 0) >= 3:
            suggestion = _rec_monitoring(api_key)
        if suggestion:
            lines.append(f"\n{suggestion}")

    return "\n".join(lines)


@mcp.tool(annotations={"title": "Price Trend Over Time", "readOnlyHint": True, "openWorldHint": True})
async def price_trend(
    table: str,
    filters: Optional[list[dict]] = None,
    by: str = "year",
    sold_only: bool = True,
) -> str:
    """Show how realized prices moved over time for a table or filtered segment.

    Buckets sold lots by sale period and reports, per period, the number of
    sales, the median, and the average `usd_price_decimal`.

    Args:
        table: Table alias (call list_tables first). Gems = loose stones;
               jewelry = mounted pieces.
        filters: Optional filter dicts (field/op/value), same shape as query_table.
        by: Time bucket — "year" (default), "quarter", or "month".
        sold_only: Restrict to sold lots with a positive USD price (default true).
    """
    api_key = _resolve_api_key()
    _register_call(api_key, table)

    bucket = (by or "year").lower()
    if bucket not in ("year", "quarter", "month"):
        return "`by` must be one of: year, quarter, month."

    eff_filters = list(filters or [])
    if sold_only:
        eff_filters = eff_filters + [
            {"field": "status", "op": "in", "value": ["Sold", "sold"]},
            {"field": "usd_price_decimal", "op": "gte", "value": 1},
        ]

    aggs = [
        {"function": "count", "field": "*", "alias": "n"},
        {"function": "median", "field": "usd_price_decimal", "alias": "median_usd"},
        {"function": "avg", "field": "usd_price_decimal", "alias": "avg_usd"},
    ]
    body = {"aggregations": aggs, "group_by_time": {"field": "sale_date", "bucket": bucket},
            "filters": eff_filters, "sort": [{"field": "sale_date", "direction": "asc"}],
            "limit": 200}
    status, payload = await _post_query(api_key, table, body)

    percentiles_ok = True
    if status in (400, 422):
        percentiles_ok = False
        aggs = [a for a in aggs if a["alias"] != "median_usd"]
        body["aggregations"] = aggs
        status, payload = await _post_query(api_key, table, body)

    if status == 404:
        return f"Table '{table}' not found. Use list_tables to see available tables."
    if status == 403:
        ent = await _get_entitlements(api_key)
        tip = _upsell_for_gated(api_key, ent, table)
        return f"Your plan doesn't include the `{table}` table." + (f"\n\n{tip}" if tip else "")
    if status == 429:
        ent = await _get_entitlements(api_key)
        tip = _upsell_for_quota(api_key, ent)
        return f"Row quota reached: {payload.get('detail', 'try again later.')}" + (f"\n\n{tip}" if tip else "")
    if status != 200:
        return f"Could not compute price trend: {payload.get('detail', payload)}"

    rows = payload.get("data") or []
    rows = [r for r in rows if r.get("sale_date") not in (None, "", "null")]
    if not rows:
        return f"No dated sold results found in `{table}` for that filter."

    lines = [f"**Price trend for `{table}` by {bucket}** (sold lots, USD)"]
    for r in rows:
        period = r.get("sale_date")
        n = int(float(r.get("n", 0) or 0))
        med = _fmt_money(r.get("median_usd")) if percentiles_ok and r.get("median_usd") is not None else "—"
        avg = _fmt_money(r.get("avg_usd"))
        lines.append(f"- {period}: {n:,} sales · median {med} · avg {avg}")
    if not percentiles_ok:
        lines.append("- (Median unavailable until the API percentile update is deployed; showing average.)")

    ent = await _get_entitlements(api_key)
    if _suggestions_allowed(ent):
        tip = _rec_trend(api_key)
        if tip:
            lines.append(f"\n{tip}")
    return "\n".join(lines)


# Categories the live comp matcher serves (see AFI_PRICE_CHECK_CATEGORIES).
_PRICE_CHECK_LIVE_CATS = {"handbags", "watches", "cars"}


def _infer_price_check_category(text: str) -> str:
    t = (text or "").lower()
    watch_kw = ("watch", "rolex", "patek", "omega", "audemars", "cartier tank",
                "chronograph", "ref.", "wristwatch", "tourbillon")
    car_kw = ("ferrari", "porsche", "car", "coupe", "roadster", "aston martin",
              "lamborghini", "bugatti", "mercedes", "chassis", "convertible")
    if any(k in t for k in watch_kw):
        return "watches"
    if any(k in t for k in car_kw):
        return "cars"
    return "handbags"


@mcp.tool(annotations={"title": "Price Check (Valuation)", "readOnlyHint": True, "openWorldHint": True})
async def price_check(
    description: Optional[str] = None,
    lot_url: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """Estimate a single item's fair-value range from comparable auction sales.

    Give either a free-text description (e.g. "Hermès Birkin 25 Togo, gold
    hardware") OR a lot URL from an auction house. Returns a realized-price range
    (low / median / high), a confidence read, and comparable sales with source
    links. Best for valuing ONE specific piece; for a whole-market read use
    market_stats.

    Live comp categories are handbags, watches, and cars. Loose gemstones and
    jewelry are intentionally held from comp-matching (under-specified colored
    stones give unreliable medians) — for those, use market_stats on `gems`
    (loose stones) or `jewelry` (mounted pieces) instead.

    Args:
        description: Free-text item description.
        lot_url: A lot URL from an auction house (alternative to description).
        category: One of "handbags", "watches", "cars". Inferred from the text
                  if omitted.
    """
    api_key = _resolve_api_key()
    _register_call(api_key)

    item = (lot_url or description or "").strip()
    if not item:
        return "Provide either a `description` or a `lot_url` to price-check."

    cat = (category or _infer_price_check_category(description or lot_url or "")).lower().strip()
    if cat in ("gems", "gem", "jewelry", "jewellery", "loose stone", "gemstone"):
        return ("Comp-matching for loose stones and jewelry is held back (colored "
                "stones under-specify origin/treatment, which drive value). Use "
                "market_stats on `gems` (loose, unmounted stones) or `jewelry` "
                "(finished, mounted pieces) for a realized-price read instead.")
    if cat not in _PRICE_CHECK_LIVE_CATS:
        cat = _infer_price_check_category(description or lot_url or "")

    async with _client(api_key) as client:
        resp = await client.post(
            "/v1/price-check/check", json={"input": item, "category": cat}
        )
    if resp.status_code == 503:
        return "Price Check is temporarily unavailable. Try again shortly."
    if resp.status_code == 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        return f"Price Check couldn't handle that request: {detail}"
    if resp.status_code != 200:
        return f"Price Check failed (HTTP {resp.status_code})."

    data = resp.json()
    if not data.get("ok"):
        return (f"No confident comparables found for that {cat} item. Try a more "
                f"specific description (brand, model, size, material).")

    parsed = data.get("parsed") or {}
    result = data.get("result") or {}
    stats = result.get("stats") or {}
    verdict = result.get("verdict") or {}

    label_bits = [parsed.get("brand"), parsed.get("model")]
    label = " ".join(b for b in label_bits if b) or (parsed.get("title") or item)[:80]

    lines = [f"**Price Check — {label}** ({cat})"]
    if stats:
        lines.append(
            f"- Realized range: {_fmt_money(stats.get('low'))} – "
            f"{_fmt_money(stats.get('high'))}  ·  median "
            f"{_fmt_money(stats.get('median'))}"
        )
        if stats.get("count") is not None:
            lines.append(f"- Based on {int(stats['count']):,} comparable sales "
                         f"(confidence: {result.get('confidence', 'n/a')})")
    if verdict.get("text"):
        lines.append(f"- Verdict: {verdict['text']}")

    comps = result.get("comps_preview") or []
    if comps:
        lines.append("\nComparable sales:")
        for c in comps:
            price = _fmt_money(c.get("usd_price"))
            when = c.get("sale_date") or c.get("year") or ""
            vend = c.get("vendor") or ""
            title = (c.get("title") or "").strip()
            url = c.get("lot_url") or ""
            meta = " · ".join(x for x in [price, str(when), vend] if x)
            lines.append(f"- {title[:90]} — {meta}" + (f"\n  {url}" if url else ""))
    if result.get("full_results_locked"):
        lines.append("\n(Showing the top comparables. The full comp set and saved "
                     "monitoring are available in the app.)")

    # After a single-item valuation, the genuine next step is monitoring — not a
    # circular pointer back to Price Check.
    ent = await _get_entitlements(api_key)
    if _suggestions_allowed(ent):
        tip = _rec_monitoring(api_key)
        if tip:
            lines.append(f"\n{tip}")
    return "\n".join(lines)


# ── search (whole-market keyword search) ─────────────────────────
#
# Wraps the same server-side "search" operator the Search app uses:
# {"field": "_keyword", "op": "search", "value": <token>} on
# POST /v1/tables/{alias}/query. One filter per token (server ORs across
# item_title/designer/vendor/gem_type/primary_gem/origin/color/model/sale_title
# and expands synonyms). With no category it fans out across the whole market and
# merges by realized price.

# The table set is read LIVE from GET /v1/tables (see _all_tables). This list is
# only the fallback for when that call fails - never the source of truth. It was
# once hardcoded to 15 tables while the API served 19, so a whole-market search
# silently skipped coins, other_automobile, perfume and accessories, and
# category="coins" matched nothing, fell back to "the whole market", and searched
# every table EXCEPT coins.
_FALLBACK_TABLES = [
    "watches", "jewelry", "gems", "handbags", "automobile", "motorcycle",
    "aircraft", "wine_whisky", "works_of_art", "fine_art", "design",
    "fashion", "shoes", "automobilia", "books", "coins", "other_automobile",
    "perfume", "accessories", "musical_instruments",
]

# /v1/tables returns the whole registry - it is not filtered per key, and search()
# applies the caller's entitlements separately - so one process-wide cache is
# correct. The registry only changes when the API is redeployed.
_TABLES_TTL_SECONDS = 600
_tables_cache: dict = {"names": None, "at": 0.0}


async def _all_tables(api_key: str) -> list[str]:
    """Every table the API currently serves, cached; the static list on failure."""
    now = time.monotonic()
    cached = _tables_cache["names"]
    if cached and now - _tables_cache["at"] < _TABLES_TTL_SECONDS:
        return list(cached)
    try:
        async with _client(api_key) as client:
            resp = await client.get("/v1/tables")
            resp.raise_for_status()
            names = [t["name"] for t in (resp.json().get("tables") or []) if t.get("name")]
        if names:
            _tables_cache["names"], _tables_cache["at"] = names, now
            return list(names)
    except Exception:  # noqa: BLE001 - a failed lookup must never break search
        pass
    return list(cached or _FALLBACK_TABLES)

# Free-text / category term → target table(s). Ambiguous "gemstone"/"stone"
# terms fan out across BOTH gems (loose) and jewelry (mounted) so a loose-stone
# question is never silently dropped.
_SEARCH_CATEGORY_ALIASES = {
    "watch": ["watches"], "watches": ["watches"], "wristwatch": ["watches"],
    "handbag": ["handbags"], "handbags": ["handbags"], "bag": ["handbags"],
    "purse": ["handbags"],
    "gem": ["gems", "jewelry"], "gems": ["gems"], "gemstone": ["gems", "jewelry"],
    "gemstones": ["gems", "jewelry"], "loose stone": ["gems"], "stone": ["gems", "jewelry"],
    "jewelry": ["jewelry"], "jewellery": ["jewelry"], "jewel": ["jewelry"],
    "jewels": ["jewelry"],
    "car": ["automobile"], "cars": ["automobile"], "automobile": ["automobile"],
    "automobiles": ["automobile"], "vehicle": ["automobile"],
    "motorcycle": ["motorcycle"], "motorbike": ["motorcycle"],
    "aircraft": ["aircraft"], "plane": ["aircraft"],
    "wine": ["wine_whisky"], "whisky": ["wine_whisky"], "whiskey": ["wine_whisky"],
    "spirits": ["wine_whisky"], "wine_whisky": ["wine_whisky"],
    "art": ["fine_art", "works_of_art"], "fine_art": ["fine_art"],
    "fine art": ["fine_art"], "painting": ["fine_art"], "paintings": ["fine_art"],
    "works_of_art": ["works_of_art"], "works of art": ["works_of_art"],
    "design": ["design"], "furniture": ["design"], "decorative arts": ["design"],
    "fashion": ["fashion"], "couture": ["fashion"], "clothing": ["fashion"],
    "shoes": ["shoes"], "shoe": ["shoes"], "sneaker": ["shoes"], "sneakers": ["shoes"],
    "automobilia": ["automobilia"], "memorabilia": ["automobilia"],
    "books": ["books"], "book": ["books"], "manuscript": ["books"], "map": ["books"],
    "coins": ["coins"], "coin": ["coins"], "numismatic": ["coins"],
    "numismatics": ["coins"],
    "perfume": ["perfume"], "perfumes": ["perfume"], "fragrance": ["perfume"],
    "fragrances": ["perfume"],
    "accessories": ["accessories"], "accessory": ["accessories"],
    "cufflinks": ["accessories"], "sunglasses": ["accessories"],
    # Scarves and belts are catalogued in both accessories and fashion, so either
    # hint searches both - the same no-silent-drop rule as gems/jewelry above.
    "scarf": ["accessories", "fashion"], "scarves": ["accessories", "fashion"],
    "belt": ["accessories", "fashion"], "belts": ["accessories", "fashion"],
    "other_automobile": ["other_automobile"], "boat": ["other_automobile"],
    "boats": ["other_automobile"], "tractor": ["other_automobile"],
    "tractors": ["other_automobile"], "truck": ["other_automobile"],
    "trucks": ["other_automobile"],
    "musical_instruments": ["musical_instruments"],
    "musical instruments": ["musical_instruments"],
    "musical instrument": ["musical_instruments"], "instrument": ["musical_instruments"],
    "instruments": ["musical_instruments"], "guitar": ["musical_instruments"],
    "guitars": ["musical_instruments"], "violin": ["musical_instruments"],
    "violins": ["musical_instruments"], "cello": ["musical_instruments"],
    "piano": ["musical_instruments"], "pianos": ["musical_instruments"],
}


def _resolve_search_tables(category: Optional[str], all_tables: list[str]) -> list[str]:
    """Map a category hint to target tables. Unknown/blank → the whole market.

    `all_tables` is the live set from _all_tables(). An alias pointing at a table
    the API no longer serves is dropped rather than queried; if nothing survives,
    the search widens to the whole market instead of returning nothing.
    """
    everything = list(all_tables)
    if not category:
        return everything
    c = category.strip().lower()
    if c in everything:
        return [c]
    if c in _SEARCH_CATEGORY_ALIASES:
        hit = [t for t in _SEARCH_CATEGORY_ALIASES[c] if t in everything]
        if hit:
            return hit
    return everything


def _row_price(row: dict) -> float:
    try:
        return float(row.get("usd_price_decimal") or 0)
    except (TypeError, ValueError):
        return 0.0


@mcp.tool(annotations={"title": "Search All Categories", "readOnlyHint": True, "openWorldHint": True})
async def search(
    query: str,
    category: Optional[str] = None,
    filters: Optional[list[dict]] = None,
    limit: int = 25,
) -> str:
    """Whole-market keyword search across every ALT/FNDATA category at once.

    Runs a server-side free-text search (the same engine behind the ALT/FNDATA
    Search app): your `query` is split into tokens, each matched across
    item_title, designer, vendor, gem_type, primary_gem, origin, color, model
    and sale_title with synonym expansion (e.g. ruby↔rubis, jade↔jadeite). With
    no `category` it fans out across the whole market and merges the top realized
    sales by USD price — so you don't have to guess which table holds an item.

    Args:
        query: Free-text keywords, e.g. "ruby ring", "Daytona 116500", "Birkin 25".
        category: Optional hint to narrow the search — a table alias
                  (e.g. "watches") or a plain word ("cars", "gemstone"). A
                  gemstone/stone hint searches BOTH gems (loose) and jewelry
                  (mounted); omit it to search everything.
        filters: Optional extra filter dicts (same field/op/value shape as
                 query_table), AND-ed with the keyword match — e.g.
                 [{"field": "usd_price_decimal", "op": "gte", "value": 50000}].
        limit: Max merged results to return (default 25, max 100).
    """
    api_key = _resolve_api_key()
    _register_call(api_key)

    q = (query or "").strip()
    extra = list(filters or [])
    if not q and not extra:
        return 'Provide a `query` (keywords) to search, e.g. "ruby ring" or "Daytona".'

    kw_filters = [{"field": "_keyword", "op": "search", "value": w}
                  for w in q.split() if w]
    base_filters = extra + kw_filters

    tables = _resolve_search_tables(category, await _all_tables(api_key))

    # Respect entitlements: when the plan is known, only fan out across subscribed
    # tables so we never surface — or 403-spam — data a tier isn't subscribed to.
    ent = await _get_entitlements(api_key)
    gated: list[str] = []
    if ent.get("known") and ent.get("tables"):
        wanted = tables
        tables = [t for t in wanted if t in ent["tables"]]
        gated = [t for t in wanted if t not in ent["tables"]]
        if not tables:
            msg = (f"None of the tables this search targets "
                   f"({', '.join(wanted)}) are included in your plan.")
            tip = _upsell_for_gated(api_key, ent, wanted[0])
            return msg + (f"\n\n{tip}" if tip else "")

    cap = max(1, min(limit, 100))
    per_table = max(3, min(cap, 50))
    body = {"filters": base_filters, "limit": per_table,
            "sort": [{"field": "usd_price_decimal", "direction": "desc"}]}

    async def _one(t: str):
        status, payload = await _post_query(api_key, t, dict(body))
        return t, status, payload

    outcomes = await asyncio.gather(*[_one(t) for t in tables])

    merged: list[tuple[str, dict]] = []
    hit_quota = False
    searched: list[str] = []
    for t, status, payload in outcomes:
        if status == 200:
            searched.append(t)
            for row in (payload.get("data") or []):
                merged.append((t, row))
        elif status == 403:
            gated.append(t)
        elif status == 429:
            hit_quota = True
        # 404 / other → skip silently (table may lack a searched column)

    merged.sort(key=lambda tr: _row_price(tr[1]), reverse=True)
    merged = merged[:cap]

    if not merged:
        parts = []
        if searched:
            parts.append(f"No results for that search across "
                         f"{', '.join(searched)}.")
        else:
            parts.append("No results for that search.")
        if hit_quota:
            tip = _upsell_for_quota(api_key, ent)
            if tip:
                parts.append(tip)
        elif gated and ent.get("tier") in _UPSELL_TIERS:
            tip = _upsell_for_gated(api_key, ent, sorted(set(gated))[0])
            if tip:
                parts.append(tip)
        return "\n\n".join(parts)

    scope = "the whole market" if len(searched) > 1 else f"`{searched[0]}`"
    lines = [f"**{len(merged)} results** for \"{q}\" across {scope} "
             f"(searched: {', '.join(searched)})\n"]
    for i, (t, row) in enumerate(merged, start=1):
        title = (row.get("item_title") or row.get("sale_title") or "").strip()
        bits = []
        price = row.get("usd_price_decimal")
        if price not in (None, "", 0, "0"):
            bits.append(_fmt_money(price))
        for key in ("vendor", "sale_date", "designer", "brand_name", "artist_name",
                    "primary_gem"):
            val = row.get(key)
            if val not in (None, "", "-"):
                bits.append(str(val))
                if len(bits) >= 4:
                    break
        meta = " · ".join(bits)
        line = f"**{i}.** [{t}] {title[:100]}" + (f" — {meta}" if meta else "")
        url = row.get("lot_url")
        if url:
            line += f"\n  {url}"
        lines.append(line)

    # Gems-vs-jewelry disambiguation reminder when relevant and results are thin.
    touched = set(searched)
    if ("gems" in touched) ^ ("jewelry" in touched):
        other = "jewelry" if "gems" in touched else "gems"
        kind = "finished/mounted pieces" if other == "jewelry" else "loose, unmounted stones"
        lines.append(f"\nTip: `{other}` ({kind}) may also hold matches — "
                     f"pass category=\"{other}\" to check it.")

    # One suggestion max, only at a real boundary, never for unlimited.
    tail = None
    if hit_quota:
        tail = _upsell_for_quota(api_key, ent)
    elif gated and ent.get("tier") in _UPSELL_TIERS:
        tail = _upsell_for_gated(api_key, ent, sorted(set(gated))[0])
    if tail:
        lines.append(f"\n{tail}")

    return "\n".join(lines)


# ── market_index (precomputed model-level price indices) ─────────
#
# Wraps the REAL precomputed hot-stats behind the ALT/FNDATA Index:
#   GET /v1/price-check/model-stats  (a typed model query → one headline)
#   GET /v1/price-check/model-index  (a brand → all its model indices)
# These are always-on, instant, and cover the three comp-matched categories
# (handbags, watches, cars). Nothing is fabricated: if a figure isn't in the
# precompute, that's reported.

_MODEL_INDEX_CATS = {"handbags", "watches", "cars"}
_ITEM_CLASS_BY_CAT = {"handbags": "bag", "watches": "watch", "cars": "car"}


def _fmt_index_stats(stats: dict) -> str:
    order = [("low", "low"), ("p25", "25th"), ("median", "median"),
             ("p75", "75th"), ("high", "high")]
    bits = [f"{label} {_fmt_money(stats[k])}" for k, label in order
            if stats.get(k) is not None]
    return "  ·  ".join(bits)


@mcp.tool(annotations={"title": "Market Price Index", "readOnlyHint": True, "openWorldHint": True})
async def market_index(
    query: Optional[str] = None,
    brand: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """Precomputed model-level price index (headline figures) for a model or brand.

    Reads the ALT/FNDATA Index's precomputed hot-stats — instant, no scan. Give a
    typed model `query` (e.g. "Hermès Birkin 25", "Rolex Daytona 116500") for a
    single model's realized-price band (low / 25th / median / 75th / high), sample
    size, and recent trend; or give a `brand` alone for that brand's whole set of
    model indices. Covered categories are handbags, watches, and cars. For other
    categories, use market_stats (whole-market read) or price_trend instead — this
    tool never invents a figure that isn't precomputed.

    Args:
        query: A specific model to look up (brand + model + optional size/material).
        brand: A brand to list all model indices for (alternative to query).
        category: One of "handbags", "watches", "cars". Inferred from the text
                  when omitted.
    """
    api_key = _resolve_api_key()
    _register_call(api_key)

    text = (query or brand or "").strip()
    if not text:
        return ('Provide a model `query` (e.g. "Rolex Daytona") or a `brand` '
                '(e.g. "Hermès").')

    cat = (category or _infer_price_check_category(text)).lower().strip()
    if cat in ("gems", "gem", "jewelry", "jewellery", "gemstone"):
        return ("The Market Index (precomputed model-level stats) covers handbags, "
                "watches, and cars. For loose stones or jewelry, use market_stats "
                "on `gems` / `jewelry` for a realized-price read instead.")
    if cat not in _MODEL_INDEX_CATS:
        return (f"The ALT/FNDATA Market Index covers handbags, watches, and cars. "
                f"For {cat}, use market_stats(table=\"{cat}\") for a realized-price "
                f"read, or price_trend for how prices moved over time.")

    # Brand-only → the brand's full index list; otherwise a single model headline.
    if brand and not query:
        item_class = _ITEM_CLASS_BY_CAT.get(cat, "bag")
        async with _client(api_key) as client:
            resp = await client.get("/v1/price-check/model-index",
                                    params={"brand": brand, "category": cat,
                                            "item_class": item_class})
        if resp.status_code != 200:
            return f"Market Index unavailable for that brand (HTTP {resp.status_code})."
        data = resp.json()
        models = data.get("models") or []
        if not models:
            return (f"No precomputed index for `{data.get('brand', brand)}` in "
                    f"{cat}. Try a specific model via `query`, or market_stats.")
        canon = data.get("brand", brand)
        lines = [f"**ALT/FNDATA Market Index — {canon}** ({cat}, {len(models)} models)"]
        # model-index rows are flat: {model, n, median, trend_dir, trend_pct}.
        ranked = sorted(models, key=lambda m: m.get("median") or 0, reverse=True)
        for m in ranked[:25]:
            med = _fmt_money(m.get("median")) if m.get("median") is not None else "—"
            n = m.get("n")
            name = m.get("model") or "?"
            extra = f" · n={n}" if n else ""
            tdir = m.get("trend_dir")
            tpct = m.get("trend_pct")
            tstr = (f" · trend {tdir} {tpct:+.1f}%"
                    if tdir and isinstance(tpct, (int, float)) else "")
            lines.append(f"- {name}: median {med}{extra}{tstr}")
    else:
        async with _client(api_key) as client:
            resp = await client.get("/v1/price-check/model-stats",
                                    params={"q": text, "category": cat})
        if resp.status_code != 200:
            return f"Market Index lookup failed (HTTP {resp.status_code})."
        data = resp.json()
        if not data.get("found"):
            return (f"No precomputed index for \"{text}\" in {cat} "
                    f"(reason: {data.get('reason', 'not found')}). Try a broader "
                    f"brand via `brand`, or market_stats for a live read.")
        stats = data.get("stats") or {}
        label = data.get("model") or text
        lines = [f"**ALT/FNDATA Market Index — {data.get('brand', '')} {label}** ({cat})".replace("  ", " ")]
        band = _fmt_index_stats(stats)
        if band:
            lines.append(f"- Realized band: {band}")
        n = data.get("n")
        tier = data.get("tier")
        meta = []
        if n is not None:
            meta.append(f"{int(n):,} sales")
        if tier:
            meta.append(f"depth: {tier}")
        if data.get("size_relaxed"):
            meta.append("size-relaxed match")
        if meta:
            lines.append(f"- Based on {' · '.join(meta)}")
        trend = data.get("trend") or {}
        if trend.get("direction"):
            pct = trend.get("pct_change")
            pstr = f" ({pct:+.1f}%)" if isinstance(pct, (int, float)) else ""
            lines.append(f"- Trend: {trend['direction']}{pstr}")

    ent = await _get_entitlements(api_key)
    if _suggestions_allowed(ent):
        tip = _rec_trend(api_key)
        if tip:
            lines.append(f"\n{tip}")
    return "\n".join(lines)


# ── list_alerts (READ-ONLY — alerts are a signed-in account feature) ─
#
# Price alerts and the watchlist (GET /v1/price-check/alerts,
# POST /history/{id}/watch) are gated by _require_claims — a Cognito ID token
# from a signed-in ALT/FNDATA account. The MCP authenticates with an API key
# (X-API-Key), NOT a Cognito login, so it CANNOT create/enable alerts and the
# alerts feed itself returns 401 for an API-key caller. This tool is therefore
# read-only and honest about that boundary, with the alert allowance ladder
# (free 0 · registered 1 · collector 10 · pro 100 · included on Membership).

@mcp.tool(annotations={"title": "List Price Alerts", "readOnlyHint": True, "openWorldHint": True})
async def list_alerts(limit: int = 25) -> str:
    """Show ALT/FNDATA price alerts (read-only) or explain how to set them up.

    Price alerts watch a saved item and fire when a matching lot sells at or below
    your target. They belong to a signed-in ALT/FNDATA account, not to an API key —
    so alerts are created and managed in the app (app.altfndata.com), and this MCP
    can only read/report them. If your key isn't tied to a signed-in session, this
    returns guidance on enabling alerts (allowance: free 0 · registered 1 ·
    collector 10 · pro 100 · included with Membership) rather than a data feed.

    Args:
        limit: Max fired alerts to show if the alerts feed is reachable (default 25).
    """
    api_key = _resolve_api_key()
    _register_call(api_key)

    try:
        async with _client(api_key) as client:
            resp = await client.get("/v1/price-check/alerts",
                                    params={"limit": max(1, min(limit, 100))})
        status = resp.status_code
        payload = resp.json() if status == 200 else {}
    except Exception:
        status, payload = 0, {}

    if status == 200:
        alerts = payload.get("alerts") or []
        if not alerts:
            return ("No price alerts have fired yet. Alerts watch your saved items "
                    "and notify you when a matching lot sells at/below your target — "
                    "set them up in the ALT/FNDATA app: " + LINK_APP)
        lines = [f"**{len(alerts)} price alert(s)** (newest first)"]
        for i, a in enumerate(alerts, start=1):
            title = (a.get("title") or a.get("query") or "").strip()
            price = _fmt_money(a.get("usd_price")) if a.get("usd_price") else ""
            when = a.get("sale_date") or a.get("fired_at") or ""
            meta = " · ".join(x for x in [price, str(when)] if x)
            line = f"**{i}.** {title[:100]}" + (f" — {meta}" if meta else "")
            url = a.get("lot_url")
            if url:
                line += f"\n  {url}"
            lines.append(line)
        return "\n".join(lines)

    # 401/403 (API-key caller, no Cognito login) or anything else → honest guidance.
    lines = [
        "Price alerts are tied to a signed-in ALT/FNDATA account, so they can't be "
        "read or created through an API key — set them up in the app (save a search, "
        "then toggle its alert): " + LINK_APP,
        "",
        "Alert allowance by plan: free 0 · registered 1 · collector 10 · pro 100. "
        "Alerts are included with ALT/FNDATA Membership.",
    ]
    ent = await _get_entitlements(api_key)
    if _suggestions_allowed(ent):
        tip = _rec_alerts_membership(api_key)
        if tip:
            lines.append("")
            lines.append(tip)
    return "\n".join(lines)


# ── Entry point ──────────────────────────────────────────────────

def main():
    """Entry point for the ALT/FNDATA MCP server."""
    if TRANSPORT == "streamable-http":
        import uvicorn
        from starlette.middleware.cors import CORSMiddleware

        from altfinance_mcp.login_handler import register_login_routes

        from pathlib import Path
        from starlette.responses import Response as StarletteResponse

        # Register login page routes
        register_login_routes(mcp, _oauth_provider)

        # Register favicon route for Google favicon service
        _favicon_path = Path(__file__).parent / "favicon.png"
        _favicon_bytes = _favicon_path.read_bytes() if _favicon_path.exists() else b""

        @mcp.custom_route("/favicon.ico", methods=["GET"])
        async def favicon(request):
            return StarletteResponse(
                content=_favicon_bytes,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"},
            )

        @mcp.custom_route("/", methods=["GET"])
        async def root(request):
            from starlette.responses import HTMLResponse
            return HTMLResponse(await _get_landing_html())

        # Build the Starlette app with CORS
        app = mcp.streamable_http_app()
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "https://claude.ai",
                "https://claude.com",
                "http://localhost:6274",  # Claude Code
            ],
            allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Accept",
                "Mcp-Protocol-Version",
                "Mcp-Session-Id",
                "Last-Event-Id",
            ],
            allow_credentials=True,
        )
        # Accept client_secret_basic without client_id in the form body (RFC 6749)
        from altfinance_mcp.basic_auth_shim import BasicAuthClientIdShim
        app.add_middleware(BasicAuthClientIdShim)

        print(f"ALT/FNDATA MCP Server (HTTP) — {HOST}:{PORT}", file=sys.stderr)
        print(f"  MCP endpoint: /mcp", file=sys.stderr)
        print(f"  OAuth issuer: {ISSUER_URL}", file=sys.stderr)
        print(f"  API backend:  {API_URL}", file=sys.stderr)
        # Logging is not set up yet when the store is chosen at import, so say it here
        _store = _oauth_provider.store
        if getattr(_store, "persistent", False):
            print(f"  OAuth state:  DynamoDB {_store.table_name} (persistent)", file=sys.stderr)
        else:
            print("  OAuth state:  in memory (connections are lost on restart)", file=sys.stderr)
        uvicorn.run(app, host=HOST, port=PORT)
    else:
        if not API_KEY:
            print("Warning: ALTFINANCE_API_KEY not set", file=sys.stderr)
        print(f"ALT/FNDATA MCP Server (stdio) — connecting to {API_URL}", file=sys.stderr)
        mcp.run(transport="stdio")
