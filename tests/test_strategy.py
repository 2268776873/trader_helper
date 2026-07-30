import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from trade_helper.config import load_strategy_config
from trade_helper.strategy import (
    BaseCandidate,
    BaseBudgetState,
    BasePlanInput,
    CycleState,
    RebalanceInput,
    TacticalInput,
    apply_fill,
    evaluate_base_plan,
    evaluate_rebalance,
    evaluate_tactical,
    plan_tactical_orders,
    release_monthly_base_budget,
    update_cycle,
)


class TacticalGoldenScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_strategy_config(Path("config/personal_v1.json"))

    def value(self, **changes):
        values = {
            "asset_id": "DIVIDEND",
            "total_assets_cny": Decimal("500000"),
            "cash_cny": Decimal("350000"),
            "position_value_cny": Decimal("30000"),
            "today_buy_cny": Decimal("0"),
            "drawdown": Decimal("0.0542"),
            "ask_price": Decimal("1.500"),
            "nav_estimate_1": Decimal("1.498"),
            "nav_estimate_2": Decimal("1.499"),
            "tactical_cash_cny": Decimal("50000"),
        }
        values.update(changes)
        return TacticalInput(**values)

    def test_dividend_first_level_generates_buy_order(self):
        advice = evaluate_tactical(self.config, self.value())
        self.assertEqual("BUY", advice.action)
        self.assertEqual("DV_L1", advice.level_id)
        self.assertEqual(6600, advice.quantity)
        self.assertEqual(Decimal("9900.00"), advice.amount_cny)

    def test_triggered_level_is_blocked_by_premium(self):
        advice = evaluate_tactical(
            self.config,
            self.value(
                asset_id="SP500",
                position_value_cny=Decimal("60000"),
                drawdown=Decimal("0.0932"),
                ask_price=Decimal("2.10"),
                nav_estimate_1=Decimal("2.00"),
                nav_estimate_2=Decimal("2.00"),
                tactical_cash_cny=Decimal("80000"),
            ),
        )
        self.assertEqual("BLOCKED", advice.action)
        self.assertEqual(("场内溢价超过档位上限",), advice.reasons)

    def test_disagreeing_valuations_block_order(self):
        advice = evaluate_tactical(
            self.config,
            self.value(nav_estimate_1=Decimal("1.45"), nav_estimate_2=Decimal("1.50")),
        )
        self.assertEqual("BLOCKED", advice.action)
        self.assertEqual(("估值源差异过大",), advice.reasons)

    def test_daily_limit_caps_order(self):
        advice = evaluate_tactical(
            self.config,
            self.value(today_buy_cny=Decimal("15000")),
        )
        self.assertEqual("BUY", advice.action)
        self.assertLessEqual(advice.amount_cny, Decimal("5000"))

    def test_cash_floor_blocks_order(self):
        advice = evaluate_tactical(
            self.config,
            self.value(cash_cny=Decimal("50500")),
        )
        self.assertEqual("BLOCKED", advice.action)

    def test_partial_fill_only_recommends_remaining_level_amount(self):
        advice = evaluate_tactical(
            self.config,
            self.value(level_filled_cny=(("DV_L1", Decimal("6000")),)),
        )
        self.assertEqual("BUY", advice.action)
        self.assertLessEqual(advice.amount_cny, Decimal("4000"))

    def test_deeper_level_waits_until_shallower_level_is_filled(self):
        advice = evaluate_tactical(
            self.config,
            self.value(
                drawdown=Decimal("0.16"),
                filled_levels=frozenset({"DV_L1"}),
            ),
        )
        self.assertEqual("DV_L2", advice.level_id)


class BasePlanGoldenScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_strategy_config(Path("config/personal_v1.json"))

    def candidate(self, asset_id, position, ask, nav):
        return BaseCandidate(
            asset_id=asset_id,
            position_value_cny=Decimal(position),
            ask_price=Decimal(ask),
            nav_estimate_1=Decimal(nav),
            nav_estimate_2=Decimal(nav),
        )

    def test_skips_largest_gap_when_premium_is_too_high(self):
        advice = evaluate_base_plan(
            self.config,
            BasePlanInput(
                total_assets_cny=Decimal("500000"),
                cash_cny=Decimal("350000"),
                base_pool_cny=Decimal("12500"),
                today_buy_cny=Decimal("0"),
                candidates=(
                    self.candidate("SP500", "60000", "2.10", "2.00"),
                    self.candidate("NASDAQ", "60000", "1.50", "1.49"),
                    self.candidate("DIVIDEND", "30000", "1.20", "1.20"),
                ),
            ),
        )
        self.assertEqual("DIVIDEND", advice.asset_id)
        self.assertEqual("BUY", advice.action)

    def test_half_budget_for_middle_premium_band(self):
        advice = evaluate_base_plan(
            self.config,
            BasePlanInput(
                total_assets_cny=Decimal("500000"),
                cash_cny=Decimal("350000"),
                base_pool_cny=Decimal("12500"),
                today_buy_cny=Decimal("0"),
                candidates=(
                    self.candidate("SP500", "60000", "2.03", "2.00"),
                    self.candidate("NASDAQ", "125000", "1.50", "1.50"),
                    self.candidate("DIVIDEND", "125000", "1.20", "1.20"),
                ),
            ),
        )
        self.assertEqual("SP500", advice.asset_id)
        self.assertLessEqual(advice.amount_cny, Decimal("6250"))

    def test_monthly_release_is_idempotent_and_carries_forward(self):
        state = BaseBudgetState(Decimal("12500"))
        released = release_monthly_base_budget(
            self.config, date(2026, 10, 16), 10, state
        )
        repeated = release_monthly_base_budget(
            self.config, date(2026, 10, 16), 10, released
        )
        self.assertEqual(Decimal("25000"), released.available_cny)
        self.assertEqual(released, repeated)

    def test_monthly_release_only_occurs_on_configured_trading_day(self):
        state = BaseBudgetState(Decimal("0"))
        unchanged = release_monthly_base_budget(
            self.config, date(2026, 9, 15), 9, state
        )
        self.assertEqual(state, unchanged)


class PortfolioOrderingGoldenScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_strategy_config(Path("config/personal_v1.json"))

    def test_deeper_trigger_is_evaluated_first(self):
        common = {
            "total_assets_cny": Decimal("500000"),
            "cash_cny": Decimal("350000"),
            "today_buy_cny": Decimal("0"),
            "ask_price": Decimal("1.50"),
            "nav_estimate_1": Decimal("1.50"),
            "nav_estimate_2": Decimal("1.50"),
        }
        orders = plan_tactical_orders(
            self.config,
            (
                TacticalInput(
                    asset_id="SP500", position_value_cny=Decimal("60000"),
                    drawdown=Decimal("0.09"), tactical_cash_cny=Decimal("80000"), **common
                ),
                TacticalInput(
                    asset_id="NASDAQ", position_value_cny=Decimal("60000"),
                    drawdown=Decimal("0.22"), tactical_cash_cny=Decimal("45000"), **common
                ),
            ),
        )
        self.assertEqual("NASDAQ", orders[0].asset_id)


class SellPolicyGoldenScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_strategy_config(Path("config/personal_v1.json"))

    def test_no_price_stop_loss(self):
        advice = evaluate_rebalance(
            self.config,
            RebalanceInput("SP500", Decimal("500000"), Decimal("200000"), Decimal("2.0")),
        )
        self.assertEqual("HOLD", advice.action)

    def test_persistent_overweight_sells_back_to_max_band(self):
        advice = evaluate_rebalance(
            self.config,
            RebalanceInput(
                "SP500", Decimal("500000"), Decimal("240000"), Decimal("2.0"),
                days_above_max=20,
            ),
        )
        self.assertEqual("SELL", advice.action)
        self.assertLessEqual(advice.amount_cny, Decimal("15000"))

    def test_structural_issue_requires_exit_review(self):
        advice = evaluate_rebalance(
            self.config,
            RebalanceInput(
                "NASDAQ", Decimal("500000"), Decimal("125000"), Decimal("1.5"),
                structural_issue=True,
            ),
        )
        self.assertEqual("REVIEW_EXIT", advice.action)


class StateMachineGoldenScenarioTests(unittest.TestCase):
    def test_partial_and_complete_fill(self):
        self.assertEqual(
            ("PARTIALLY_FILLED", Decimal("6000")),
            apply_fill(Decimal("10000"), Decimal("0"), Decimal("6000")),
        )
        self.assertEqual(
            ("FILLED", Decimal("10000")),
            apply_fill(Decimal("10000"), Decimal("6000"), Decimal("4000")),
        )

    def test_near_high_resets_only_after_twenty_days(self):
        state = CycleState(19, (("DV_L1", "FILLED"), ("DV_L2", "TRIGGERED")))
        reset = update_cycle(Decimal("0.019"), False, state)
        self.assertEqual(0, reset.near_high_days)
        self.assertEqual((("DV_L1", "ARMED"), ("DV_L2", "ARMED")), reset.level_statuses)

    def test_moving_away_from_high_clears_counter(self):
        state = CycleState(10, (("SP_L1", "FILLED"),))
        updated = update_cycle(Decimal("0.03"), False, state)
        self.assertEqual(0, updated.near_high_days)
        self.assertEqual(state.level_statuses, updated.level_statuses)


if __name__ == "__main__":
    unittest.main()
