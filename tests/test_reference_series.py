from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.ledger import Ledger, LedgerConflict
from trade_helper.reference_series import ReferencePoint, ReferenceSeriesStore


class ReferenceSeriesTests(TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        ledger = Ledger(Path(self.directory.name) / "account.db")
        ledger.initialize()
        self.store = ReferenceSeriesStore(ledger)
        self.now = datetime(2026, 7, 30, tzinfo=timezone.utc)

    def test_drawdown_uses_only_points_at_or_before_as_of(self) -> None:
        for offset, value in enumerate(("100", "120", "90", "200")):
            day = date(2026, 7, 1) + timedelta(days=offset)
            self.store.add(
                ReferencePoint("SP500", day, Decimal(value), "COMPOSITE", self.now)
            )

        result = self.store.drawdown("SP500", date(2026, 7, 3))

        self.assertEqual(Decimal("90"), result.current_value_cny)
        self.assertEqual(Decimal("120"), result.rolling_high_cny)
        self.assertEqual(Decimal("0.25"), result.drawdown)
        self.assertEqual(3, result.observations)

    def test_same_point_is_idempotent_but_changed_value_conflicts(self) -> None:
        point = ReferencePoint(
            "SP500", date(2026, 7, 1), Decimal("100"), "COMPOSITE", self.now
        )
        self.assertTrue(self.store.add(point))
        self.assertFalse(self.store.add(point))
        with self.assertRaises(LedgerConflict):
            self.store.add(
                ReferencePoint(
                    "SP500", point.trading_date, Decimal("101"),
                    point.source, self.now,
                )
            )
