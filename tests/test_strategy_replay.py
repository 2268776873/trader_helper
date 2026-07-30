from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import TestCase

from trade_helper.config import load_strategy_config
from trade_helper.strategy_replay import (
    HistoricalAssetInput,
    HistoricalTradingDay,
    ReplayInitialAccount,
    run_strategy_replay,
)


ROOT = Path(__file__).resolve().parents[1]


class StrategyReplayTests(TestCase):
    def setUp(self) -> None:
        self.config = load_strategy_config(ROOT / "config" / "personal_v1.json")
        self.initial = ReplayInitialAccount(
            Decimal("350000"),
            {asset.asset_id: 0 for asset in self.config.assets},
        )

    def day(
        self,
        offset: int,
        *,
        references: dict[str, str] | None = None,
    ) -> HistoricalTradingDay:
        references = references or {}
        return HistoricalTradingDay(
            date(2024, 1, 2) + timedelta(days=offset),
            {
                asset.asset_id: HistoricalAssetInput(
                    Decimal("1"),
                    Decimal("1"),
                    Decimal("1"),
                    Decimal(references.get(asset.asset_id, "1")),
                )
                for asset in self.config.assets
            },
        )

    def test_drawdown_executes_real_strategy_and_preserves_cash_identity(self) -> None:
        days = (
            self.day(0),
            self.day(1, references={"DIVIDEND": "0.94"}),
            self.day(2, references={"DIVIDEND": "0.93"}),
        )

        result = run_strategy_replay(self.config, days, self.initial)

        self.assertEqual(3, len(result.points))
        self.assertGreater(result.points[1].traded_value_cny, Decimal("0"))
        self.assertTrue(
            any("BUY:DIVIDEND" in action for action in result.days[1].actions)
        )
        self.assertEqual(
            Decimal("350000"),
            result.points[1].portfolio_value_cny,
        )
        self.assertEqual(
            result.points[1].portfolio_value_cny
            - result.points[1].cash_cny,
            result.points[1].traded_value_cny,
        )

    def test_future_rows_cannot_change_earlier_results(self) -> None:
        baseline = (self.day(0), self.day(1), self.day(2))
        changed = baseline[:-1] + (
            self.day(
                2,
                references={
                    "SP500": "0.5",
                    "NASDAQ": "0.5",
                    "DIVIDEND": "0.5",
                },
            ),
        )

        first = run_strategy_replay(self.config, baseline, self.initial)
        second = run_strategy_replay(self.config, changed, self.initial)

        self.assertEqual(first.days[:2], second.days[:2])
        self.assertEqual(first.points[:2], second.points[:2])

    def test_persistent_overweight_sells_into_strategic_cash(self) -> None:
        days = tuple(self.day(offset) for offset in range(25))
        initial = replace(
            self.initial,
            quantities={"SP500": 600000, "NASDAQ": 0, "DIVIDEND": 0},
        )

        result = run_strategy_replay(self.config, days, initial)

        sell_days = [
            item
            for item in result.days
            if any(action.startswith("SELL:SP500") for action in item.actions)
        ]
        self.assertTrue(sell_days)
        self.assertGreater(sell_days[0].cash_cny, initial.cash_cny)

    def test_dates_must_be_unique_and_increasing(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            run_strategy_replay(
                self.config,
                (self.day(1), self.day(0)),
                self.initial,
            )

    def test_direct_initial_account_rejects_non_board_lot(self) -> None:
        invalid = replace(
            self.initial,
            quantities={"SP500": 1, "NASDAQ": 0, "DIVIDEND": 0},
        )

        with self.assertRaisesRegex(ValueError, "board lots"):
            run_strategy_replay(
                self.config,
                (self.day(0), self.day(1)),
                invalid,
            )
