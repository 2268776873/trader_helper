from datetime import datetime, timedelta, timezone
from unittest import TestCase

from trade_helper.feasibility import assess_quote, overall_readiness
from trade_helper.models import Quote, Readiness


class FeasibilityTests(TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)

    def quote(self, **overrides: object) -> Quote:
        values = {
            "symbol": "513500",
            "name": "标普500ETF",
            "observed_at": self.now,
            "last_price": 2.0,
            "bid1": 1.99,
            "ask1": 2.0,
            "iopv": 1.99,
            "source": "test",
        }
        values.update(overrides)
        return Quote(**values)

    def test_ready_requires_fresh_price_iopv_and_two_valuations(self) -> None:
        result = assess_quote(
            self.quote(),
            self.now,
            independent_valuation_count=2,
        )

        self.assertEqual(Readiness.READY, result.readiness)
        self.assertEqual((), result.reasons)

    def test_single_valuation_requires_manual_review(self) -> None:
        result = assess_quote(self.quote(), self.now)

        self.assertEqual(Readiness.REVIEW, result.readiness)

    def test_missing_iopv_requires_review_but_does_not_invent_value(self) -> None:
        result = assess_quote(
            self.quote(iopv=None),
            self.now,
            independent_valuation_count=1,
        )

        self.assertEqual(Readiness.REVIEW, result.readiness)
        self.assertIn("公开行情未提供已验证的IOPV", result.reasons)

    def test_stale_quote_blocks_advice(self) -> None:
        result = assess_quote(
            self.quote(observed_at=self.now - timedelta(minutes=6)),
            self.now,
            independent_valuation_count=2,
        )

        self.assertEqual(Readiness.BLOCKED, result.readiness)

    def test_overall_uses_most_conservative_state(self) -> None:
        ready = assess_quote(
            self.quote(),
            self.now,
            independent_valuation_count=2,
        )
        blocked = assess_quote(
            self.quote(last_price=None),
            self.now,
            independent_valuation_count=2,
        )

        self.assertEqual(Readiness.BLOCKED, overall_readiness([ready, blocked]))
