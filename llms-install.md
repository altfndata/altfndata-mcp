# Installing the ALT/FNDATA MCP server

ALT/FNDATA gives your AI assistant read-only access to luxury & collectibles
auction data across 20 categories (watches, jewelry, cars, art, wine and more)
from 100+ auction houses: search, market statistics, price trends, model price
indices, and single-item valuations — every result carrying a source link.

## Requirements
- Python 3.10+ (or `uv` / `uvx`).
- An ALT/FNDATA API key (paid plan — there is no free tier). Get one at
  https://app.altfndata.com/#/mcp .

## Install (stdio, local)
No build step. Run with `uvx` (recommended, no install) or install via pip.

Add this to your MCP settings (for Cline: `cline_mcp_settings.json`):

```json
{
  "mcpServers": {
    "altfinance": {
      "command": "uvx",
      "args": ["altfinance-mcp"],
      "env": {
        "ALTFINANCE_API_KEY": "YOUR_ALTFNDATA_API_KEY"
      }
    }
  }
}
```

Prefer pip instead of uvx? Run `pip install altfinance-mcp`, then set
`"command": "altfinance-mcp"` and drop the `args` line.

Replace `YOUR_ALTFNDATA_API_KEY` with the key from app.altfndata.com, then
restart the client.

## Verify it works
Ask the assistant:
- "What data tables does ALT/FNDATA have?" → calls `list_tables`
- "Price-check a Rolex Daytona 116500LN" → calls `price_check`
- "Market stats for Hermès handbags" → calls `market_stats`

## Tools (all read-only)
`list_tables`, `get_table_schema`, `query_table`, `search`, `market_stats`,
`price_trend`, `price_check`, `market_index`, `list_alerts`. No tool writes,
modifies, or transacts anything.

## Notes
- A valid paid ALT/FNDATA API key is required (no free tier). Without it the
  tools return an authentication error.
- A hosted OAuth connector also exists at `https://mcp.altfndata.com/mcp` for
  clients that support remote MCP servers; for a local Cline setup use the
  stdio config above.
