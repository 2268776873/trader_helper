from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.config import load_strategy_config
from trade_helper.ledger import AccountSnapshot, CashFlow, Ledger, PositionSnapshot
from trade_helper.execution import Advice, ExecutionLedger, Fill
from trade_helper.models import Readiness
from trade_helper.market_data import (
    MarketDataStore, Observation, ObservationKind, aggregate_market_data,
)
from trade_helper.models import Quote
from trade_helper.state_store import StrategyStateStore
from trade_helper.ui.view_model import DashboardRepository


ROOT = Path(__file__).resolve().parents[1]


class DashboardRepositoryTests(TestCase):
    def test_missing_database_is_explicitly_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            model = DashboardRepository(Path(directory) / "missing.db").load()
        self.assertFalse(model.has_account)
        self.assertEqual(Readiness.BLOCKED, model.data_status)
        self.assertEqual("RECONCILIATION_REQUIRED", model.reconciliation_status)

    def test_reads_latest_account_and_runtime_pools(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "account.db"
            ledger = Ledger(database)
            ledger.initialize()
            config = load_strategy_config(ROOT / "config" / "personal_v1.json")
            StrategyStateStore(ledger).initialize_runtime(config)
            ledger.add_snapshot(
                AccountSnapshot(
                    "SNAP-1", datetime(2026, 7, 30, tzinfo=timezone.utc),
                    Decimal("500000"), Decimal("350000"),
                ),
                (
                    PositionSnapshot(
                        "SNAP-1", "SP500", "513500", 24000, Decimal("60000")
                    ),
                ),
            )
            ExecutionLedger(ledger).create_advice(
                Advice(
                    "ADV-1", datetime(2026, 7, 30, tzinfo=timezone.utc),
                    "personal-v1", "SP500", "513500", "BUY", 1000,
                    Decimal("2.000"), "test",
                )
            )
            ExecutionLedger(ledger).record_fill(
                Fill(
                    "FILL-1", "ADV-1",
                    datetime(2026, 7, 30, 0, 1, tzinfo=timezone.utc),
                    400, Decimal("2"),
                )
            )
            ledger.add_cash_flow(
                CashFlow(
                    "FLOW-1", datetime(2026, 7, 29, tzinfo=timezone.utc),
                    "DEPOSIT", Decimal("16000"),
                )
            )
            market_now = datetime(2026, 7, 30, 6, 0, tzinfo=timezone.utc)
            MarketDataStore(ledger).save(
                aggregate_market_data(
                    snapshot_id="M-1", symbol="513500", now=market_now,
                    quotes=(
                        Quote("513500", "SP", market_now, 2, 2, 2, None, "q1"),
                        Quote("513500", "SP", market_now, 2, 2, 2, None, "q2"),
                    ),
                    observations=(
                        Observation(ObservationKind.VALUATION, "v1", market_now, Decimal("2")),
                        Observation(ObservationKind.VALUATION, "v2", market_now, Decimal("2")),
                        Observation(ObservationKind.INDEX, "i1", market_now, Decimal("100")),
                        Observation(ObservationKind.FX, "f1", market_now, Decimal("7")),
                    ),
                )
            )

            model = DashboardRepository(database).load()
            history = DashboardRepository(database).load_history()
            details = DashboardRepository(database).load_market_details()
            versions, levels = DashboardRepository(database).load_config_versions()

        self.assertTrue(model.has_account)
        self.assertEqual(Decimal("500000"), model.total_assets_cny)
        self.assertEqual(Decimal("349200"), model.cash_cny)
        self.assertEqual(Decimal("0.1216"), model.assets[0].weight)
        self.assertEqual(Decimal("350000"), sum(value for _, value in model.cash_pools))
        self.assertEqual("ADV-1", model.open_advices[0].advice_id)
        self.assertEqual(400, model.open_advices[0].filled_quantity)
        cash_record = next(item for item in history if item.category == "资金")
        self.assertIn("16,000.00", cash_record.summary)
        self.assertTrue(any(item.category == "成交" for item in history))
        self.assertEqual(("q1", "q2"), details[0].quote_sources)
        self.assertEqual(("v1", "v2"), details[0].valuation_sources)
        self.assertTrue(versions[0].is_runtime)
        self.assertEqual("personal-v1", versions[0].config_version)
        self.assertEqual(9, len(levels))
