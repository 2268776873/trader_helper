from datetime import date
from decimal import Decimal
from unittest import TestCase

from trade_helper.replay import (
    ReplayPoint, SensitivityVariant, calculate_replay_metrics,
    compare_sensitivity,
)


class ReplayMetricsTests(TestCase):
    def test_reports_full_required_metric_set_without_lookahead(self) -> None:
        metrics = calculate_replay_metrics(
            (
                ReplayPoint(date(2026, 1, 1), Decimal("100"), Decimal("20")),
                ReplayPoint(
                    date(2026, 1, 2), Decimal("120"), Decimal("18"), Decimal("10")
                ),
                ReplayPoint(
                    date(2026, 1, 3), Decimal("90"), Decimal("15"), Decimal("5")
                ),
                ReplayPoint(date(2026, 1, 4), Decimal("110"), Decimal("16")),
            )
        )

        self.assertEqual(Decimal("0.1"), metrics.total_return)
        self.assertEqual(Decimal("0.25"), metrics.maximum_drawdown)
        self.assertEqual(Decimal("15"), metrics.minimum_cash_cny)
        self.assertGreater(metrics.turnover_ratio, 0)
        self.assertGreater(metrics.annualized_volatility, 0)

    def test_rejects_duplicate_dates(self) -> None:
        with self.assertRaises(ValueError):
            calculate_replay_metrics(
                (
                    ReplayPoint(date(2026, 1, 1), Decimal("100"), Decimal("20")),
                    ReplayPoint(date(2026, 1, 1), Decimal("101"), Decimal("20")),
                )
            )

    def test_sensitivity_keeps_full_metrics_and_requires_baseline(self) -> None:
        first = calculate_replay_metrics(
            (
                ReplayPoint(date(2026, 1, 1), Decimal("100"), Decimal("20")),
                ReplayPoint(date(2026, 1, 2), Decimal("101"), Decimal("19")),
            )
        )
        second = calculate_replay_metrics(
            (
                ReplayPoint(date(2026, 1, 1), Decimal("100"), Decimal("30")),
                ReplayPoint(
                    date(2026, 1, 2), Decimal("99"), Decimal("28"), Decimal("5")
                ),
            )
        )
        report = compare_sensitivity(
            (
                SensitivityVariant("personal-v1", first),
                SensitivityVariant("variant-a", second),
            ),
            baseline="personal-v1",
        )
        self.assertEqual("personal-v1", report.baseline)
        self.assertGreater(report.annualized_return_range, 0)
        self.assertIn("maximum_drawdown", report.to_dict()["ranges"])
