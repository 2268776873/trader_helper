from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.ledger import Ledger
from trade_helper.trading_calendar import (
    CalendarDay,
    TradingCalendarStore,
    load_calendar_csv,
)


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


class Bundled2026CalendarTests(TestCase):
    CSV = Path(__file__).resolve().parents[1] / "data" / "calendar_2026.csv"

    def test_bundled_csv_has_full_year_and_key_dates(self) -> None:
        days = load_calendar_csv(self.CSV, "SSE-2026")
        self.assertEqual(365, len(days))
        by_date = {item.trading_date: item.is_open for item in days}
        closed = [
            "2026-01-01", "2026-01-02", "2026-01-03",
            "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-23",
            "2026-04-04", "2026-04-05", "2026-04-06",
            "2026-05-01", "2026-05-05",
            "2026-06-19", "2026-06-20", "2026-06-21",
            "2026-09-25", "2026-09-26", "2026-09-27",
            "2026-10-01", "2026-10-07",
        ]
        for value in closed:
            self.assertFalse(by_date[date.fromisoformat(value)], value)
        for value in [
            "2026-01-05", "2026-02-24", "2026-04-07",
            "2026-05-06", "2026-06-22", "2026-09-28",
            "2026-10-08", "2026-08-03", "2026-07-31",
        ]:
            self.assertTrue(by_date[date.fromisoformat(value)], value)

    def test_imported_bundled_calendar_counts_open_days(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "account.db")
            ledger.initialize()
            days = load_calendar_csv(self.CSV, "SSE-2026")
            TradingCalendarStore(ledger).replace(days)
            store = TradingCalendarStore(ledger)
            self.assertEqual(1, store.trading_day_number(date(2026, 8, 3)))
            self.assertEqual(1, store.trading_day_number(date(2026, 1, 5)))
            self.assertIsNone(store.trading_day_number(date(2026, 1, 1)))
            self.assertIsNone(store.trading_day_number(date(2026, 10, 7)))
