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
from trade_helper.strategy import BaseCandidate, BasePlanInput, TacticalInput


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
        DecisionStore(self.ledger).save(result, request, self.states)

        self.assertEqual(Decimal("12500"), self.states.load_runtime().base_budget.available_cny)
        self.assertEqual(1, self.ledger.count("decision_runs"))

    def test_market_block_precedes_strategy(self) -> None:
        request = self.request()
        blocked = replace(request.markets[0], readiness=Readiness.BLOCKED)
        result = run_daily_decision(
            self.config, self.runtime,
            replace(request, markets=(blocked, *request.markets[1:])),
        )
        self.assertEqual(DecisionStatus.BLOCKED, result.status)
        self.assertIn("市场数据质量阻断", result.reasons[0])
