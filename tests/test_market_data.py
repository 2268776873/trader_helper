from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.ledger import Ledger
from trade_helper.market_data import (
    MarketDataStore,
    Observation,
    ObservationKind,
    aggregate_market_data,
)
from trade_helper.models import Quote, Readiness


class MarketDataTests(TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 30, 6, 0, tzinfo=timezone.utc)

    def quote(self, source: str, price: float) -> Quote:
        return Quote(
            "513500", "SP500", self.now, price, price - 0.001,
            price + 0.001, None, source,
        )

    def observations(self) -> tuple[Observation, ...]:
        return (
            Observation(ObservationKind.VALUATION, "valuation-a", self.now, Decimal("1.999")),
            Observation(ObservationKind.VALUATION, "valuation-b", self.now, Decimal("2.000")),
            Observation(ObservationKind.INDEX, "index-a", self.now, Decimal("6500")),
            Observation(ObservationKind.FX, "fx-a", self.now, Decimal("7.15")),
        )

    def test_ready_requires_complete_consistent_sources(self) -> None:
        result = aggregate_market_data(
            snapshot_id="MKT-1", symbol="513500", now=self.now,
            quotes=(self.quote("sina", 2.0), self.quote("eastmoney", 2.001)),
            observations=self.observations(),
        )
        self.assertEqual(Readiness.READY, result.readiness)
        self.assertEqual(Decimal("1.999"), result.conservative_valuation)

    def test_stale_or_single_sources_block(self) -> None:
        stale = self.quote("eastmoney", 2.001)
        stale = Quote(
            stale.symbol, stale.name, self.now - timedelta(minutes=10),
            stale.last_price, stale.bid1, stale.ask1, stale.iopv, stale.source,
        )
        result = aggregate_market_data(
            snapshot_id="MKT-2", symbol="513500", now=self.now,
            quotes=(self.quote("sina", 2.0), stale),
            observations=self.observations(),
        )
        self.assertEqual(Readiness.BLOCKED, result.readiness)
        self.assertIn("缺少两个独立且新鲜的行情源", result.reasons)

    def test_raw_snapshot_is_auditable(self) -> None:
        result = aggregate_market_data(
            snapshot_id="MKT-3", symbol="513500", now=self.now,
            quotes=(self.quote("sina", 2.0), self.quote("eastmoney", 2.001)),
            observations=self.observations(),
        )
        with TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "account.db")
            ledger.initialize()
            MarketDataStore(ledger).save(result)
            self.assertEqual(1, ledger.count("market_snapshots"))
