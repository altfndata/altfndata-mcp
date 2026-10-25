"""Let /token and /revoke accept client_secret_basic without client_id in the body.

RFC 6749 section 2.3.1 lets a confidential client send its credentials only in
the ``Authorization: Basic`` header. The MCP SDK (1.26 to 1.30) still reads
``client_id`` from the form body and rejects the request with "Missing
client_id" when it is absent. Some clients (enterprise connectors such as
Gemini Enterprise) send the header only, so this middleware copies the client
id from the header into the form body when the body lacks one. The SDK still
checks the secret and that both ids match.
"""

import base64
import binascii
from urllib.parse import parse_qs, quote, unquote

_PATHS = {"/token", "/revoke"}


def _basic_client_id(headers: list[tuple[bytes, bytes]]) -> str | None:
    for name, value in headers:
        if name.lower() == b"authorization" and value[:6].lower() == b"basic ":
            try:
                decoded = base64.b64decode(value[6:].strip()).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                return None
            if ":" not in decoded:
                return None
            return unquote(decoded.split(":", 1)[0]) or None
    return None


class BasicAuthClientIdShim:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") not in _PATHS
        ):
            return await self.app(scope, receive, send)
        client_id = _basic_client_id(scope.get("headers", []))
        if client_id is None:
            return await self.app(scope, receive, send)

        # Buffer the (small) form body, add client_id if missing, replay it
        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                return await self.app(scope, _replay([message], receive), send)
            body += message.get("body", b"")
            more = message.get("more_body", False)

        if "client_id" not in parse_qs(body.decode("latin-1")):
            sep = b"&" if body else b""
            body += sep + b"client_id=" + quote(client_id, safe="").encode()
            scope = dict(scope)
            scope["headers"] = [
                (k, v) for k, v in scope["headers"] if k.lower() != b"content-length"
            ] + [(b"content-length", str(len(body)).encode())]

        return await self.app(
            scope, _replay([{"type": "http.request", "body": body, "more_body": False}], receive), send
        )


def _replay(messages, upstream):
    """Serve the buffered messages, then hand back to the real receive."""
    queue = list(messages)

    async def receive():
        if queue:
            return queue.pop(0)
        return await upstream()

    return receive
