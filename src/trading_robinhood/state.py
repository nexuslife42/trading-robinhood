"""Local durable ledger. SQLite and process locks protect against accidental concurrency."""

import fcntl
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import OrderIntent, Usage


class ExecutionError(RuntimeError):
    """A closed execution gate; safe to show its controlled message to the operator."""


ACTIVE = ("submitting", "unknown", "open", "partial", "cancel_pending")


class State:
    def __init__(self, path: Path):
        self.path = path.resolve() if not path.is_symlink() else path
        if self.path.is_symlink():
            raise ExecutionError("State file must not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.connection = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
          CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          INSERT OR IGNORE INTO settings VALUES ('halted', 'false');
          CREATE TABLE IF NOT EXISTS orders(
            id TEXT PRIMARY KEY, account TEXT NOT NULL, intent TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL, submitted_at TEXT,
            approval TEXT, broker_id TEXT, filled_quantity TEXT NOT NULL DEFAULT '0');
          CREATE TABLE IF NOT EXISTS events(
            seq INTEGER PRIMARY KEY, order_id TEXT, kind TEXT NOT NULL,
            at TEXT NOT NULL, detail TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS paper_accounts(
            account TEXT PRIMARY KEY, cash TEXT NOT NULL, positions TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS paper_quotes(
            instrument TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS paper_orders(
            id TEXT PRIMARY KEY, intent TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, filled TEXT NOT NULL DEFAULT '0',
            fee_paid INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS settlements(
            id INTEGER PRIMARY KEY, account TEXT NOT NULL,
            amount TEXT NOT NULL, due TEXT NOT NULL);
        """)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    @contextmanager
    def lock(self) -> Iterator[None]:
        fd = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ExecutionError("Executor busy; another operation owns the ledger") from exc
            yield
        finally:
            os.close(fd)

    @property
    def halted(self) -> bool:
        row = self.connection.execute("SELECT value FROM settings WHERE key='halted'").fetchone()
        unresolved = self.connection.execute(
            "SELECT 1 FROM orders WHERE status IN ('submitting','unknown','cancel_pending') LIMIT 1"
        ).fetchone()
        return row is None or row[0] != "false" or unresolved is not None

    def set_halt(self, halted: bool) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO settings VALUES ('halted', ?)",
            ("true" if halted else "false",),
        )

    def event(self, order_id: str | None, kind: str, now: datetime, detail: str = "") -> None:
        self.connection.execute(
            "INSERT INTO events(order_id,kind,at,detail) VALUES (?,?,?,?)",
            (order_id, kind, now.astimezone(UTC).isoformat(), detail),
        )

    def get_order(self, key: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM orders WHERE id=?", (key,)).fetchone()
        if row is None:
            raise ExecutionError("Unknown order")
        return dict(row)

    def orders(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM orders ORDER BY rowid")]

    def events(self, key: str | None = None) -> list[dict[str, Any]]:
        if key is None:
            rows = self.connection.execute("SELECT * FROM events ORDER BY seq")
        else:
            rows = self.connection.execute(
                "SELECT * FROM events WHERE order_id=? ORDER BY seq", (key,)
            )
        return [dict(row) for row in rows]

    def usage(self, account: str, now: datetime, fee: Decimal) -> Usage:
        cash = Decimal(0)
        positions: dict[str, Decimal] = {}
        daily_value = Decimal(0)
        daily_count = open_count = 0
        for row in self.orders():
            if row["account"] != account:
                continue
            intent = OrderIntent.model_validate_json(row["intent"])
            if (
                row["submitted_at"]
                and datetime.fromisoformat(row["submitted_at"]).date() == now.astimezone(UTC).date()
            ):
                daily_count += 1
                daily_value += intent.notional
            if row["status"] in ACTIVE:
                open_count += 1
                remaining = intent.quantity - Decimal(row["filled_quantity"])
                # Conservatively reserve the fee until terminal, even if it may already be paid.
                cash += fee
                if intent.side == "buy":
                    cash += remaining * intent.limit_price
                else:
                    positions[intent.instrument] = (
                        positions.get(intent.instrument, Decimal(0)) + remaining
                    )
        return Usage(
            reserved_cash=cash,
            reserved_positions=positions,
            daily_value=daily_value,
            daily_orders=daily_count,
            open_orders=open_count,
        )

    def backup(self, destination: Path) -> None:
        if destination.exists():
            raise ExecutionError("Backup destination already exists")
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        target = sqlite3.connect(destination)
        try:
            self.connection.backup(target)
        finally:
            target.close()

    def close(self) -> None:
        self.connection.close()


def encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
