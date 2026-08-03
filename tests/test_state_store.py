from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.config import load_strategy_config
from trade_helper.ledger import AccountSnapshot, Ledger, LedgerConflict
from trade_helper.state_store import StrategyStateStore
from trade_helper.strategy import BaseBudgetState


ROOT = Path(__file__).resolve().parents[1]


class StrategyStateStoreTests(TestCase):
    def test_initial_runtime_reconciles_to_real_account_cash(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "account.db")
            ledger.initialize()
            config = load_strategy_config(ROOT / "config" / "personal_v1.json")

            state = StrategyStateStore(ledger).initialize_runtime(
                config, cash_total_cny=Decimal("350123.45")
            )

            self.assertEqual(Decimal("350123.45"), state.cash_pools.total_cny)

    def test_initial_runtime_reads_latest_account_cash_by_default(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "account.db")
            ledger.initialize()
            ledger.add_snapshot(
                AccountSnapshot(
                    "SNAP-1",
                    datetime(2026, 8, 3, 15, 6, tzinfo=timezone.utc),
                    Decimal("350123.45"),
                    Decimal("350123.45"),
                    Decimal("0"),
                    "TEST",
                ),
                (),
            )
            config = load_strategy_config(ROOT / "config" / "personal_v1.json")

            state = StrategyStateStore(ledger).initialize_runtime(config)

            self.assertEqual(Decimal("350123.45"), state.cash_pools.total_cny)

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        ledger = Ledger(Path(self.directory.name) / "account.db")
        ledger.initialize()
        self.store = StrategyStateStore(ledger)
        self.config = load_strategy_config(ROOT / "config" / "personal_v1.json")

    def test_initializes_and_survives_reload(self) -> None:
        initial = self.store.initialize_runtime(self.config)
        changed = replace(
            initial,
            base_budget=BaseBudgetState(
                Decimal("12500"), frozenset({"2026-09"})
            ),
            tactical_levels=(
                replace(
                    initial.tactical_levels[0],
                    status="PARTIALLY_FILLED",
                    filled_cny=Decimal("6000"),
                ),
                *initial.tactical_levels[1:],
            ),
        )
        self.store.save_runtime(changed)

        loaded = self.store.load_runtime()

        self.assertEqual(changed, loaded)
        self.assertEqual(Decimal("350000"), loaded.cash_pools.total_cny)

    def test_config_version_is_immutable(self) -> None:
        self.assertTrue(self.store.save_config(self.config))
        self.assertFalse(self.store.save_config(self.config))
        changed_raw = dict(self.config.raw)
        changed_raw["status"] = "RETIRED"

        with self.assertRaises(LedgerConflict):
            self.store.save_config(replace(self.config, raw=changed_raw))
