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


ROOT = Path(__file__).resolve().parents[1]


class ShadowRunReportTests(TestCase):
    def test_counts_distinct_days_and_unresolved_advice(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "account.db"
            ledger = Ledger(database)
            ledger.initialize()
            config = load_strategy_config(ROOT / "config" / "personal_v1.json")
            StrategyStateStore(ledger).save_config(config)
            start = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
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

        self.assertTrue(report.completed)
        self.assertEqual(20, report.observed_trading_days)
        self.assertEqual(20, report.ready_days)
        self.assertEqual(1, report.unresolved_advices)
