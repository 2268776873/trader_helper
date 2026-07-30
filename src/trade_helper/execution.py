from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from trade_helper.ledger import Ledger, LedgerConflict, _iso, price_to_milli


class AdviceStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Advice:
    advice_id: str
    created_at: datetime
    config_version: str
    asset_id: str
    etf_code: str
    side: str
    proposed_quantity: int
    limit_price: Decimal
    reason: str


@dataclass(frozen=True)
class OrderAttempt:
    attempt_id: str
    advice_id: str
    attempted_at: datetime
    status: AdviceStatus
    broker_order_id: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class Fill:
    fill_id: str
    advice_id: str
    filled_at: datetime
    quantity: int
    price: Decimal
    attempt_id: str | None = None


class ExecutionLedger:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def create_advice(self, advice: Advice) -> None:
        if advice.side not in {"BUY", "SELL"}:
            raise ValueError("advice side must be BUY or SELL")
        if advice.proposed_quantity <= 0:
            raise ValueError("proposed quantity must be positive")
        try:
            with self.ledger.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO advice(
                        advice_id, created_at, config_version, asset_id, etf_code,
                        side, proposed_quantity, limit_price_milli, status, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        advice.advice_id, _iso(advice.created_at),
                        advice.config_version, advice.asset_id, advice.etf_code,
                        advice.side, advice.proposed_quantity,
                        price_to_milli(advice.limit_price),
                        AdviceStatus.PENDING_CONFIRMATION.value, advice.reason,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise LedgerConflict(f"advice conflict: {advice.advice_id}") from error

    def record_attempt(self, attempt: OrderAttempt) -> None:
        allowed = {
            AdviceStatus.NOT_ATTEMPTED,
            AdviceStatus.ORDER_SUBMITTED,
            AdviceStatus.CANCELLED,
            AdviceStatus.EXPIRED,
            AdviceStatus.REJECTED,
        }
        if attempt.status not in allowed:
            raise ValueError("attempt status cannot claim an unrecorded fill")
        try:
            with self.ledger.transaction() as connection:
                advice = connection.execute(
                    "SELECT status FROM advice WHERE advice_id = ?",
                    (attempt.advice_id,),
                ).fetchone()
                if advice is None:
                    raise ValueError("unknown advice_id")
                if advice["status"] == AdviceStatus.FILLED.value:
                    raise ValueError("filled advice cannot receive another attempt")
                connection.execute(
                    """
                    INSERT INTO order_attempts(
                        attempt_id, advice_id, attempted_at, status,
                        broker_order_id, notes
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt.attempt_id, attempt.advice_id,
                        _iso(attempt.attempted_at), attempt.status.value,
                        attempt.broker_order_id, attempt.notes,
                    ),
                )
                connection.execute(
                    "UPDATE advice SET status = ? WHERE advice_id = ?",
                    (attempt.status.value, attempt.advice_id),
                )
        except sqlite3.IntegrityError as error:
            raise LedgerConflict(f"attempt conflict: {attempt.attempt_id}") from error

    def record_fill(self, fill: Fill) -> AdviceStatus:
        if fill.quantity <= 0:
            raise ValueError("fill quantity must be positive")
        try:
            with self.ledger.transaction() as connection:
                advice = connection.execute(
                    """
                    SELECT asset_id, etf_code, side, proposed_quantity
                    FROM advice WHERE advice_id = ?
                    """,
                    (fill.advice_id,),
                ).fetchone()
                if advice is None:
                    raise ValueError("unknown advice_id")
                if fill.attempt_id is not None:
                    attempt = connection.execute(
                        """
                        SELECT 1 FROM order_attempts
                        WHERE attempt_id = ? AND advice_id = ?
                        """,
                        (fill.attempt_id, fill.advice_id),
                    ).fetchone()
                    if attempt is None:
                        raise ValueError("attempt does not belong to advice")
                prior = connection.execute(
                    "SELECT COALESCE(SUM(quantity), 0) AS quantity FROM advice_fills WHERE advice_id = ?",
                    (fill.advice_id,),
                ).fetchone()
                total = int(prior["quantity"]) + fill.quantity
                if total > int(advice["proposed_quantity"]):
                    raise ValueError("filled quantity exceeds proposed quantity")
                status = (
                    AdviceStatus.FILLED
                    if total == int(advice["proposed_quantity"])
                    else AdviceStatus.PARTIALLY_FILLED
                )
                connection.execute(
                    """
                    INSERT INTO advice_fills(
                        fill_id, advice_id, attempt_id, filled_at, quantity, price_milli
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fill.fill_id, fill.advice_id, fill.attempt_id,
                        _iso(fill.filled_at), fill.quantity, price_to_milli(fill.price),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO trades(
                        trade_id, trade_time, asset_id, etf_code, side,
                        quantity, price_milli, status, source, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'FILLED', 'APP_FORM', ?)
                    """,
                    (
                        fill.fill_id, _iso(fill.filled_at), advice["asset_id"],
                        advice["etf_code"], advice["side"], fill.quantity,
                        price_to_milli(fill.price), f"advice:{fill.advice_id}",
                    ),
                )
                connection.execute(
                    "UPDATE advice SET status = ? WHERE advice_id = ?",
                    (status.value, fill.advice_id),
                )
                return status
        except sqlite3.IntegrityError as error:
            raise LedgerConflict(f"fill conflict: {fill.fill_id}") from error

    def status(self, advice_id: str) -> AdviceStatus:
        with closing(self.ledger.connect()) as connection:
            row = connection.execute(
                "SELECT status FROM advice WHERE advice_id = ?", (advice_id,)
            ).fetchone()
        if row is None:
            raise ValueError("unknown advice_id")
        return AdviceStatus(row["status"])
