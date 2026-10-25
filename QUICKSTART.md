# AltFinance Data API — Quickstart Guide

Welcome to the ALT/FNDATA Data API! You have access to **millions of luxury and collectibles auction records across 20 categories** — watches, jewelry, loose gemstones, handbags, cars, motorcycles, aircraft, wine and whisky, fine art, works of art, design, fashion, shoes, automobilia, books, coins, other vehicles, perfume, accessories and musical instruments — from 100+ auction houses worldwide. Call `list_tables` (or `GET /v1/tables`) for the live set with current column counts.

---

## Your API Key

```
API Key: <YOUR_KEY_HERE>
Base URL: https://api.altfndata.com
```

---

## Option 1: Use with an AI assistant (MCP Server)

The fastest way to explore the data is through an AI assistant using our MCP server. It works with Claude, ChatGPT, Gemini, Perplexity and other MCP-capable assistants.

### Hosted connector (no install — Claude, ChatGPT, Gemini, Perplexity)

In any assistant that supports remote MCP servers (often called **custom connectors**), add a connector with this URL:

```
https://mcp.altfndata.com/mcp
```

Choose **OAuth** if asked for an authentication method; a sign-in page then asks for your ALT/FNDATA API key.

- **Claude:** Settings → Connectors → add a custom connector.
- **ChatGPT:** add it as a custom connector (developer mode). ChatGPT only connects to hosted servers, so use this option.
- **Gemini (personal):** Settings → Connected Apps → add a custom app with the URL above.
- **Perplexity:** Settings → Connectors → add a custom connector with the URL above.

Full per-assistant steps (including Gemini Enterprise) are in the package [README](https://pypi.org/project/altfinance-mcp/).

### Claude Desktop (local install)

1. Install the MCP server (or run it with no install via `uvx altfinance-mcp` — see note below):

```bash
pip install altfinance-mcp
```

2. Open your Claude Desktop config file:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

3. Add the AltFinance server:

```json
{
  "mcpServers": {
    "altfinance": {
      "command": "altfinance-mcp",
      "env": {
        "ALTFINANCE_API_KEY": "<YOUR_KEY_HERE>",
        "ALTFINANCE_API_URL": "https://api.altfndata.com"
      }
    }
  }
}
```

   To run without installing, set `"command": "uvx"` and `"args": ["altfinance-mcp"]` instead of `"command": "altfinance-mcp"` (requires [uv](https://docs.astral.sh/uv/)).

4. Restart Claude Desktop.

5. Try asking Claude:
   - *"What tables are available in AltFinance?"*
   - *"Show me the top 10 most expensive Rolex watches sold at auction"*
   - *"Give me market stats for Hermès Birkin bags"*
   - *"How have Patek Philippe prices moved by year?"*
   - *"Price-check a Rolex Daytona 116500"*
   - *"Search the whole market for a Burma ruby ring over $50k"*

### The 9 MCP tools

The MCP server exposes 9 read-only tools (each annotated `readOnlyHint` + `openWorldHint`):

| Tool | What it does |
|------|--------------|
| `list_tables` | Lists the 20 tables with live descriptions and column counts |
| `get_table_schema` | Column names and types for one table |
| `query_table` | Filter, sort, select fields, paginate (max 500 rows/request) |
| `market_stats` | Count, median, 25th/75th percentiles, average, min/max, date span, top vendors |
| `price_trend` | Realized prices over time, bucketed by year/quarter/month |
| `price_check` | Fair-value range for one item from comparable sales (handbags, watches, cars) |
| `search` | Whole-market keyword search across every category at once |
| `market_index` | Precomputed model-level price index for a brand or model (handbags, watches, cars) |
| `list_alerts` | Read-only view of price alerts, or guidance on enabling them in the app |

**Price alerts are read-only over MCP.** Alerts belong to a signed-in AltFinance account, not to an API key, so the MCP cannot create or enable them; `list_alerts` reports fired alerts when reachable, otherwise returns setup guidance. Some responses may append one short "💡" feature or plan suggestion at a real tier boundary, never for unlimited or comp accounts, and never changing the data returned.

**Note:** `market_stats` medians and percentiles depend on the API percentile update (already deployed); the 9 tools depend on the MCP redeploy. This doc describes the intended live state.

### Claude Code

```bash
export ALTFINANCE_API_KEY="<YOUR_KEY_HERE>"
claude mcp add altfinance -- altfinance-mcp
```

---

## Option 2: Direct API Usage

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/health` | Health check |
| GET | `/v1/tables` | List available tables |
| GET | `/v1/tables/{name}/schema` | Get column names and types |
| POST | `/v1/tables/{name}/query` | Query with filters, sorting, pagination |
| GET | `/v1/tables/{name}/query` | Simple query via URL params |

### Authentication

Include your API key in the `X-API-Key` header:

```
X-API-Key: <YOUR_KEY_HERE>
```

### Interactive Docs

Visit **https://api.altfndata.com/docs** for the Swagger UI — you can test all endpoints directly in the browser.

---

## Quick Examples

### List available tables

```bash
curl -H "X-API-Key: YOUR_KEY" https://api.altfndata.com/v1/tables
```

### Get table schema

```bash
curl -H "X-API-Key: YOUR_KEY" https://api.altfndata.com/v1/tables/watches/schema
```

### Query watches (simple GET)

```bash
curl -H "X-API-Key: YOUR_KEY" \
  "https://api.altfndata.com/v1/tables/watches/query?designer=Rolex&limit=5&sort=usd_price_decimal:desc"
```

### Query watches (POST with filters)

```bash
curl -X POST https://api.altfndata.com/v1/tables/watches/query \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": ["item_title", "vendor", "usd_price_decimal", "sale_date"],
    "filters": [
      {"field": "designer", "op": "eq", "value": "Rolex"},
      {"field": "usd_price_decimal", "op": "gte", "value": "50000"}
    ],
    "sort": [{"field": "usd_price_decimal", "direction": "desc"}],
    "limit": 20
  }'
```

### Python example

```python
import requests

API_KEY = "YOUR_KEY"
BASE_URL = "https://api.altfndata.com"
HEADERS = {"X-API-Key": API_KEY}

# List tables
tables = requests.get(f"{BASE_URL}/v1/tables", headers=HEADERS).json()
print(tables)

# Query Hermès handbags over $10K
resp = requests.post(
    f"{BASE_URL}/v1/tables/handbags/query",
    headers={**HEADERS, "Content-Type": "application/json"},
    json={
        "fields": ["item_title", "vendor", "usd_price_decimal", "sale_date"],
        "filters": [
            {"field": "designer", "op": "like", "value": "Hermes"},
            {"field": "usd_price_decimal", "op": "gte", "value": "10000"},
        ],
        "sort": [{"field": "usd_price_decimal", "direction": "desc"}],
        "limit": 10,
    },
)
print(resp.json())
```

---

## Available Tables

20 tables. Call `list_tables` (or `GET /v1/tables`) for the live set with current column counts.

| Table | Description |
|-------|-------------|
| `watches` | Luxury watch auction results |
| `handbags` | Luxury handbag auction results |
| `jewelry` | Finished jewelry, mounted pieces set with gemstones |
| `gems` | Loose, unmounted gemstones (single stones and parcels). Use for gemstone valuations, not `jewelry` |
| `automobile` | Collector car auction results |
| `motorcycle` | Collector motorcycle auction results |
| `aircraft` | Aircraft auction results |
| `wine_whisky` | Wine and whisky auction results |
| `works_of_art` | Works of art with stone/jewelry relevance |
| `fine_art` | Fine art across all movements and periods |
| `design` | Design and decorative arts: furniture, lighting, glass, ceramics |
| `fashion` | Fashion and couture: clothing and accessories |
| `shoes` | Footwear: designer shoes and collectible sneakers |
| `automobilia` | Automotive memorabilia, parts, signage, models |
| `books` | Books, manuscripts, maps and printed material |
| `coins` | Numismatic coin auction results |
| `other_automobile` | Other vehicles: boats, tractors, trucks, buses and military vehicles |
| `perfume` | Perfume and collectible fragrance bottles and flacons |
| `accessories` | Fashion accessories: belts, scarves, cufflinks, brooches and sunglasses |
| `musical_instruments` | Musical instruments: guitars, violin family, pianos, woodwind, brass, percussion |

**`gems` vs `jewelry`:** `gems` = LOOSE, unmounted stones (the right table for a gemstone valuation); `jewelry` = FINISHED, mounted pieces set with stones.

---

## Filter Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `eq` | Equals | `{"field": "designer", "op": "eq", "value": "Rolex"}` |
| `neq` | Not equals | `{"field": "status", "op": "neq", "value": "withdrawn"}` |
| `gt` | Greater than | `{"field": "usd_price_decimal", "op": "gt", "value": "100000"}` |
| `gte` | Greater or equal | `{"field": "carats", "op": "gte", "value": "5"}` |
| `lt` | Less than | `{"field": "usd_price_decimal", "op": "lt", "value": "1000"}` |
| `lte` | Less or equal | Same as above |
| `like` | Contains (substring) | `{"field": "item_title", "op": "like", "value": "Daytona"}` |
| `in` | In list | `{"field": "vendor", "op": "in", "value": ["Christie's", "Sotheby's"]}` |
| `not_in` | Not in list | Same format as `in` |
| `is_null` | Is null | `{"field": "usd_price_decimal", "op": "is_null"}` |
| `is_not_null` | Is not null | `{"field": "usd_price_decimal", "op": "is_not_null"}` |

---

## Rate Limits

Your API key has the following limits:

| Limit | Value |
|-------|-------|
| Requests per minute | *See your welcome email* |
| Rows per day | *See your welcome email* |
| Max rows per request | *See your welcome email* |

If you hit a rate limit, you'll receive a `429 Too Many Requests` response. Wait and retry.

---

## Support

- Email: support@altfndata.com
- Issues: Report bugs or request features via email

---

*AltFinance Data — The cross-category luxury auction data API.*
