from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zoneinfo import ZoneInfo

from trade_helper.config import load_strategy_config
from trade_helper.decision import (
    DecisionRequest,
    DecisionStatus,
    DecisionStore,
    run_daily_decision,
)
from trade_helper.ledger import Ledger
from trade_helper.market_data import MarketSnapshot
from trade_helper.models import Readiness
from trade_helper.state_store import StrategyStateStore
from trade_helper.strategy import (
    BaseCandidate, BasePlanInput, RebalanceInput, TacticalInput,
)


ROOT = Path(__file__).resolve().parents[1]


class DecisionTests(TestCase):
    def setUp(self) -> None:
        self.config = load_strategy_config(ROOT / "config" / "personal_v1.json")
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = Ledger(Path(self.directory.name) / "account.db")
        self.ledger.initialize()
        self.states = StrategyStateStore(self.ledger)
        self.runtime = self.states.initialize_runtime(self.config)
        self.now = datetime(2026, 9, 14, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    def markets(self) -> tuple[MarketSnapshot, ...]:
        return tuple(
            MarketSnapshot(
                f"MKT-{asset.etf_code}", asset.etf_code, self.now,
                Readiness.READY, (), (), (), Decimal("2"), Decimal("2"),
            )
            for asset in self.config.assets
        )

    def request(self, *, reconciled: bool = True) -> DecisionRequest:
        tactical = tuple(
            TacticalInput(
                asset.asset_id, Decimal("500000"), Decimal("350000"),
                Decimal("60000"), Decimal("0"), Decimal("0"),
                Decimal("2"), Decimal("2"), Decimal("2"),
                Decimal("50000"),
            )
            for asset in self.config.assets
        )
        base = BasePlanInput(
            Decimal("500000"), Decimal("350000"), Decimal("0"), Decimal("0"),
            tuple(
                BaseCandidate(
                    asset.asset_id, Decimal("60000"), Decimal("2"),
                    Decimal("2"), Decimal("2"),
                )
                for asset in self.config.assets
            ),
        )
        return DecisionRequest(
            "DEC-1", self.now, reconciled, 10, self.markets(), tactical, base
        )

    def test_reconciliation_blocks_every_advice(self) -> None:
        result = run_daily_decision(
            self.config, self.runtime, self.request(reconciled=False)
        )
        self.assertEqual(DecisionStatus.BLOCKED, result.status)
        self.assertEqual((), result.advices)

    def test_monthly_release_and_audit_are_persisted(self) -> None:
        request = self.request()
        result = run_daily_decision(self.config, self.runtime, request)
        DecisionStore(self.ledger).save(
            result, request, self.states, self.config
        )

        self.assertEqual(Decimal("12500"), self.states.load_runtime().base_budget.available_cny)
        self.assertEqual(1, self.ledger.count("decision_runs"))
        self.assertEqual(1, self.ledger.count("advice"))
        connection = self.ledger.connect()
        try:
            advice = connection.execute(
                "SELECT level_id, funding_pool FROM advice"
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNone(advice["level_id"])
        self.assertEqual("BASE", advice["funding_pool"])

    def test_market_block_precedes_strategy(self) -> None:
        request = self.request()
        blocked = replace(request.markets[0], readiness=Readiness.BLOCKED)
        result = run_daily_decision(
            self.config, self.runtime,
            replace(request, markets=(blocked, *request.markets[1:])),
        )
        self.assertEqual(DecisionStatus.BLOCKED, result.status)
        self.assertIn("市场数据质量阻断", result.reasons[0])

    def test_twentieth_near_high_day_resets_filled_cycle_once(self) -> None:
        changed_levels = tuple(
            replace(
                item,
                status="FILLED" if item.asset_id == "SP500" else item.status,
                filled_cny=(
                    Decimal("10000")
                    if item.asset_id == "SP500" else item.filled_cny
                ),
                near_high_days=19 if item.asset_id == "SP500" else 0,
            )
            for item in self.runtime.tactical_levels
        )
        runtime = replace(self.runtime, tactical_levels=changed_levels)
        request = self.request()
        tactical = tuple(
            replace(item, drawdown=Decimal("0.01"))
            if item.asset_id == "SP500" else item
            for item in request.tactical_inputs
        )

        reset = run_daily_decision(
            self.config, runtime, replace(request, tactical_inputs=tactical)
        )
        sp_levels = tuple(
            item
            for item in reset.runtime.tactical_levels
            if item.asset_id == "SP500"
        )
        self.assertTrue(all(item.status == "ARMED" for item in sp_levels))
        self.assertTrue(all(item.filled_cny == 0 for item in sp_levels))
        self.assertTrue(all(item.near_high_days == 0 for item in sp_levels))

        unchanged = run_daily_decision(
            self.config,
            runtime,
            replace(
                request, tactical_inputs=tactical, advance_cycle=False
            ),
        )
        sp_levels = tuple(
            item
            for item in unchanged.runtime.tactical_levels
            if item.asset_id == "SP500"
        )
        self.assertTrue(all(item.near_high_days == 19 for item in sp_levels))

    def test_hard_overweight_generates_audited_strategic_sell(self) -> None:
        request = self.request()
        rebalance = RebalanceInput(
            "SP500", Decimal("500000"), Decimal("260000"),
            Decimal("2"), 1,
        )

        result = run_daily_decision(
            self.config,
            self.runtime,
            replace(request, rebalance_inputs=(rebalance,)),
        )
        sell = next(item for item in result.advices if item.action == "SELL")
        self.assertEqual("SP500", sell.asset_id)
        self.assertEqual(17500, sell.quantity)
        DecisionStore(self.ledger).save(
            result,
            replace(request, rebalance_inputs=(rebalance,)),
            self.states,
            self.config,
        )
        connection = self.ledger.connect()
        try:
            saved = connection.execute(
                """
                SELECT side, funding_pool FROM advice
                WHERE side = 'SELL'
                """
            ).fetchone()
            rebalance_state = connection.execute(
                """
                SELECT days_above_max FROM rebalance_state
                WHERE asset_id = 'SP500'
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual("STRATEGIC", saved["funding_pool"])
        self.assertEqual(1, rebalance_state["days_above_max"])
