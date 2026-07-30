from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.ledger import Ledger
from trade_helper.trading_calendar import CalendarDay, TradingCalendarStore


class TradingCalendarTests(TestCase):
    def test_explicit_calendar_counts_only_open_days(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "account.db")
            ledger.initialize()
            store = TradingCalendarStore(ledger)
            store.replace(
                (
                    CalendarDay(date(2026, 9, 1), True, "TEST"),
                    CalendarDay(date(2026, 9, 2), False, "TEST"),
                    CalendarDay(date(2026, 9, 3), True, "TEST"),
                )
            )
            self.assertEqual(2, store.trading_day_number(date(2026, 9, 3)))
            self.assertIsNone(store.trading_day_number(date(2026, 9, 2)))

    def test_missing_date_fails_instead_of_guessing_weekday(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "account.db")
            ledger.initialize()
            with self.assertRaises(ValueError):
                TradingCalendarStore(ledger).trading_day_number(date(2026, 9, 1))
