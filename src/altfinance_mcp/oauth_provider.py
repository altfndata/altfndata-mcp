"""OAuth 2.0 Authorization Server Provider for AltFinance MCP.

Implements the OAuthAuthorizationServerProvider protocol from the MCP SDK
to handle Dynamic Client Registration, authorization, and token exchange.

Users authenticate by entering their AltFinance API key during the OAuth
authorization flow. The provider maps OAuth access tokens to API keys
so tool handlers can make authenticated requests to the AltFinance API.

State (clients, login sessions, codes, tokens) lives in an ``OAuthStore``:
in memory by default, or DynamoDB + KMS for the hosted connector so that
connections survive restarts and redeploys (see ``oauth_store.py``).
"""

import asyncio
import logging
import secrets
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from altfinance_mcp.oauth_store import (
    ACCESS,
    CLIENT,
    CODE,
    PENDING,
    REFRESH,
    MemoryOAuthStore,
    OAuthStore,
)

# Token lifetimes
ACCESS_TOKEN_EXPIRY = 3600  # 1 hour
REFRESH_TOKEN_EXPIRY = 30 * 24 * 3600  # 30 days
AUTH_CODE_EXPIRY = 300  # 5 minutes
PENDING_AUTH_EXPIRY = 900  # 15 minutes to enter the API key on the login page

# Prune the in-process access-token cache once it grows past this
_CACHE_PRUNE_AT = 10_000


class AltFinanceOAuthProvider:
    """OAuth provider that authenticates users via their AltFinance API key.

    During the /authorize flow, users are redirected to a login page where
    they enter their API key. The provider validates the key, issues OAuth
    tokens, and maintains a mapping from tokens to API keys.
    """

    def __init__(self, api_url: str, login_url: str, store: Optional[OAuthStore] = None):
        self.api_url = api_url
        self.login_url = login_url  # Base URL for the login page
        self.store: OAuthStore = store if store is not None else MemoryOAuthStore()

        # Access token -> (AccessToken, API key). Saves a store read (and a
        # KMS decrypt) on every request; the store stays the source of truth.
        self._access_cache: dict[str, tuple[AccessToken, str]] = {}

    async def _run(self, fn, *args, **kwargs):
        """Run a (possibly blocking) store call off the event loop."""
        if isinstance(self.store, MemoryOAuthStore):
            return fn(*args, **kwargs)
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _cache_access(self, access: AccessToken, api_key: str) -> None:
        if len(self._access_cache) >= _CACHE_PRUNE_AT:
            now = time.time()
            for tok, (a, _) in list(self._access_cache.items()):
                if a.expires_at and a.expires_at < now:
                    del self._access_cache[tok]
        self._access_cache[access.token] = (access, api_key)

    # ── Dynamic Client Registration ──────────────────────────────

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        record = await self._run(self.store.get, CLIENT, client_id)
        if record is None:
            return None
        data, client_secret = record
        return OAuthClientInformationFull.model_validate({**data, "client_secret": client_secret})

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        data = client_info.model_dump(mode="json", exclude={"client_secret"})
        await self._run(
            self.store.put, CLIENT, client_info.client_id, data,
            secret=client_info.client_secret,
        )

    # ── Authorization ────────────────────────────────────────────

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Start the authorization flow by redirecting to the login page.

        Stores the authorization params in a pending session and returns
        the URL of the login page with the session ID.
        """
        session_id = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + PENDING_AUTH_EXPIRY
        await self._run(
            self.store.put, PENDING, session_id,
            {
                "client_id": client.client_id,
                "params": params.model_dump(mode="json"),
                "expires_at": expires_at,
            },
            expires_at=expires_at,
        )
        return f"{self.login_url}?session={session_id}"

    async def get_pending_auth(self, session_id: str) -> Optional[dict]:
        """Retrieve a pending authorization session."""
        if not session_id:
            return None
        record = await self._run(self.store.get, PENDING, session_id)
        if record is None:
            return None
        data, _ = record
        return {
            "client_id": data["client_id"],
            "params": AuthorizationParams.model_validate(data["params"]),
        }

    async def complete_authorization(
        self, session_id: str, api_key: str
    ) -> tuple[str, str]:
        """Complete authorization after user enters a valid API key.

        Returns (redirect_url, error_message). On success, redirect_url
        contains the callback URL with the auth code; error_message is empty.
        On failure, redirect_url is empty; error_message describes the error.
        """
        record = await self._run(self.store.pop, PENDING, session_id) if session_id else None
        if not record:
            return "", "Invalid or expired session."
        pending, _ = record

        # Validate the API key against the AltFinance API
        valid = await self._validate_api_key(api_key)
        if not valid:
            # Put the session back so user can retry
            await self._run(
                self.store.put, PENDING, session_id, pending,
                expires_at=pending["expires_at"],
            )
            return "", "Invalid API key. Please check and try again."

        params = AuthorizationParams.model_validate(pending["params"])
        client_id: str = pending["client_id"]

        # Generate authorization code
        code = secrets.token_urlsafe(32)
        now = time.time()

        code_obj = AuthorizationCode(
            code=code,
            scopes=params.scopes or ["read"],
            expires_at=now + AUTH_CODE_EXPIRY,
            client_id=client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        await self._run(
            self.store.put, CODE, code, code_obj.model_dump(mode="json", exclude={"code"}),
            secret=api_key, expires_at=int(code_obj.expires_at) + 1,
        )

        # Build redirect URL back to the client
        redirect_url = construct_redirect_uri(
            str(params.redirect_uri),
            code=code,
            state=params.state,
        )
        return redirect_url, ""

    async def _validate_api_key(self, api_key: str) -> bool:
        """Validate an API key by making a test request to the AltFinance API."""
        masked = api_key[:12] + "..." if len(api_key) > 12 else api_key
        logger.info(f"Validating API key {masked} against {self.api_url}/v1/tables")
        try:
            async with httpx.AsyncClient(
                base_url=self.api_url,
                headers={"X-API-Key": api_key},
                timeout=15.0,
            ) as client:
                resp = await client.get("/v1/tables")
                logger.info(f"API key validation response: {resp.status_code}")
                if resp.status_code != 200:
                    logger.warning(f"API key validation failed: HTTP {resp.status_code} - {resp.text[:200]}")
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"API key validation error: {type(e).__name__}: {e}")
            return False

    # ── Token issuance ───────────────────────────────────────────

    async def _issue_tokens(
        self,
        client_id: str,
        scopes: list[str],
        resource: Optional[str],
        api_key: str,
    ) -> OAuthToken:
        now = int(time.time())

        access_token = AccessToken(
            token=secrets.token_urlsafe(32),
            client_id=client_id,
            scopes=scopes,
            expires_at=now + ACCESS_TOKEN_EXPIRY,
            resource=resource,
        )
        refresh_token = RefreshToken(
            token=secrets.token_urlsafe(32),
            client_id=client_id,
            scopes=scopes,
            expires_at=now + REFRESH_TOKEN_EXPIRY,
        )
        await self._run(
            self.store.put, ACCESS, access_token.token,
            access_token.model_dump(mode="json", exclude={"token"}),
            secret=api_key, expires_at=access_token.expires_at,
        )
        # The refresh token carries the API key so it can mint new access tokens
        refresh_data = refresh_token.model_dump(mode="json", exclude={"token"})
        refresh_data["resource"] = resource
        await self._run(
            self.store.put, REFRESH, refresh_token.token, refresh_data,
            secret=api_key, expires_at=refresh_token.expires_at,
        )
        self._cache_access(access_token, api_key)

        return OAuthToken(
            access_token=access_token.token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_EXPIRY,
            scope=" ".join(scopes),
            refresh_token=refresh_token.token,
        )

    # ── Authorization Code Exchange ──────────────────────────────

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[AuthorizationCode]:
        record = await self._run(self.store.get, CODE, authorization_code)
        if record is None:
            return None
        code_obj = AuthorizationCode.model_validate({**record[0], "code": authorization_code})
        if code_obj.client_id != client.client_id or code_obj.expires_at < time.time():
            return None
        return code_obj

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # Consume the auth code (single use, atomic across processes)
        record = await self._run(self.store.pop, CODE, authorization_code.code)
        api_key = record[1] if record else None
        if not api_key:
            raise TokenError(error="invalid_grant", error_description="Authorization code not found.")

        return await self._issue_tokens(
            client.client_id, authorization_code.scopes, authorization_code.resource, api_key
        )

    # ── Refresh Token Exchange ───────────────────────────────────

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[RefreshToken]:
        record = await self._run(self.store.get, REFRESH, refresh_token)
        if record is None:
            return None
        data = {k: v for k, v in record[0].items() if k != "resource"}
        token_obj = RefreshToken.model_validate({**data, "token": refresh_token})
        if token_obj.client_id != client.client_id:
            return None
        if token_obj.expires_at and token_obj.expires_at < int(time.time()):
            return None
        return token_obj

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Consume the old refresh token (rotation); a replay finds nothing
        record = await self._run(self.store.pop, REFRESH, refresh_token.token)
        api_key = record[1] if record else None
        if not api_key:
            raise TokenError(error="invalid_grant", error_description="Refresh token not found.")

        effective_scopes = scopes if scopes else refresh_token.scopes
        return await self._issue_tokens(
            client.client_id, effective_scopes, record[0].get("resource"), api_key
        )

    # ── Token Verification ───────────────────────────────────────

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        now = int(time.time())
        cached = self._access_cache.get(token)
        if cached is None:
            record = await self._run(self.store.get, ACCESS, token)
            if record is None:
                return None
            data, api_key = record
            access = AccessToken.model_validate({**data, "token": token})
            if not api_key:
                return None
            self._cache_access(access, api_key)
            cached = (access, api_key)
        access = cached[0]
        if access.expires_at and access.expires_at < now:
            # Expired - clean up
            self._access_cache.pop(token, None)
            await self._run(self.store.delete, ACCESS, token)
            return None
        return access

    # ── Token Revocation ─────────────────────────────────────────

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        token_str = token.token
        self._access_cache.pop(token_str, None)
        await self._run(self.store.delete, ACCESS, token_str)
        await self._run(self.store.delete, REFRESH, token_str)

    # ── Helper for tool handlers ─────────────────────────────────

    def get_api_key_for_token(self, token_str: str) -> Optional[str]:
        """Resolve an AltFinance API key from an OAuth access token string.

        The auth middleware has already called ``load_access_token`` for this
        request, so the key is normally in the cache.
        """
        cached = self._access_cache.get(token_str)
        if cached is not None:
            return cached[1]
        record = self.store.get(ACCESS, token_str)
        return record[1] if record else None
