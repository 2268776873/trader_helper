import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.config import ConfigError, load_strategy_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StrategyConfigTests(TestCase):
    def test_personal_v1_is_internally_consistent(self) -> None:
        config = load_strategy_config(PROJECT_ROOT / "config" / "personal_v1.json")

        self.assertEqual("personal-v1", config.config_version)
        self.assertEqual("ACTIVE", config.status)
        self.assertEqual(3, len(config.assets))
        self.assertEqual(Decimal("0.40"), config.assets[0].target_weight)
        self.assertFalse(config.raw["execution"]["include_commission"])
        self.assertTrue(
            config.raw["contributions"]["actual_cash_flows_are_authoritative"]
        )
        self.assertEqual(
            "SYSTEM_VIRTUAL_LEDGER",
            config.raw["cash"]["internal_pool_management"],
        )
        self.assertEqual(
            "MANUAL_STRATEGY_REVIEW_REQUIRED",
            config.raw["cash"]["equity_sale_for_withdrawal"],
        )

    def test_rejects_target_weights_that_do_not_total_one(self) -> None:
        source = json.loads(
            (PROJECT_ROOT / "config" / "personal_v1.json").read_text(encoding="utf-8")
        )
        source["cash"]["target_weight"] = 0.20

        with TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "target weights"):
                load_strategy_config(path)

    def test_rejects_cash_pools_that_do_not_match_cash(self) -> None:
        source = json.loads(
            (PROJECT_ROOT / "config" / "personal_v1.json").read_text(encoding="utf-8")
        )
        source["cash_pools"]["base_pool_cny"] = 1

        with TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "cash pools"):
                load_strategy_config(path)
