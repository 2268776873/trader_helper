from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.config import load_strategy_config
from trade_helper.execution import Advice, ExecutionLedger
from trade_helper.ledger import Ledger
from trade_helper.shadow_run import build_shadow_report
from trade_helper.state_store import StrategyStateStore
from trade_helper.trading_calendar import CalendarDay, TradingCalendarStore


ROOT = Path(__file__).resolve().parents[1]


class ShadowRunReportTests(TestCase):
    def test_missing_database_is_not_created_by_report(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "missing.db"

            with self.assertRaises(FileNotFoundError):
                build_shadow_report(database)

            self.assertFalse(database.exists())

    def test_counts_distinct_days_and_unresolved_advice(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "account.db"
            ledger = Ledger(database)
            ledger.initialize()
            config = load_strategy_config(ROOT / "config" / "personal_v1.json")
            StrategyStateStore(ledger).save_config(config)
            start = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
            TradingCalendarStore(ledger).replace(
                tuple(
                    CalendarDay(
                        (start + timedelta(days=index)).date(),
                        True,
                        "TEST",
                    )
                    for index in range(20)
                )
            )
            with ledger.transaction() as connection:
                for index in range(20):
                    when = start + timedelta(days=index)
                    connection.execute(
                        """
                        INSERT INTO decision_runs(
                            decision_id, generated_at, config_version, status,
                            reasons_json, input_json, output_json
                        ) VALUES (?, ?, ?, 'NO_ACTION', '[]', '{}', '{}')
                        """,
                        (f"D-{index}", when.isoformat(), config.config_version),
                    )
            ExecutionLedger(ledger).create_advice(
                Advice(
                    "ADV-1", start, config.config_version, "SP500", "513500",
                    "BUY", 100, Decimal("2"), "test",
                )
            )

            report = build_shadow_report(
                database, now=start + timedelta(days=20)
            )

        self.assertTrue(report.coverage_completed)
        self.assertFalse(report.completed)
        self.assertEqual(20, report.observed_trading_days)
        self.assertEqual(20, report.ready_days)
        self.assertEqual(1, report.unresolved_advices)
        self.assertIn("1 advices remain unresolved", report.acceptance_issues)

    def test_excludes_missing_and_closed_calendar_dates(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "account.db"
            ledger = Ledger(database)
            ledger.initialize()
            config = load_strategy_config(ROOT / "config" / "personal_v1.json")
            StrategyStateStore(ledger).save_config(config)
            start = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
            TradingCalendarStore(ledger).replace(
                (
                    CalendarDay(start.date(), True, "TEST"),
                    CalendarDay(
                        (start + timedelta(days=1)).date(), False, "TEST"
                    ),
                )
            )
            with ledger.transaction() as connection:
                for index in range(3):
                    when = start + timedelta(days=index)
                    connection.execute(
                        """
                        INSERT INTO decision_runs(
                            decision_id, generated_at, config_version, status,
                            reasons_json, input_json, output_json
                        ) VALUES (?, ?, ?, 'NO_ACTION', '[]', '{}', '{}')
                        """,
                        (f"D-{index}", when.isoformat(), config.config_version),
                    )

            report = build_shadow_report(database, required_trading_days=2)

        self.assertFalse(report.completed)
        self.assertFalse(report.coverage_completed)
        self.assertEqual(1, report.observed_trading_days)
        self.assertEqual(
            ((start + timedelta(days=2)).date(),),
            report.missing_calendar_dates,
        )
        self.assertEqual(
            ((start + timedelta(days=1)).date(),),
            report.closed_dates_with_decisions,
        )

    def test_clean_coverage_passes_acceptance(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "account.db"
            ledger = Ledger(database)
            ledger.initialize()
            config = load_strategy_config(ROOT / "config" / "personal_v1.json")
            StrategyStateStore(ledger).save_config(config)
            start = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
            TradingCalendarStore(ledger).replace(
                tuple(
                    CalendarDay(
                        (start + timedelta(days=index)).date(),
                        True,
                        "MANUAL_CSV",
                    )
                    for index in range(20)
                )
            )
            with ledger.transaction() as connection:
                for index in range(20):
                    when = start + timedelta(days=index)
                    connection.execute(
                        """
                        INSERT INTO decision_runs(
                            decision_id, generated_at, config_version, status,
                            reasons_json, input_json, output_json
                        ) VALUES (?, ?, ?, 'NO_ACTION', '[]', '{}', '{}')
                        """,
                        (f"D-{index}", when.isoformat(), config.config_version),
                    )

            report = build_shadow_report(database)

        self.assertTrue(report.coverage_completed)
        self.assertTrue(report.completed)
        self.assertEqual((), report.acceptance_issues)

    def test_orphan_advice_date_fails_acceptance(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "account.db"
            ledger = Ledger(database)
            ledger.initialize()
            config = load_strategy_config(ROOT / "config" / "personal_v1.json")
            StrategyStateStore(ledger).save_config(config)
            when = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
            ExecutionLedger(ledger).create_advice(
                Advice(
                    "ADV-ORPHAN", when, config.config_version,
                    "SP500", "513500", "BUY", 100, Decimal("2"), "test",
                )
            )

            report = build_shadow_report(
                database, required_trading_days=1
            )

        self.assertFalse(report.completed)
        self.assertEqual((when.date(),), report.advice_dates_without_decisions)
