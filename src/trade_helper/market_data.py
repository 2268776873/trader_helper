from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from trade_helper.ledger import Ledger, LedgerConflict
from trade_helper.models import Quote, Readiness


class ObservationKind(StrEnum):
    QUOTE = "QUOTE"
    VALUATION = "VALUATION"
    INDEX = "INDEX"
    FX = "FX"
    ANNOUNCEMENT = "ANNOUNCEMENT"


@dataclass(frozen=True)
class Observation:
    kind: ObservationKind
    source: str
    observed_at: datetime
    value: Decimal | None = None
    blocking: bool = False
    detail: str = ""


@dataclass(frozen=True)
class MarketSnapshot:
    snapshot_id: str
    symbol: str
    generated_at: datetime
    readiness: Readiness
    reasons: tuple[str, ...]
    quotes: tuple[Quote, ...]
    observations: tuple[Observation, ...]
    selected_ask: Decimal | None
    conservative_valuation: Decimal | None


def aggregate_market_data(
    *,
    snapshot_id: str,
    symbol: str,
    now: datetime,
    quotes: tuple[Quote, ...],
    observations: tuple[Observation, ...] = (),
    max_age: timedelta = timedelta(minutes=5),
    maximum_quote_deviation: Decimal = Decimal("0.005"),
    maximum_premium_difference: Decimal = Decimal("0.005"),
) -> MarketSnapshot:
    reasons: list[str] = []
    symbol_quotes = tuple(item for item in quotes if item.symbol == symbol)
    fresh_quotes = tuple(
        item
        for item in symbol_quotes
        if item.observed_at <= now + timedelta(seconds=30)
        and now - item.observed_at <= max_age
        and item.last_price is not None
    )
    if len({item.source for item in fresh_quotes}) < 2:
        reasons.append("缺少两个独立且新鲜的行情源")
    prices = [Decimal(str(item.last_price)) for item in fresh_quotes if item.last_price]
    if len(prices) >= 2 and (max(prices) / min(prices) - 1) > maximum_quote_deviation:
        reasons.append("行情源价格偏差超过阈值")

    relevant = tuple(
        item
        for item in observations
        if item.observed_at <= now + timedelta(seconds=30)
        and now - item.observed_at <= max_age
    )
    valuations = tuple(
        item
        for item in relevant
        if item.kind == ObservationKind.VALUATION
        and item.value is not None
        and item.value > 0
    )
    if len({item.source for item in valuations}) < 2:
        reasons.append("缺少两个独立且新鲜的估值源")
    selected_ask = min(
        (
            Decimal(str(item.ask1 or item.last_price))
            for item in fresh_quotes
            if item.ask1 or item.last_price
        ),
        default=None,
    )
    if selected_ask is not None and len(valuations) >= 2:
        premiums = [selected_ask / item.value - 1 for item in valuations if item.value]
        if max(premiums) - min(premiums) > maximum_premium_difference:
            reasons.append("估值源溢价差超过阈值")
    if any(item.blocking for item in relevant):
        reasons.append("存在尚未解除的阻断公告或交易状态")
    blocking = {
        "缺少两个独立且新鲜的行情源",
        "行情源价格偏差超过阈值",
        "缺少两个独立且新鲜的估值源",
        "估值源溢价差超过阈值",
        "存在尚未解除的阻断公告或交易状态",
    }
    readiness = (
        Readiness.BLOCKED
        if any(reason in blocking for reason in reasons)
        else Readiness.READY
    )
    return MarketSnapshot(
        snapshot_id, symbol, now, readiness, tuple(reasons), symbol_quotes,
        observations, selected_ask,
        min((item.value for item in valuations if item.value), default=None),
    )


class MarketDataStore:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def save(self, snapshot: MarketSnapshot) -> None:
        def encode(value):
            if isinstance(value, (datetime, Decimal, StrEnum)):
                return str(value)
            raise TypeError(f"unsupported JSON value: {type(value)}")

        payload = json.dumps(asdict(snapshot), ensure_ascii=False, default=encode)
        try:
            with self.ledger.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO market_snapshots(
                        snapshot_id, symbol, observed_at, readiness,
                        reasons_json, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id, snapshot.symbol,
                        snapshot.generated_at.isoformat(), snapshot.readiness.value,
                        json.dumps(snapshot.reasons, ensure_ascii=False), payload,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise LedgerConflict(
                f"market snapshot conflict: {snapshot.snapshot_id}"
            ) from error
