"""OAuth flow end to end, including a server restart between token and refresh.

Runs the real Starlette app (SDK auth routes + our login page) against
moto's DynamoDB and KMS. A "restart" builds a brand new provider, store and
app on the same table, so nothing survives in process memory.

Run: pip install -e ".[test]" && pytest tests
"""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from moto import mock_aws
from starlette.testclient import TestClient

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP

from altfinance_mcp import oauth_provider as op
from altfinance_mcp.basic_auth_shim import BasicAuthClientIdShim
from altfinance_mcp.login_handler import register_login_routes
from altfinance_mcp.oauth_store import DynamoOAuthStore, MemoryOAuthStore, store_from_env

ISSUER = "https://mcp.example.test"
GEMINI_REDIRECT = "https://vertexaisearch.cloud.google.com/oauth-redirect"
GOOD_KEY = "afi_live_" + "x" * 32
TABLE = "altfinance-mcp-oauth"
REGION = "us-east-1"


@pytest.fixture(autouse=True)
def _fake_api_key_check(monkeypatch):
    async def validate(self, api_key):
        return api_key == GOOD_KEY

    monkeypatch.setattr(op.AltFinanceOAuthProvider, "_validate_api_key", validate)


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with mock_aws():
        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        key_id = boto3.client("kms", region_name=REGION).create_key()["KeyMetadata"]["KeyId"]
        yield key_id


def make_app(store):
    """Mirror server.py's HTTP-mode wiring around a given store."""
    provider = op.AltFinanceOAuthProvider(
        api_url="https://api.example.test", login_url=f"{ISSUER}/login", store=store
    )
    mcp = FastMCP(
        name="test",
        host="0.0.0.0",  # as in production (server.py HOST)
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=ISSUER,
            resource_server_url=ISSUER,
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=["read"], default_scopes=["read"]
            ),
            revocation_options=RevocationOptions(enabled=True),
            required_scopes=["read"],
        ),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool()
    async def whoami() -> str:
        from mcp.server.auth.middleware.auth_context import get_access_token

        return provider.get_api_key_for_token(get_access_token().token) or ""

    register_login_routes(mcp, provider)
    app = mcp.streamable_http_app()
    app.add_middleware(BasicAuthClientIdShim)
    return app, provider


def dynamo_store(key_id):
    return DynamoOAuthStore(TABLE, key_id, REGION)


def register(client, auth_method):
    resp = client.post(
        "/register",
        json={
            "client_name": "Gemini Enterprise",
            "redirect_uris": [GEMINI_REDIRECT],
            "token_endpoint_auth_method": auth_method,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "read",
        },
    )
    assert resp.status_code == 201, resp.text
    info = resp.json()
    assert info["client_secret"]
    return info


def token_request(client, info, form, *, body_client_id=True):
    """POST /token authenticating the way the client registered."""
    form = dict(form)
    headers = {}
    if info["token_endpoint_auth_method"] == "client_secret_basic":
        creds = f"{info['client_id']}:{info['client_secret']}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(creds).decode()
        if body_client_id:
            form["client_id"] = info["client_id"]
    else:
        form["client_id"] = info["client_id"]
        form["client_secret"] = info["client_secret"]
    return client.post("/token", data=form, headers=headers)


def authorize_and_login(client, info):
    """Authorize with PKCE, submit the API key on the login page, get the code."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    resp = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": info["client_id"],
            "redirect_uri": GEMINI_REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "read",
            "state": "xyz",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    session = parse_qs(urlparse(resp.headers["location"]).query)["session"][0]

    assert client.get("/login", params={"session": session}).status_code == 200

    bad = client.post("/login", data={"session": session, "api_key": "afi_live_wrong"})
    assert "Invalid API key" in bad.text

    resp = client.post(
        "/login", data={"session": session, "api_key": GOOD_KEY}, follow_redirects=False
    )
    assert resp.status_code == 302, resp.text
    location = resp.headers["location"]
    assert location.startswith(GEMINI_REDIRECT)
    query = parse_qs(urlparse(location).query)
    assert query["state"] == ["xyz"]
    return query["code"][0], verifier


def call_whoami(client, access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    return client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "whoami", "arguments": {}}},
    )


@pytest.mark.parametrize("auth_method", ["client_secret_post", "client_secret_basic"])
def test_flow_survives_restart(aws, auth_method):
    # ── Process 1: register, authorize, login, token ──
    app, _ = make_app(dynamo_store(aws))
    with TestClient(app, base_url=ISSUER) as c:
        info = register(c, auth_method)
        code, verifier = authorize_and_login(c, info)
        resp = token_request(c, info, {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": GEMINI_REDIRECT, "code_verifier": verifier,
        })
        assert resp.status_code == 200, resp.text
        tokens = resp.json()
        assert call_whoami(c, tokens["access_token"]).status_code == 200

        # A code is single use
        again = token_request(c, info, {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": GEMINI_REDIRECT, "code_verifier": verifier,
        })
        assert again.status_code == 400

    # ── Process 2: a fresh provider, store and app on the same table ──
    app, provider = make_app(dynamo_store(aws))
    with TestClient(app, base_url=ISSUER) as c:
        # The access token issued before the restart still works, and still
        # resolves to the user's API key
        resp = call_whoami(c, tokens["access_token"])
        assert resp.status_code == 200, resp.text
        assert GOOD_KEY in resp.text

        # The client and its refresh token still work
        resp = token_request(c, info, {
            "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
        })
        assert resp.status_code == 200, resp.text
        new_tokens = resp.json()
        assert new_tokens["refresh_token"] != tokens["refresh_token"]
        assert call_whoami(c, new_tokens["access_token"]).status_code == 200

        # A rotated refresh token cannot be replayed
        replay = token_request(c, info, {
            "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
        })
        assert replay.status_code == 400

        # A wrong secret is rejected
        wrong = dict(info, client_secret="not-the-secret")
        bad = token_request(c, wrong, {
            "grant_type": "refresh_token", "refresh_token": new_tokens["refresh_token"],
        })
        assert bad.status_code == 401


def test_basic_auth_without_client_id_in_body(aws):
    """RFC 6749: Basic-auth clients may omit client_id from the form body."""
    app, _ = make_app(dynamo_store(aws))
    with TestClient(app, base_url=ISSUER) as c:
        info = register(c, "client_secret_basic")
        code, verifier = authorize_and_login(c, info)
        resp = token_request(c, info, {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": GEMINI_REDIRECT, "code_verifier": verifier,
        }, body_client_id=False)
        assert resp.status_code == 200, resp.text
        resp = token_request(c, info, {
            "grant_type": "refresh_token", "refresh_token": resp.json()["refresh_token"],
        }, body_client_id=False)
        assert resp.status_code == 200, resp.text


def test_nothing_sensitive_stored_in_clear(aws):
    app, _ = make_app(dynamo_store(aws))
    with TestClient(app, base_url=ISSUER) as c:
        info = register(c, "client_secret_post")
        code, verifier = authorize_and_login(c, info)
        tokens = token_request(c, info, {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": GEMINI_REDIRECT, "code_verifier": verifier,
        }).json()

    items = boto3.resource("dynamodb", region_name=REGION).Table(TABLE).scan()["Items"]
    dump = repr(items)
    for needle in (GOOD_KEY, info["client_secret"], tokens["access_token"],
                   tokens["refresh_token"], code):
        assert needle not in dump
    kinds = sorted({i["pk"].split("#")[0] for i in items})
    assert kinds == ["access", "client", "refresh"]
    assert all("ttl" in i for i in items if not i["pk"].startswith("client#"))


def test_ciphertext_bound_to_its_row(aws):
    store = dynamo_store(aws)
    store.put("refresh", "token-a", {"x": 1}, secret="key-a")
    store.put("refresh", "token-b", {"x": 2}, secret="key-b")
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    items = {i["data"]: i for i in table.scan()["Items"]}
    a, b = items['{"x": 1}'], items['{"x": 2}']
    table.put_item(Item={**b, "secret": a["secret"]})  # move A's ciphertext onto B
    assert store.get("refresh", "token-a") == ({"x": 1}, "key-a")
    with pytest.raises(Exception):
        store.get("refresh", "token-b")


def test_expired_rows_are_ignored_before_dynamodb_ttl_runs(aws):
    store = dynamo_store(aws)
    store.put("access", "old", {"x": 1}, secret="k", expires_at=1)
    assert store.get("access", "old") is None
    assert store.pop("access", "old") is None


def test_memory_store_flow_and_restart_loses_state():
    store = MemoryOAuthStore()
    app, _ = make_app(store)
    with TestClient(app, base_url=ISSUER) as c:
        info = register(c, "client_secret_post")
        code, verifier = authorize_and_login(c, info)
        tokens = token_request(c, info, {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": GEMINI_REDIRECT, "code_verifier": verifier,
        }).json()
        assert call_whoami(c, tokens["access_token"]).status_code == 200

    app, _ = make_app(MemoryOAuthStore())
    with TestClient(app, base_url=ISSUER) as c:
        assert call_whoami(c, tokens["access_token"]).status_code == 401


def test_store_from_env(aws, monkeypatch):
    monkeypatch.delenv("ALTFINANCE_OAUTH_TABLE", raising=False)
    monkeypatch.delenv("ALTFINANCE_OAUTH_KMS_KEY", raising=False)
    assert isinstance(store_from_env(), MemoryOAuthStore)

    monkeypatch.setenv("ALTFINANCE_OAUTH_TABLE", TABLE)
    with pytest.raises(RuntimeError):
        store_from_env()  # half-configured

    monkeypatch.setenv("ALTFINANCE_OAUTH_KMS_KEY", aws)
    assert isinstance(store_from_env(), DynamoOAuthStore)

    monkeypatch.setenv("ALTFINANCE_OAUTH_TABLE", "no-such-table")
    with pytest.raises(Exception):
        store_from_env()  # unusable: fail the deploy, never fall back to memory
