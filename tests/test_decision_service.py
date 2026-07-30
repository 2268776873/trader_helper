from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zoneinfo import ZoneInfo

from trade_helper.config import load_strategy_config
from trade_helper.decision import DecisionStatus
from trade_helper.decision_service import DailyDecisionService
from trade_helper.execution import ExecutionLedger, Fill
from trade_helper.ledger import AccountSnapshot, Ledger, PositionSnapshot
from trade_helper.market_data import (
    MarketDataStore, Observation, ObservationKind, aggregate_market_data,
)
from trade_helper.models import Quote
from trade_helper.reference_series import ReferencePoint, ReferenceSeriesStore


ROOT = Path(__file__).resolve().parents[1]
ZONE = ZoneInfo("Asia/Shanghai")


class DailyDecisionServiceTests(TestCase):
    def test_builds_and_persists_a_real_decision_from_ledger_state(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "account.db")
            ledger.initialize()
            config = load_strategy_config(ROOT / "config" / "personal_v1.json")
            now = datetime(2026, 9, 14, 14, 0, tzinfo=ZONE)
            ledger.add_snapshot(
                AccountSnapshot(
                    "S1", now, Decimal("500000"), Decimal("350000")
                ),
                (
                    PositionSnapshot("S1", "SP500", "513500", 24000, Decimal("60000")),
                    PositionSnapshot("S1", "NASDAQ", "513100", 30000, Decimal("60000")),
                    PositionSnapshot("S1", "DIVIDEND", "515450", 21000, Decimal("30000")),
                ),
            )
            references = ReferenceSeriesStore(ledger)
            markets = MarketDataStore(ledger)
            for asset in config.assets:
                references.add(
                    ReferencePoint(
                        asset.asset_id, date(2026, 9, 14), Decimal("100"),
                        "COMPOSITE", now,
                    )
                )
                quotes = (
                    Quote(asset.etf_code, asset.display_name, now, 2, 1.999, 2, None, "quote-a"),
                    Quote(asset.etf_code, asset.display_name, now, 2.001, 2, 2.001, None, "quote-b"),
                )
                observations = (
                    Observation(ObservationKind.VALUATION, "v-a", now, Decimal("2")),
                    Observation(ObservationKind.VALUATION, "v-b", now, Decimal("2.001")),
                    Observation(ObservationKind.INDEX, "index", now, Decimal("100")),
                    Observation(ObservationKind.FX, "fx", now, Decimal("7.1")),
                )
                markets.save(
                    aggregate_market_data(
                        snapshot_id=f"M-{asset.etf_code}",
                        symbol=asset.etf_code,
                        now=now,
                        quotes=quotes,
                        observations=observations,
                    )
                )

            outcome = DailyDecisionService(ledger, config).execute(
                decision_id="D-1", now=now, a_share_trading_day_number=10
            )

            self.assertEqual(DecisionStatus.READY, outcome.status)
            self.assertEqual(1, ledger.count("decision_runs"))
            self.assertEqual(1, ledger.count("advice"))

            advice = next(
                item for item in outcome.advices if item.action == "BUY"
            )
            connection = ledger.connect()
            try:
                advice_id = connection.execute(
                    "SELECT advice_id FROM advice"
                ).fetchone()["advice_id"]
            finally:
                connection.close()
            fill_quantity = min(100, advice.quantity)
            fill_value = Decimal(fill_quantity) * advice.limit_price
            ExecutionLedger(ledger).record_fill(
                Fill(
                    "FILL-1", advice_id, now + timedelta(seconds=30),
                    fill_quantity, advice.limit_price,
                )
            )
            projected = DailyDecisionService(ledger, config).build_request(
                decision_id="D-PROJECTED",
                now=now + timedelta(minutes=1),
                a_share_trading_day_number=10,
            )
            self.assertTrue(projected.reconciled)
            self.assertEqual(
                Decimal("350000") - fill_value,
                projected.base_input.cash_cny,
            )
            projected_candidate = next(
                item
                for item in projected.base_input.candidates
                if item.asset_id == advice.asset_id
            )
            self.assertEqual(
                Decimal("60000") + fill_value,
                projected_candidate.position_value_cny,
            )

            stale_service = DailyDecisionService(ledger, config)
            stale_request = stale_service.build_request(
                decision_id="D-2",
                now=now + timedelta(minutes=6),
                a_share_trading_day_number=10,
            )
            self.assertTrue(
                all(
                    "market snapshot is stale at decision time" in market.reasons
                    for market in stale_request.markets
                )
            )
            stale_outcome = stale_service.execute(
                decision_id="D-2",
                now=now + timedelta(minutes=6),
                a_share_trading_day_number=10,
            )

            self.assertEqual(DecisionStatus.BLOCKED, stale_outcome.status)
