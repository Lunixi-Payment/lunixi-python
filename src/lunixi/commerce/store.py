"""Durable transaction protocol and real SQLite implementation.

The native order callback MUST use this transaction's connection. A process-local
set or a separate database transaction cannot make fulfillment atomic.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ContextManager, Iterator, Optional, Protocol

from .models import CommerceError


class Transaction(Protocol):
    def load(self) -> Optional[dict[str, Any]]: ...
    def save(self, record: dict[str, Any]) -> None: ...
    def claim_event(self, merchant_id: str, event_id: str, payload_hash: str) -> bool: ...


class LedgerStore(Protocol):
    def transaction(self, order_key: str) -> ContextManager[Transaction]: ...
    def find_payment(self, payment_id: str) -> Optional[str]: ...


class SqliteTransaction:
    def __init__(self, connection: sqlite3.Connection, order_key: str) -> None:
        self.connection = connection
        self.order_key = order_key

    def load(self) -> Optional[dict[str, Any]]:
        row = self.connection.execute(
            "SELECT payload FROM lunixi_attempt WHERE order_key=?", (self.order_key,)
        ).fetchone()
        return json.loads(row[0]) if row is not None and row[0] is not None else None

    def save(self, record: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO lunixi_attempt(order_key,payload,payment_id) VALUES(?,?,?) ON CONFLICT(order_key) DO UPDATE SET payload=excluded.payload,payment_id=excluded.payment_id",
            (
                self.order_key,
                json.dumps(record, separators=(",", ":")),
                record.get("paymentId", ""),
            ),
        )

    def claim_event(self, merchant_id: str, event_id: str, payload_hash: str) -> bool:
        key = hashlib.sha256((merchant_id + "\0" + event_id).encode()).hexdigest()
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO lunixi_event(event_key,payload_hash) VALUES(?,?)",
            (key, payload_hash),
        )
        if cursor.rowcount == 1:
            return True
        row = self.connection.execute(
            "SELECT payload_hash FROM lunixi_event WHERE event_key=?", (key,)
        ).fetchone()
        if row is None or not hmac.compare_digest(row[0], payload_hash):
            raise CommerceError("Verified event identity was reused with different content.")
        return False


class SqliteLedgerStore:
    """Disk-backed, per-transaction connections and BEGIN IMMEDIATE writer locks."""

    def __init__(self, path: str) -> None:
        if not isinstance(path, str) or path in ("", ":memory:") or path.startswith("file:"):
            raise CommerceError("A persistent SQLite file path is required.")
        self.path = str(Path(path).resolve())

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def install(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""CREATE TABLE IF NOT EXISTS lunixi_attempt(order_key TEXT PRIMARY KEY,payload TEXT,payment_id TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS lunixi_payment_lookup ON lunixi_attempt(payment_id);
CREATE TABLE IF NOT EXISTS lunixi_event(event_key TEXT PRIMARY KEY,payload_hash TEXT NOT NULL);""")
        connection.close()

    @contextmanager
    def transaction(self, order_key: str) -> Iterator[Transaction]:
        if not isinstance(order_key, str) or not 1 <= len(order_key) <= 191:
            raise CommerceError("Invalid durable order key.")
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield SqliteTransaction(connection, order_key)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def find_payment(self, payment_id: str) -> Optional[str]:
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT order_key FROM lunixi_attempt WHERE payment_id=? LIMIT 2", (payment_id,)
            ).fetchall()
            return str(rows[0][0]) if len(rows) == 1 else None
        finally:
            connection.close()

    def pending_keys(self, limit: int = 100) -> list[str]:
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT order_key,payload FROM lunixi_attempt LIMIT ?", (max(1, min(limit, 1000)),)
            ).fetchall()
            return [
                r[0] for r in rows if json.loads(r[1]).get("state") not in ("failed", "refunded")
            ]
        finally:
            connection.close()
