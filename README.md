<!-- mcp-name: com.altfndata/altfinance-mcp -->

# ALT/FNDATA MCP Server

Connect your AI assistant to luxury and collectibles auction data. Query watches, jewelry, loose gemstones, handbags, cars, motorcycles, aircraft, wine and whisky, fine art, works of art, design, fashion, shoes, automobilia, books, coins, perfume, accessories, musical instruments and other vehicles from 100+ global auction houses, in plain language.

It uses the open Model Context Protocol (MCP), so it works with Claude, ChatGPT, Gemini, Perplexity and other assistants and developer tools that support MCP servers.

## Quick Start

### 1. Get an API Key

Get your key from [API Key & MCP](https://app.altfndata.com/#/mcp) in the ALT/FNDATA app.

### 2a. Connect the hosted server (no install)

In any assistant that supports remote MCP servers (often called custom connectors), add a connector with this URL:

```
https://mcp.altfndata.com/mcp
```

Choose OAuth if you are asked for an authentication method. A sign-in page then asks for your ALT/FNDATA API key.

- **Claude:** Settings → Connectors → add a custom connector.
- **ChatGPT:** add it as a custom connector (developer mode). ChatGPT only connects to hosted servers, so use this option.
- **Perplexity:** Settings → Connectors → add a custom connector with the URL above.
- **Gemini app:** Settings → Connected Apps → add a custom app with the URL above (personal Google accounts).
- **Gemini Enterprise:** an admin adds ALT/FNDATA once for the organisation. See [Gemini Enterprise set-up](#gemini-enterprise-admin-set-up) below.

Menu names and plan availability are set by each assistant and change over time; check its help pages if the steps differ.

#### Gemini Enterprise (admin set-up)

Gemini Enterprise connects through a Custom MCP Server data store, which an admin sets up once for the organisation.

1. Register a client. The response contains a `client_id` and a `client_secret`. The secret is shown only once, so store it safely.

   ```bash
   curl -X POST https://mcp.altfndata.com/register \
     -H "Content-Type: application/json" \
     -d '{"client_name": "Gemini Enterprise (your organisation)",
          "redirect_uris": ["https://vertexaisearch.cloud.google.com/oauth-redirect"],
          "token_endpoint_auth_method": "client_secret_post",
          "grant_types": ["authorization_code", "refresh_token"],
          "response_types": ["code"],
          "scope": "read"}'
   ```

2. In the Gemini Enterprise console, add a Custom MCP Server data store with these values:

   | Field | Value |
   |---|---|
   | MCP Server URL | `https://mcp.altfndata.com/mcp` |
   | Authorization URL | `https://mcp.altfndata.com/authorize` |
   | Token URL | `https://mcp.altfndata.com/token` |
   | Client ID | `client_id` from step 1 |
   | Client Secret | `client_secret` from step 1 |
   | Scopes | `read` |
   | Enable PKCE | ticked |

3. Each user then connects from Gemini and signs in with their own ALT/FNDATA API key. The client ID and secret only identify your organisation's Gemini Enterprise; they give no access to data on their own.

Google's guide to setting up a custom MCP server describes the console screens.

### 2b. Or run it locally

For desktop apps and developer tools that launch MCP servers on your machine, either install it with pip:

```bash
pip install altfinance-mcp
```

or run it with no install using [uv](https://docs.astral.sh/uv/) — point the client's `command` at `uvx` with `altfinance-mcp` as the argument (see the uvx config example below):

```bash
uvx altfinance-mcp
```

Most tools take a configuration in this shape; add it to the tool's MCP settings and restart it.

**Example, Claude Desktop:** the config file is `%APPDATA%\Claude\claude_desktop_config.json` on Windows and `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS.

```json
{
  "mcpServers": {
    "altfinance": {
      "command": "altfinance-mcp",
      "env": {
        "ALTFINANCE_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

With `uvx` (no `pip install` needed), use `"command": "uvx"` and pass the package as an argument:

```json
{
  "mcpServers": {
    "altfinance": {
      "command": "uvx",
      "args": ["altfinance-mcp"],
      "env": {
        "ALTFINANCE_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

**Example, Claude Code:**

```bash
claude mcp add altfinance -- altfinance-mcp
```

Set the env var before launching:
```bash
export ALTFINANCE_API_KEY="your-api-key-here"
```

## What You Can Ask

Once connected, ask your assistant questions like:

- "What tables are available in the ALT/FNDATA database?"
- "Show me the schema for the watches table"
- "Find the top 10 most expensive Rolex watches sold after 2020"
- "How many Hermes handbags were sold by Christie's?"
- "Give me market stats for Patek Philippe watches sold at Phillips"
- "How have Hermes Birkin prices moved over the last five years?"
- "Price-check a Rolex Daytona 116500 white dial"
- "Search the whole market for a Burma ruby ring over $50k"
- "What loose sapphires have sold at auction?" (uses `gems`, not `jewelry`)

## Available Tools

All 9 tools are **read-only** and annotated with `readOnlyHint: true`. No data is modified by any tool.

| Tool | Description |
|------|-------------|
| `list_tables` | Lists the 20 available tables with live descriptions and column counts |
| `get_table_schema` | Shows column names and types for one table |
| `query_table` | Queries a table with filters, sorting, field selection, and pagination |
| `market_stats` | Realized-price summary for a table or filtered segment: count of sales, median, 25th/75th percentiles, average, min/max, sale-date span, and top vendors by volume |
| `price_trend` | How realized prices moved over time, bucketed by year, quarter, or month (count, median, average per period) |
| `price_check` | Fair-value range for a single item from comparable sales, with source links. Live comp categories: handbags, watches, cars |
| `search` | Whole-market keyword search across every category at once, merged by realized price. With no category it fans out across all 20 tables |
| `market_index` | Precomputed model-level price index (low / 25th / median / 75th / high, sample size, trend) for a brand or model. Covered categories: handbags, watches, cars |
| `list_alerts` | Read-only view of price alerts, or guidance on enabling them. See "Price alerts are read-only" below |

Every tool carries `readOnlyHint` and `openWorldHint`.

### Price alerts are read-only

Price alerts belong to a signed-in ALT/FNDATA account (Cognito login), not to an API key. The MCP authenticates with an API key only, so it **cannot create or enable alerts**, and the alerts feed itself is not reachable for an API-key caller. `list_alerts` therefore either reports fired alerts (when a session makes the feed reachable) or returns guidance on setting alerts up in the app at [app.altfndata.com](https://app.altfndata.com). Alert allowance by plan: free 0, registered 1, collector 10, pro 100, included with Membership.

### Feature and plan suggestions

Some tool responses may append a single short "💡" line suggesting a complementary ALT/FNDATA product or a plan upgrade. This happens at most once per response, only at a genuine tier boundary (a table your plan does not include, or an exhausted row quota) or as a relevant feature tip, and never for unlimited or comp accounts. It never changes the data returned.

### Query Capabilities

- **Filter** by any column using operators: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `like`, `in`, `not_in`, `is_null`, `is_not_null`
- **Sort** by any column, ascending or descending
- **Select** specific fields to return
- **Paginate** with limit/offset (max 500 rows per request)

## Data Coverage

The database spans 20 tables. Call `list_tables` for the live set with current column counts.

| Table | Description |
|-------|-------------|
| `watches` | Luxury watch auction results |
| `handbags` | Luxury handbag auction results |
| `jewelry` | Finished jewelry, mounted pieces (rings, necklaces, bracelets, earrings) set with gemstones |
| `gems` | Loose, unmounted gemstones (single stones and parcels). Use this for gemstone valuations, not `jewelry` |
| `automobile` | Collector car auction results |
| `motorcycle` | Collector motorcycle auction results |
| `aircraft` | Aircraft auction results |
| `wine_whisky` | Wine and whisky auction results |
| `works_of_art` | Works of art with stone/jewelry relevance (jade, jadeite, diamond-set, etc.) |
| `fine_art` | Fine art auction results across all movements and periods |
| `design` | Design and decorative arts: furniture, lighting, glass, ceramics, studio/industrial design |
| `fashion` | Fashion and couture: clothing and accessories (not handbags or shoes, which have their own tables) |
| `shoes` | Footwear: designer shoes and collectible sneakers |
| `automobilia` | Automotive memorabilia, parts, signage, models and related collectibles (not the cars themselves) |
| `books` | Books, manuscripts, maps and printed material |
| `coins` | Numismatic coin auction results |
| `other_automobile` | Other vehicles: boats, tractors, trucks, buses and military vehicles (not cars or motorcycles) |
| `perfume` | Perfume and collectible fragrance bottles and flacons |
| `accessories` | Fashion accessories: belts, scarves, cufflinks, brooches and sunglasses, including gem-set pieces |
| `musical_instruments` | Musical instruments: guitars, violin family, pianos and keyboards, woodwind, brass, percussion and amplifiers |

**`gems` vs `jewelry`:** `gems` holds LOOSE, unmounted stones (the right table for a gemstone valuation); `jewelry` holds FINISHED, mounted pieces set with stones. If one returns nothing, try the other.

Data sources include Christie's, Sotheby's, Phillips, Bonhams, Artcurial, Dorotheum, Heritage Auctions, and 100+ other auction houses worldwide.

## Hosted Server

The hosted server at `https://mcp.altfndata.com/mcp` (Quick Start 2a) is this package running in HTTP mode. Any MCP client that supports remote servers with OAuth can connect to it; the sign-in page asks for your ALT/FNDATA API key, so no local installation is needed.

### Self-Hosting the Remote Server

To run the MCP server in remote (HTTP) mode:

```bash
export ALTFINANCE_TRANSPORT=streamable-http
export ALTFINANCE_ISSUER_URL=https://mcp.altfndata.com
export ALTFINANCE_RESOURCE_URL=https://mcp.altfndata.com
python -m altfinance_mcp
```

Or with Docker:

```bash
docker build -t altfinance-mcp .
docker run -p 8000:8000 \
  -e ALTFINANCE_TRANSPORT=streamable-http \
  -e ALTFINANCE_ISSUER_URL=https://mcp.altfndata.com \
  -e ALTFINANCE_RESOURCE_URL=https://mcp.altfndata.com \
  altfinance-mcp
```

The remote server exposes:
- `POST/GET/DELETE /mcp` — MCP Streamable HTTP endpoint (authenticated)
- `GET /.well-known/oauth-authorization-server` — OAuth metadata
- `POST /register` — Dynamic Client Registration
- `GET /authorize` — OAuth authorization
- `POST /token` — Token exchange
- `GET/POST /login` — API key entry form

## Environment Variables

### Local (stdio) mode

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ALTFINANCE_API_KEY` | Yes | — | Your ALT/FNDATA API key |
| `ALTFINANCE_API_URL` | No | `https://api.altfndata.com` | API base URL |

### Remote (HTTP) mode

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ALTFINANCE_TRANSPORT` | Yes | `stdio` | Set to `streamable-http` |
| `ALTFINANCE_API_URL` | No | `https://api.altfndata.com` | API base URL |
| `ALTFINANCE_HOST` | No | `0.0.0.0` | HTTP listen address |
| `ALTFINANCE_PORT` | No | `8000` | HTTP listen port |
| `ALTFINANCE_ISSUER_URL` | No | `http://localhost:8000` | OAuth issuer URL (your public URL) |
| `ALTFINANCE_RESOURCE_URL` | No | Same as issuer | OAuth resource server URL |

## Privacy Policy

This MCP server connects to the ALT/FNDATA API (`api.altfndata.com`) to retrieve auction data. The following outlines our data practices:

- **Data collection**: The server sends your API key and query parameters (table names, filters, sort options) to the ALT/FNDATA API. No personal user data is collected beyond what is required for API authentication and query execution.
- **Usage and storage**: Query data is processed in real-time and returned to the MCP client. The server does not persist, cache, or store any query results or user data locally.
- **Third-party sharing**: Data is exchanged only between the MCP client and the ALT/FNDATA API (`api.altfndata.com`). No data is shared with any other third parties.
- **Data retention**: The server is stateless. No user data or query history is retained after a session ends.
- **Contact**: For privacy inquiries, contact [support@altfndata.com](mailto:support@altfndata.com).

Full privacy policy: [https://altfndata.com/privacy-policy/](https://altfndata.com/privacy-policy/)

## Support

- **Documentation**: [https://docs.altfndata.com](https://docs.altfndata.com)
- **Email**: [support@altfndata.com](mailto:support@altfndata.com)

## Requirements

- Python 3.10+
- An ALT/FNDATA API key

## License

MIT
