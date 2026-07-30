import unittest
from decimal import Decimal
from pathlib import Path

from trade_helper.cash_management import (
    CashPools,
    apply_actual_cash_flow,
    buying_is_blocked,
)
from trade_helper.config import load_strategy_config


class CashManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_strategy_config(Path("config/personal_v1.json"))

    def pools(self):
        return CashPools(
            Decimal("125000"),
            Decimal("80000"),
            Decimal("45000"),
            Decimal("50000"),
            Decimal("50000"),
        )

    def test_actual_deposit_is_allocated_by_frozen_ratios(self):
        updated = apply_actual_cash_flow(self.config, self.pools(), Decimal("10000"))
        self.assertEqual(Decimal("132000.0"), updated.base_cny)
        self.assertEqual(Decimal("81350.0000"), updated.tactical_sp_cny)
        self.assertEqual(Decimal("45750.0000"), updated.tactical_nd_cny)
        self.assertEqual(Decimal("50900.0000"), updated.tactical_dv_cny)
        self.assertEqual(Decimal("360000.0000"), updated.total_cny)

    def test_withdrawal_uses_base_pool_first(self):
        updated = apply_actual_cash_flow(self.config, self.pools(), Decimal("-20000"))
        self.assertEqual(Decimal("105000"), updated.base_cny)
        self.assertEqual(Decimal("50000"), updated.strategic_cny)

    def test_large_withdrawal_eventually_reduces_strategic_cash_and_blocks_buying(self):
        updated = apply_actual_cash_flow(self.config, self.pools(), Decimal("-310000"))
        self.assertEqual(Decimal("40000"), updated.total_cny)
        self.assertTrue(buying_is_blocked(self.config, updated))

    def test_cannot_withdraw_more_than_strategy_cash(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            apply_actual_cash_flow(self.config, self.pools(), Decimal("-350001"))


if __name__ == "__main__":
    unittest.main()
