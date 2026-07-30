from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.config import load_strategy_config
from trade_helper.ledger import AccountSnapshot, Ledger, PositionSnapshot
from trade_helper.execution import Advice, ExecutionLedger
from trade_helper.models import Readiness
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

            model = DashboardRepository(database).load()

        self.assertTrue(model.has_account)
        self.assertEqual(Decimal("500000"), model.total_assets_cny)
        self.assertEqual(Decimal("350000"), model.cash_cny)
        self.assertEqual(Decimal("0.12"), model.assets[0].weight)
        self.assertEqual(Decimal("350000"), sum(value for _, value in model.cash_pools))
        self.assertEqual("ADV-1", model.open_advices[0].advice_id)
        self.assertEqual(0, model.open_advices[0].filled_quantity)
