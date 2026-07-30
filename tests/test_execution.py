from datetime import datetime, timezone
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.config import load_strategy_config
from trade_helper.execution import (
    Advice,
    AdviceStatus,
    ExecutionLedger,
    Fill,
    OrderAttempt,
)
from trade_helper.ledger import Ledger
from trade_helper.state_store import StrategyStateStore
from trade_helper.strategy import BaseBudgetState


ROOT = Path(__file__).resolve().parents[1]


class ExecutionLedgerTests(TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        ledger = Ledger(Path(self.directory.name) / "account.db")
        ledger.initialize()
        self.ledger = ledger
        self.execution = ExecutionLedger(ledger)
        self.now = datetime(2026, 7, 30, 6, 0, tzinfo=timezone.utc)
        self.execution.create_advice(
            Advice(
                "ADV-1", self.now, "personal-v1", "DIVIDEND", "515450",
                "BUY", 1000, Decimal("1.500"), "DV_L1",
            )
        )

    def test_advice_and_attempt_do_not_create_a_trade(self) -> None:
        self.execution.record_attempt(
            OrderAttempt(
                "ATT-1", "ADV-1", self.now, AdviceStatus.ORDER_SUBMITTED
            )
        )

        self.assertEqual(AdviceStatus.ORDER_SUBMITTED, self.execution.status("ADV-1"))
        self.assertEqual(0, self.ledger.count("trades"))

    def test_partial_and_full_fills_create_only_actual_trades(self) -> None:
        self.execution.record_attempt(
            OrderAttempt(
                "ATT-1", "ADV-1", self.now, AdviceStatus.ORDER_SUBMITTED
            )
        )
        first = self.execution.record_fill(
            Fill("FILL-1", "ADV-1", self.now, 400, Decimal("1.498"), "ATT-1")
        )
        second = self.execution.record_fill(
            Fill("FILL-2", "ADV-1", self.now, 600, Decimal("1.497"), "ATT-1")
        )

        self.assertEqual(AdviceStatus.PARTIALLY_FILLED, first)
        self.assertEqual(AdviceStatus.FILLED, second)
        self.assertEqual(2, self.ledger.count("trades"))

    def test_fill_cannot_exceed_advice(self) -> None:
        with self.assertRaises(ValueError):
            self.execution.record_fill(
                Fill("FILL-X", "ADV-1", self.now, 1100, Decimal("1.498"))
            )
        self.assertEqual(0, self.ledger.count("trades"))

    def test_tactical_fill_atomically_updates_pool_and_level_state(self) -> None:
        config = load_strategy_config(ROOT / "config" / "personal_v1.json")
        store = StrategyStateStore(self.ledger)
        initial = store.initialize_runtime(config)
        self.execution.create_advice(
            Advice(
                "ADV-TACTICAL", self.now, config.config_version,
                "DIVIDEND", "515450", "BUY", 5000, Decimal("2"),
                "tactical test", "DV_L1", "TACTICAL",
            )
        )

        self.execution.record_fill(
            Fill(
                "FILL-TACTICAL-1", "ADV-TACTICAL", self.now,
                2000, Decimal("2"),
            )
        )
        partial = store.load_runtime()
        level = next(
            item
            for item in partial.tactical_levels
            if item.asset_id == "DIVIDEND" and item.level_id == "DV_L1"
        )
        self.assertEqual("PARTIALLY_FILLED", level.status)
        self.assertEqual(Decimal("4000"), level.filled_cny)
        self.assertEqual(
            initial.cash_pools.tactical_dv_cny - Decimal("4000"),
            partial.cash_pools.tactical_dv_cny,
        )

        self.execution.record_fill(
            Fill(
                "FILL-TACTICAL-2", "ADV-TACTICAL", self.now,
                3000, Decimal("2"),
            )
        )
        completed = store.load_runtime()
        level = next(
            item
            for item in completed.tactical_levels
            if item.asset_id == "DIVIDEND" and item.level_id == "DV_L1"
        )
        self.assertEqual("FILLED", level.status)
        self.assertEqual(Decimal("10000"), level.filled_cny)

    def test_base_fill_updates_released_budget_and_base_pool(self) -> None:
        config = load_strategy_config(ROOT / "config" / "personal_v1.json")
        store = StrategyStateStore(self.ledger)
        initial = store.initialize_runtime(config)
        released = replace(
            initial,
            base_budget=BaseBudgetState(
                Decimal("12500"), frozenset({"2026-09"})
            ),
        )
        store.save_runtime(released)
        self.execution.create_advice(
            Advice(
                "ADV-BASE", self.now, config.config_version,
                "SP500", "513500", "BUY", 2500, Decimal("2"),
                "base test", None, "BASE",
            )
        )

        self.execution.record_fill(
            Fill("FILL-BASE", "ADV-BASE", self.now, 2500, Decimal("2"))
        )

        completed = store.load_runtime()
        self.assertEqual(Decimal("7500"), completed.base_budget.available_cny)
        self.assertEqual(
            initial.cash_pools.base_cny - Decimal("5000"),
            completed.cash_pools.base_cny,
        )

    def test_sell_fill_adds_actual_proceeds_to_strategic_cash(self) -> None:
        config = load_strategy_config(ROOT / "config" / "personal_v1.json")
        store = StrategyStateStore(self.ledger)
        initial = store.initialize_runtime(config)
        self.execution.create_advice(
            Advice(
                "ADV-SELL", self.now, config.config_version,
                "SP500", "513500", "SELL", 1000, Decimal("2"),
                "rebalance test", None, "STRATEGIC",
            )
        )

        self.execution.record_fill(
            Fill("FILL-SELL", "ADV-SELL", self.now, 400, Decimal("2.01"))
        )

        updated = store.load_runtime()
        self.assertEqual(
            initial.cash_pools.strategic_cny + Decimal("804"),
            updated.cash_pools.strategic_cny,
        )
        self.assertEqual(1, self.ledger.count("cash_pool_events"))
