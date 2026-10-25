"""Storage backends for the OAuth provider's state.

The provider keeps five kinds of record: registered clients, pending login
sessions, authorization codes, access tokens and refresh tokens. Each record
is a JSON-able dict plus an optional secret (the user's API key, or a
client's secret) and an optional expiry.

Two backends:

- ``MemoryOAuthStore``: plain dicts. Used for stdio, local dev and tests.
  Everything is lost when the process exits.
- ``DynamoOAuthStore``: one DynamoDB table plus one KMS key. Used by the
  hosted connector so that connections survive restarts and redeploys.
  Token, code and session values are never stored: rows are keyed by their
  SHA-256. Secrets are KMS-encrypted, bound to their row by the encryption
  context, so a ciphertext copied to another row does not decrypt.

``store_from_env()`` picks the backend from ``ALTFINANCE_OAUTH_TABLE`` and
``ALTFINANCE_OAUTH_KMS_KEY``.
"""

import hashlib
import json
import logging
import os
import time
from typing import Optional, Protocol

logger = logging.getLogger(__name__)

# Record kinds
CLIENT = "client"
PENDING = "pending"
CODE = "code"
ACCESS = "access"
REFRESH = "refresh"

# Kinds whose key is a bearer value (token, code, login session) and must
# never be stored in the clear. Client ids are public identifiers.
_HASHED_KINDS = {PENDING, CODE, ACCESS, REFRESH}

# A record: (data, secret)
Record = tuple[dict, Optional[str]]


def _row_key(kind: str, key: str) -> str:
    if kind in _HASHED_KINDS:
        key = hashlib.sha256(key.encode()).hexdigest()
    return f"{kind}#{key}"


class OAuthStore(Protocol):
    def put(
        self,
        kind: str,
        key: str,
        data: dict,
        *,
        secret: Optional[str] = None,
        expires_at: Optional[int] = None,
    ) -> None: ...

    def get(self, kind: str, key: str) -> Optional[Record]: ...

    def pop(self, kind: str, key: str) -> Optional[Record]:
        """Delete and return a record atomically.

        Only one caller ever gets a given record back, so a reused
        authorization code or refresh token is rejected even when two
        server processes are running.
        """
        ...

    def delete(self, kind: str, key: str) -> None: ...


class MemoryOAuthStore:
    """In-process store. State is lost on restart."""

    persistent = False

    def __init__(self) -> None:
        self._rows: dict[str, tuple[dict, Optional[str], Optional[int]]] = {}

    def put(self, kind, key, data, *, secret=None, expires_at=None):
        self._rows[_row_key(kind, key)] = (data, secret, expires_at)

    def get(self, kind, key):
        row = self._rows.get(_row_key(kind, key))
        if row is None:
            return None
        data, secret, expires_at = row
        if expires_at is not None and expires_at < time.time():
            self._rows.pop(_row_key(kind, key), None)
            return None
        return data, secret

    def pop(self, kind, key):
        record = self.get(kind, key)
        self._rows.pop(_row_key(kind, key), None)
        return record

    def delete(self, kind, key):
        self._rows.pop(_row_key(kind, key), None)


class DynamoOAuthStore:
    """DynamoDB + KMS store.

    Table: partition key ``pk`` (S), TTL attribute ``ttl``. Items carry
    ``data`` (JSON string), optional ``secret`` (KMS ciphertext) and
    optional ``ttl`` (epoch seconds). DynamoDB deletes expired items
    lazily, so reads also check ``ttl`` themselves.
    """

    persistent = True

    def __init__(self, table_name: str, kms_key_id: str, region: str) -> None:
        import boto3  # Only needed for the hosted connector

        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        self._kms = boto3.client("kms", region_name=region)
        self._kms_key_id = kms_key_id
        self.table_name = table_name

    @staticmethod
    def _context(pk: str) -> dict:
        return {"app": "altfinance-mcp", "pk": pk}

    def _encrypt(self, pk: str, plaintext: str) -> bytes:
        resp = self._kms.encrypt(
            KeyId=self._kms_key_id,
            Plaintext=plaintext.encode(),
            EncryptionContext=self._context(pk),
        )
        return resp["CiphertextBlob"]

    def _decrypt(self, pk: str, blob) -> str:
        resp = self._kms.decrypt(
            CiphertextBlob=bytes(blob),
            EncryptionContext=self._context(pk),
        )
        return resp["Plaintext"].decode()

    def _record(self, item: Optional[dict]) -> Optional[Record]:
        if not item:
            return None
        ttl = item.get("ttl")
        if ttl is not None and int(ttl) < time.time():
            return None
        secret = item.get("secret")
        if secret is not None:
            # boto3 returns Binary for B attributes
            secret = self._decrypt(item["pk"], getattr(secret, "value", secret))
        return json.loads(item["data"]), secret

    def put(self, kind, key, data, *, secret=None, expires_at=None):
        pk = _row_key(kind, key)
        item = {"pk": pk, "data": json.dumps(data)}
        if secret is not None:
            item["secret"] = self._encrypt(pk, secret)
        if expires_at is not None:
            item["ttl"] = int(expires_at)
        self._table.put_item(Item=item)

    def get(self, kind, key):
        resp = self._table.get_item(Key={"pk": _row_key(kind, key)}, ConsistentRead=True)
        return self._record(resp.get("Item"))

    def pop(self, kind, key):
        from botocore.exceptions import ClientError

        try:
            resp = self._table.delete_item(
                Key={"pk": _row_key(kind, key)},
                ConditionExpression="attribute_exists(pk)",
                ReturnValues="ALL_OLD",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise
        return self._record(resp.get("Attributes"))

    def delete(self, kind, key):
        self._table.delete_item(Key={"pk": _row_key(kind, key)})

    def check(self) -> None:
        """Fail fast if the table or key is unusable (missing, or IAM denied)."""
        pk = "healthcheck#startup"
        self._decrypt(pk, self._encrypt(pk, "ok"))
        self._table.get_item(Key={"pk": pk})


def store_from_env() -> OAuthStore:
    """Choose the backend from the environment.

    ``ALTFINANCE_OAUTH_TABLE`` and ``ALTFINANCE_OAUTH_KMS_KEY`` both set:
    DynamoDB, verified at startup (raises if unusable, so a broken deploy
    fails instead of silently forgetting every connection). Neither set:
    in-memory. Only one set: configuration error.
    """
    table = os.environ.get("ALTFINANCE_OAUTH_TABLE", "").strip()
    kms_key = os.environ.get("ALTFINANCE_OAUTH_KMS_KEY", "").strip()
    if not table and not kms_key:
        logger.warning(
            "OAuth state is in memory: connections will not survive a restart "
            "(set ALTFINANCE_OAUTH_TABLE and ALTFINANCE_OAUTH_KMS_KEY to persist)."
        )
        return MemoryOAuthStore()
    if not table or not kms_key:
        raise RuntimeError(
            "Set both ALTFINANCE_OAUTH_TABLE and ALTFINANCE_OAUTH_KMS_KEY, or neither."
        )
    region = (
        os.environ.get("ALTFINANCE_OAUTH_REGION")
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "us-east-1"
    )
    store = DynamoOAuthStore(table, kms_key, region)
    store.check()
    logger.info(f"OAuth state persisted in DynamoDB table {table} ({region}).")
    return store
