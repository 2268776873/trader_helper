from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from trade_helper.ledger import Ledger, LedgerConflict


MICRO = Decimal("1000000")


@dataclass(frozen=True)
class ReferencePoint:
    asset_id: str
    trading_date: date
    value_cny: Decimal
    source: str
    observed_at: datetime


@dataclass(frozen=True)
class DrawdownResult:
    asset_id: str
    as_of: date
    current_value_cny: Decimal
    rolling_high_cny: Decimal
    drawdown: Decimal
    observations: int


def _to_micro(value: Decimal) -> int:
    if value <= 0:
        raise ValueError("reference value must be positive")
    return int((value * MICRO).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _from_micro(value: int) -> Decimal:
    return Decimal(value) / MICRO


class ReferenceSeriesStore:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def add(self, point: ReferencePoint) -> bool:
        if point.observed_at.tzinfo is None:
            raise ValueError("observed_at must include timezone")
        try:
            with self.ledger.transaction() as connection:
                existing = connection.execute(
                    """
                    SELECT value_micro FROM reference_series
                    WHERE asset_id = ? AND trading_date = ? AND source = ?
                    """,
                    (
                        point.asset_id, point.trading_date.isoformat(),
                        point.source,
                    ),
                ).fetchone()
                value_micro = _to_micro(point.value_cny)
                if existing is not None:
                    if int(existing["value_micro"]) != value_micro:
                        raise LedgerConflict(
                            "reference point identifier has different content"
                        )
                    return False
                connection.execute(
                    """
                    INSERT INTO reference_series(
                        asset_id, trading_date, value_micro, source, observed_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        point.asset_id, point.trading_date.isoformat(), value_micro,
                        point.source, point.observed_at.isoformat(),
                    ),
                )
            return True
        except sqlite3.IntegrityError as error:
            raise LedgerConflict("reference point conflict") from error

    def drawdown(
        self,
        asset_id: str,
        as_of: date,
        *,
        trading_days: int = 250,
        source: str = "COMPOSITE",
    ) -> DrawdownResult:
        if trading_days <= 1:
            raise ValueError("trading_days must be greater than one")
        with closing(self.ledger.connect()) as connection:
            rows = connection.execute(
                """
                SELECT trading_date, value_micro
                FROM reference_series
                WHERE asset_id = ? AND trading_date <= ? AND source = ?
                ORDER BY trading_date DESC
                LIMIT ?
                """,
                (asset_id, as_of.isoformat(), source, trading_days),
            ).fetchall()
        if not rows:
            raise ValueError(f"no reference history for {asset_id} as of {as_of}")
        current = _from_micro(int(rows[0]["value_micro"]))
        high = max(_from_micro(int(row["value_micro"])) for row in rows)
        return DrawdownResult(
            asset_id, as_of, current, high, Decimal("1") - current / high, len(rows)
        )
