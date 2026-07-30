from __future__ import annotations

import sqlite3
import hashlib
import json
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterator


class LedgerConflict(RuntimeError):
    """Raised when an immutable ledger identifier is reused."""


def cny_to_fen(value: Decimal | int | float | str) -> int:
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(amount * 100)


def price_to_milli(value: Decimal | int | float | str) -> int:
    price = Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return int(price * 1000)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("datetime must include timezone")
    return value.isoformat()


@dataclass(frozen=True)
class AccountSnapshot:
    snapshot_id: str
    as_of: datetime
    total_assets_cny: Decimal
    available_cash_cny: Decimal
    frozen_cash_cny: Decimal = Decimal("0")
    source: str = "MANUAL"
    notes: str = ""


@dataclass(frozen=True)
class PositionSnapshot:
    snapshot_id: str
    asset_id: str
    etf_code: str
    quantity: int
    broker_market_value_cny: Decimal | None = None
    source: str = "MANUAL"


@dataclass(frozen=True)
class Trade:
    trade_id: str
    trade_time: datetime
    asset_id: str
    etf_code: str
    side: str
    quantity: int
    price: Decimal
    status: str = "FILLED"
    source: str = "MANUAL"
    notes: str = ""


@dataclass(frozen=True)
class CashFlow:
    flow_id: str
    flow_time: datetime
    flow_type: str
    amount_cny: Decimal
    asset_id: str | None = None
    notes: str = ""


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self._path = str(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with closing(self.connect()) as connection:
            with connection:
                connection.executescript(
                    """
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR REPLACE INTO schema_metadata(key, value)
                VALUES ('schema_version', '1');

                CREATE TABLE IF NOT EXISTS account_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    total_assets_fen INTEGER NOT NULL CHECK(total_assets_fen >= 0),
                    available_cash_fen INTEGER NOT NULL CHECK(available_cash_fen >= 0),
                    frozen_cash_fen INTEGER NOT NULL CHECK(frozen_cash_fen >= 0),
                    source TEXT NOT NULL,
                    notes TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS position_snapshots (
                    snapshot_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    etf_code TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity >= 0),
                    broker_market_value_fen INTEGER,
                    source TEXT NOT NULL,
                    PRIMARY KEY(snapshot_id, asset_id),
                    FOREIGN KEY(snapshot_id)
                        REFERENCES account_snapshots(snapshot_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    trade_time TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    etf_code TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('BUY', 'SELL')),
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    price_milli INTEGER NOT NULL CHECK(price_milli > 0),
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    notes TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cash_flows (
                    flow_id TEXT PRIMARY KEY,
                    flow_time TEXT NOT NULL,
                    flow_type TEXT NOT NULL,
                    amount_fen INTEGER NOT NULL CHECK(amount_fen != 0),
                    asset_id TEXT,
                    notes TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS import_batches (
                    batch_id TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL UNIQUE,
                    imported_at TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    row_counts_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS advice (
                    advice_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    config_version TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    etf_code TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('BUY', 'SELL')),
                    proposed_quantity INTEGER NOT NULL CHECK(proposed_quantity > 0),
                    limit_price_milli INTEGER NOT NULL CHECK(limit_price_milli > 0),
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS order_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    advice_id TEXT NOT NULL,
                    attempted_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    broker_order_id TEXT,
                    notes TEXT NOT NULL,
                    FOREIGN KEY(advice_id) REFERENCES advice(advice_id)
                );

                CREATE TABLE IF NOT EXISTS advice_fills (
                    fill_id TEXT PRIMARY KEY,
                    advice_id TEXT NOT NULL,
                    attempt_id TEXT,
                    filled_at TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    price_milli INTEGER NOT NULL CHECK(price_milli > 0),
                    FOREIGN KEY(advice_id) REFERENCES advice(advice_id),
                    FOREIGN KEY(attempt_id) REFERENCES order_attempts(attempt_id)
                );
                    """
                )

    def apply_import_batch(
        self,
        *,
        content_hash: str,
        source_name: str,
        snapshots: tuple[tuple[AccountSnapshot, tuple[PositionSnapshot, ...]], ...],
        trades: tuple[Trade, ...],
        cash_flows: tuple[CashFlow, ...],
    ) -> bool:
        """Atomically apply a validated import. Returns False for an identical batch."""
        batch_id = hashlib.sha256(
            f"{source_name}\0{content_hash}".encode("utf-8")
        ).hexdigest()
        row_counts = {
            "snapshots": len(snapshots),
            "positions": sum(len(item[1]) for item in snapshots),
            "trades": len(trades),
            "cash_flows": len(cash_flows),
        }
        try:
            with self.transaction() as connection:
                existing = connection.execute(
                    "SELECT 1 FROM import_batches WHERE content_hash = ?",
                    (content_hash,),
                ).fetchone()
                if existing is not None:
                    return False

                for snapshot, positions in snapshots:
                    connection.execute(
                        """
                        INSERT INTO account_snapshots(
                            snapshot_id, as_of, total_assets_fen,
                            available_cash_fen, frozen_cash_fen, source, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            snapshot.snapshot_id, _iso(snapshot.as_of),
                            cny_to_fen(snapshot.total_assets_cny),
                            cny_to_fen(snapshot.available_cash_cny),
                            cny_to_fen(snapshot.frozen_cash_cny),
                            snapshot.source, snapshot.notes,
                        ),
                    )
                    connection.executemany(
                        """
                        INSERT INTO position_snapshots(
                            snapshot_id, asset_id, etf_code, quantity,
                            broker_market_value_fen, source
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                item.snapshot_id, item.asset_id, item.etf_code,
                                item.quantity,
                                cny_to_fen(item.broker_market_value_cny)
                                if item.broker_market_value_cny is not None else None,
                                item.source,
                            )
                            for item in positions
                        ],
                    )
                connection.executemany(
                    """
                    INSERT INTO trades(
                        trade_id, trade_time, asset_id, etf_code, side,
                        quantity, price_milli, status, source, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.trade_id, _iso(item.trade_time), item.asset_id,
                            item.etf_code, item.side, item.quantity,
                            price_to_milli(item.price), item.status,
                            item.source, item.notes,
                        )
                        for item in trades
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO cash_flows(
                        flow_id, flow_time, flow_type, amount_fen, asset_id, notes
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.flow_id, _iso(item.flow_time), item.flow_type,
                            cny_to_fen(item.amount_cny), item.asset_id, item.notes,
                        )
                        for item in cash_flows
                    ],
                )
                connection.execute(
                    """
                    INSERT INTO import_batches(
                        batch_id, content_hash, imported_at, source_name, row_counts_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id, content_hash, datetime.now().astimezone().isoformat(),
                        source_name, json.dumps(row_counts, sort_keys=True),
                    ),
                )
            return True
        except sqlite3.IntegrityError as error:
            raise LedgerConflict(f"import batch conflicts with existing ledger data: {source_name}") from error

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def add_snapshot(
        self,
        snapshot: AccountSnapshot,
        positions: tuple[PositionSnapshot, ...],
    ) -> None:
        if any(position.snapshot_id != snapshot.snapshot_id for position in positions):
            raise ValueError("all positions must reference the account snapshot")
        if len({position.asset_id for position in positions}) != len(positions):
            raise ValueError("position asset_id values must be unique")

        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO account_snapshots(
                        snapshot_id, as_of, total_assets_fen,
                        available_cash_fen, frozen_cash_fen, source, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id,
                        _iso(snapshot.as_of),
                        cny_to_fen(snapshot.total_assets_cny),
                        cny_to_fen(snapshot.available_cash_cny),
                        cny_to_fen(snapshot.frozen_cash_cny),
                        snapshot.source,
                        snapshot.notes,
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO position_snapshots(
                        snapshot_id, asset_id, etf_code, quantity,
                        broker_market_value_fen, source
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            position.snapshot_id,
                            position.asset_id,
                            position.etf_code,
                            position.quantity,
                            (
                                cny_to_fen(position.broker_market_value_cny)
                                if position.broker_market_value_cny is not None
                                else None
                            ),
                            position.source,
                        )
                        for position in positions
                    ],
                )
        except sqlite3.IntegrityError as error:
            raise LedgerConflict(f"snapshot conflict: {snapshot.snapshot_id}") from error

    def add_trade(self, trade: Trade) -> None:
        if trade.side not in {"BUY", "SELL"}:
            raise ValueError("trade side must be BUY or SELL")
        if trade.quantity <= 0:
            raise ValueError("trade quantity must be positive")
        try:
            with closing(self.connect()) as connection:
                with connection:
                    connection.execute(
                        """
                    INSERT INTO trades(
                        trade_id, trade_time, asset_id, etf_code, side,
                        quantity, price_milli, status, source, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade.trade_id,
                        _iso(trade.trade_time),
                        trade.asset_id,
                        trade.etf_code,
                        trade.side,
                        trade.quantity,
                        price_to_milli(trade.price),
                        trade.status,
                        trade.source,
                        trade.notes,
                        ),
                    )
        except sqlite3.IntegrityError as error:
            raise LedgerConflict(f"trade conflict: {trade.trade_id}") from error

    def add_cash_flow(self, cash_flow: CashFlow) -> None:
        try:
            with closing(self.connect()) as connection:
                with connection:
                    connection.execute(
                        """
                    INSERT INTO cash_flows(
                        flow_id, flow_time, flow_type, amount_fen, asset_id, notes
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cash_flow.flow_id,
                        _iso(cash_flow.flow_time),
                        cash_flow.flow_type,
                        cny_to_fen(cash_flow.amount_cny),
                        cash_flow.asset_id,
                        cash_flow.notes,
                        ),
                    )
        except sqlite3.IntegrityError as error:
            raise LedgerConflict(f"cash flow conflict: {cash_flow.flow_id}") from error

    def count(self, table: str) -> int:
        allowed = {
            "account_snapshots",
            "position_snapshots",
            "trades",
            "cash_flows",
            "import_batches",
            "advice",
            "order_attempts",
            "advice_fills",
        }
        if table not in allowed:
            raise ValueError("unsupported table")
        with closing(self.connect()) as connection:
            row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"])
