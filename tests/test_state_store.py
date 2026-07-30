from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.config import load_strategy_config
from trade_helper.ledger import Ledger, LedgerConflict
from trade_helper.state_store import StrategyStateStore
from trade_helper.strategy import BaseBudgetState


ROOT = Path(__file__).resolve().parents[1]


class StrategyStateStoreTests(TestCase):
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
