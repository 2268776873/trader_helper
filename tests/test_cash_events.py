from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.cash_events import apply_account_cash_event
from trade_helper.config import load_strategy_config
from trade_helper.ledger import AccountSnapshot, Ledger, PositionSnapshot
from trade_helper.state_store import StrategyStateStore
from trade_helper.ui.view_model import DashboardRepository


ROOT = Path(__file__).resolve().parents[1]


class AccountCashEventTests(TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "account.db"
        self.ledger = Ledger(self.database)
        self.ledger.initialize()
        self.config = load_strategy_config(
            ROOT / "config" / "personal_v1.json"
        )
        StrategyStateStore(self.ledger).initialize_runtime(self.config)
        self.now = datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)
        self.ledger.add_snapshot(
            AccountSnapshot(
                "S-1", self.now, Decimal("500000"), Decimal("350000")
            ),
            (
                PositionSnapshot(
                    "S-1", "SP500", "513500", 24000, Decimal("60000")
                ),
                PositionSnapshot(
                    "S-1", "NASDAQ", "513100", 30000, Decimal("60000")
                ),
                PositionSnapshot(
                    "S-1", "DIVIDEND", "515450", 21000, Decimal("30000")
                ),
            ),
        )

    def test_deposit_and_withdrawal_replan_every_pool_atomically(self) -> None:
        deposited = apply_account_cash_event(
            self.database,
            event_id="FLOW-DEPOSIT",
            snapshot_id="S-2",
            occurred_at=self.now + timedelta(minutes=1),
            event_type="DEPOSIT",
            amount_cny=Decimal("10000"),
        )
        withdrawn = apply_account_cash_event(
            self.database,
            event_id="FLOW-WITHDRAW",
            snapshot_id="S-3",
            occurred_at=self.now + timedelta(minutes=2),
            event_type="WITHDRAWAL",
            amount_cny=Decimal("20000"),
        )

        self.assertEqual(
            Decimal("360000"), deposited.transition.after.total_cny
        )
        self.assertEqual(
            Decimal("340000"), withdrawn.transition.after.total_cny
        )
        self.assertEqual(Decimal("490000"), withdrawn.total_assets_cny)
        self.assertEqual(Decimal("340000"), withdrawn.available_cash_cny)
        self.assertEqual(2, self.ledger.count("cash_pool_events"))
        self.assertEqual(3, self.ledger.count("account_snapshots"))
        runtime = StrategyStateStore(self.ledger).load_runtime()
        self.assertEqual(
            Decimal("112000"), runtime.cash_pools.base_cny
        )
        history = DashboardRepository(self.database).load_history()
        self.assertTrue(any(item.category == "资金池" for item in history))

    def test_failed_withdrawal_rolls_back_all_ledgers(self) -> None:
        with self.assertRaises(ValueError):
            apply_account_cash_event(
                self.database,
                event_id="FLOW-FAIL",
                snapshot_id="S-FAIL",
                occurred_at=self.now + timedelta(minutes=1),
                event_type="WITHDRAWAL",
                amount_cny=Decimal("350001"),
            )

        self.assertEqual(0, self.ledger.count("cash_pool_events"))
        self.assertEqual(0, self.ledger.count("cash_flows"))
        self.assertEqual(1, self.ledger.count("account_snapshots"))
