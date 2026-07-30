from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from trade_helper.config import StrategyConfig
from trade_helper.decision import DecisionOutcome
from trade_helper.decision_service import DailyDecisionService
from trade_helper.ledger import AccountSnapshot, Ledger, PositionSnapshot
from trade_helper.market_data import (
    MarketDataStore,
    Observation,
    ObservationKind,
    aggregate_market_data,
)
from trade_helper.models import Quote
from trade_helper.reference_series import ReferencePoint, ReferenceSeriesStore
from trade_helper.state_store import StrategyStateStore
from trade_helper.trading_calendar import CalendarDay, TradingCalendarStore


def create_example_database(
    path: str | Path,
    config: StrategyConfig,
    *,
    now: datetime,
) -> DecisionOutcome:
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing database: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(target)
    ledger.initialize()
    StrategyStateStore(ledger).initialize_runtime(config)
    ledger.add_snapshot(
        AccountSnapshot(
            "SAMPLE-SNAPSHOT-1",
            now,
            Decimal("500000"),
            Decimal("350000"),
            source="SAMPLE",
            notes="仅用于功能演示，不代表真实账户",
        ),
        (
            PositionSnapshot(
                "SAMPLE-SNAPSHOT-1", "SP500", "513500", 24000,
                Decimal("60000"), "SAMPLE",
            ),
            PositionSnapshot(
                "SAMPLE-SNAPSHOT-1", "NASDAQ", "513100", 30000,
                Decimal("60000"), "SAMPLE",
            ),
            PositionSnapshot(
                "SAMPLE-SNAPSHOT-1", "DIVIDEND", "515450", 21000,
                Decimal("30000"), "SAMPLE",
            ),
        ),
    )
    first = now.date().replace(day=1)
    calendar_days = tuple(
        CalendarDay(
            first + timedelta(days=offset),
            (first + timedelta(days=offset)).weekday() < 5,
            "SAMPLE_CALENDAR",
        )
        for offset in range((now.date() - first).days + 1)
    )
    calendar = TradingCalendarStore(ledger)
    calendar.replace(calendar_days)
    day_number = calendar.trading_day_number(now.date())
    if day_number is None:
        raise ValueError("example decision date must be an open sample day")

    references = ReferenceSeriesStore(ledger)
    markets = MarketDataStore(ledger)
    prices = {"SP500": Decimal("2"), "NASDAQ": Decimal("2"), "DIVIDEND": Decimal("1.5")}
    for asset in config.assets:
        value = prices[asset.asset_id]
        references.add(
            ReferencePoint(
                asset.asset_id, now.date(), Decimal("100"),
                "COMPOSITE", now,
            )
        )
        markets.save(
            aggregate_market_data(
                snapshot_id=f"SAMPLE-MARKET-{asset.etf_code}",
                symbol=asset.etf_code,
                now=now,
                quotes=(
                    Quote(
                        asset.etf_code, asset.display_name, now, float(value),
                        float(value), float(value), None, "SAMPLE_QUOTE_A",
                    ),
                    Quote(
                        asset.etf_code, asset.display_name, now,
                        float(value + Decimal("0.001")), float(value),
                        float(value + Decimal("0.001")), None, "SAMPLE_QUOTE_B",
                    ),
                ),
                observations=(
                    Observation(
                        ObservationKind.VALUATION, "SAMPLE_VALUATION_A",
                        now, value,
                    ),
                    Observation(
                        ObservationKind.VALUATION, "SAMPLE_VALUATION_B",
                        now, value + Decimal("0.001"),
                    ),
                    Observation(
                        ObservationKind.INDEX, "SAMPLE_INDEX",
                        now, Decimal("100"),
                    ),
                    Observation(
                        ObservationKind.FX, "SAMPLE_FX",
                        now, Decimal("7.1") if asset.asset_id != "DIVIDEND" else Decimal("1"),
                    ),
                ),
            )
        )
    return DailyDecisionService(ledger, config).execute(
        decision_id="SAMPLE-DECISION-1",
        now=now,
        a_share_trading_day_number=day_number,
    )
