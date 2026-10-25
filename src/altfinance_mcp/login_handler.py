"""Login page handler for the AltFinance OAuth flow.

Provides a simple HTML form where users enter their AltFinance API key
during the OAuth authorization flow. The key is validated against the
AltFinance API, and on success the user is redirected back to Claude
with an authorization code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from altfinance_mcp.oauth_provider import AltFinanceOAuthProvider

LOGIN_PAGE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Connect to ALT/FNDATA</title>
  <link rel="icon" href="/favicon.ico" type="image/png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', -apple-system, sans-serif;
      background: #0a0b0d;
      color: #f4f4f5;
      line-height: 1.6;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem;
    }}
    .auth-container {{
      position: relative;
      width: 100%;
      max-width: 480px;
    }}
    .auth-header {{
      text-align: center;
      margin-bottom: 2.5rem;
    }}
    .auth-logo {{
      height: 48px;
      margin-bottom: 1rem;
    }}
    .auth-tagline {{
      color: #71717a;
      font-size: 0.9rem;
    }}
    .auth-card {{
      background: #15171e;
      border: 1px solid #2a2d38;
      border-radius: 16px;
      padding: 2.5rem;
      text-align: center;
    }}
    .auth-title {{
      font-size: 1.5rem;
      font-weight: 600;
      margin-bottom: 0.5rem;
      color: #f4f4f5;
    }}
    .auth-subtitle {{
      color: #a1a1aa;
      font-size: 0.95rem;
      margin-bottom: 1.5rem;
      line-height: 1.6;
    }}
    .form-group {{
      text-align: left;
      margin-bottom: 0.25rem;
    }}
    label {{
      display: block;
      font-size: 0.875rem;
      font-weight: 500;
      margin-bottom: 0.5rem;
      color: #a1a1aa;
    }}
    input[type="password"] {{
      width: 100%;
      padding: 0.75rem 1rem;
      background: #0a0b0d;
      border: 1px solid #2a2d38;
      border-radius: 8px;
      color: #f4f4f5;
      font-size: 0.95rem;
      font-family: 'JetBrains Mono', 'SF Mono', monospace;
      outline: none;
      transition: border-color 0.2s;
    }}
    input[type="password"]:focus {{
      border-color: #0049ff;
    }}
    input[type="password"]::placeholder {{
      color: #3a3d48;
    }}
    .error {{
      background: rgba(239, 68, 68, 0.1);
      border: 1px solid rgba(239, 68, 68, 0.3);
      color: #fca5a5;
      padding: 0.75rem 1rem;
      border-radius: 8px;
      font-size: 0.875rem;
      margin-bottom: 1rem;
      text-align: left;
    }}
    .auth-btn {{
      width: 100%;
      padding: 0.875rem 1.5rem;
      background: #0049FF;
      color: white;
      border: none;
      border-radius: 8px;
      font-size: 0.95rem;
      font-weight: 600;
      font-family: inherit;
      cursor: pointer;
      margin-top: 1rem;
      transition: background 0.2s, transform 0.1s;
    }}
    .auth-btn:hover {{
      background: #0039cc;
    }}
    .auth-btn:active {{
      transform: scale(0.98);
    }}
    .auth-footer {{
      text-align: center;
      margin-top: 1.5rem;
      padding-top: 1.5rem;
      border-top: 1px solid #2a2d38;
      color: #71717a;
      font-size: 0.875rem;
    }}
    .auth-footer a {{
      color: #0049ff;
      text-decoration: none;
      font-weight: 600;
    }}
    .auth-footer a:hover {{
      text-decoration: underline;
    }}
  </style>
</head>
<body>
  <div class="auth-container">
    <div class="auth-header">
      <img class="auth-logo" src="https://app.altfndata.com/images/AltFndata_Logo_White_main.png" alt="ALT/FNDATA" style="height:44px;width:auto;display:inline-block">
      <p class="auth-tagline">Institutional-Grade Alternative Market Intelligence</p>
    </div>
    <div class="auth-card">
      <h2 class="auth-title">Connect your AI assistant</h2>
      <p class="auth-subtitle">Enter your ALT/FNDATA API key to connect your account and start querying market data from your AI assistant.</p>
      {error_html}
      <form method="POST" action="/login">
        <input type="hidden" name="session" value="{session_id}">
        <div class="form-group">
          <label for="api_key">API Key</label>
          <input type="password" id="api_key" name="api_key"
                 placeholder="afi_live_..." autocomplete="off" required>
        </div>
        <button type="submit" class="auth-btn">Connect</button>
      </form>
      <div class="auth-footer">
        Don't have an API key? <a href="https://app.altfndata.com/#/mcp" target="_blank">Get your API key</a>
      </div>
    </div>
  </div>
</body>
</html>
"""


def register_login_routes(
    mcp: FastMCP, oauth_provider: AltFinanceOAuthProvider
) -> None:
    """Register the /login GET and POST routes on the FastMCP server."""

    @mcp.custom_route("/login", methods=["GET"])
    async def login_get(request: Request) -> Response:
        session_id = request.query_params.get("session", "")
        pending = await oauth_provider.get_pending_auth(session_id)
        if not pending:
            return HTMLResponse(
                "<h1>Invalid session</h1><p>This authorization link has expired. "
                "Please try connecting again from your AI assistant.</p>",
                status_code=400,
            )
        return HTMLResponse(
            LOGIN_PAGE_HTML.format(session_id=session_id, error_html="")
        )

    @mcp.custom_route("/login", methods=["POST"])
    async def login_post(request: Request) -> Response:
        form = await request.form()
        session_id = str(form.get("session", ""))
        api_key = str(form.get("api_key", "")).strip()

        if not session_id or not api_key:
            return HTMLResponse(
                LOGIN_PAGE_HTML.format(
                    session_id=session_id,
                    error_html='<div class="error">Please enter your API key.</div>',
                ),
                status_code=400,
            )

        redirect_url, error = await oauth_provider.complete_authorization(
            session_id, api_key
        )

        if error:
            return HTMLResponse(
                LOGIN_PAGE_HTML.format(
                    session_id=session_id,
                    error_html=f'<div class="error">{error}</div>',
                )
            )

        return RedirectResponse(url=redirect_url, status_code=302)
