from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from trade_helper.config import load_strategy_config
from trade_helper.ledger import Ledger
from trade_helper.release_readiness import build_release_readiness
from trade_helper.state_store import StrategyStateStore
from trade_helper.trading_calendar import CalendarDay, TradingCalendarStore


ROOT = Path(__file__).resolve().parents[1]


class ReleaseReadinessTests(TestCase):
    def test_automated_gates_pass_but_manual_gates_remain_explicit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "account.db"
            ledger = Ledger(database)
            ledger.initialize()
            config_path = ROOT / "config" / "personal_v1.json"
            config = load_strategy_config(config_path)
            StrategyStateStore(ledger).initialize_runtime(config)
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

            with patch(
                "trade_helper.release_readiness.run_replay_suite",
                return_value=SimpleNamespace(
                    scenarios=(1, 2, 3, 4),
                    to_dict=lambda: {
                        "coverage": {"complete": True}
                    },
                ),
            ):
                report = build_release_readiness(
                    database, config_path, root / "suite.json"
                )

        self.assertTrue(report.automated_ready, report.gates)
        self.assertTrue(report.manual_gates)
        self.assertFalse(report.to_dict()["release_ready"])

    def test_missing_replay_inputs_become_a_failed_gate(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "account.db"
            ledger = Ledger(database)
            ledger.initialize()
            config_path = ROOT / "config" / "personal_v1.json"
            StrategyStateStore(ledger).initialize_runtime(
                load_strategy_config(config_path)
            )

            report = build_release_readiness(
                database, config_path, root / "missing.json"
            )

        replay_gate = next(
            item for item in report.gates
            if item.name == "historical_replay"
        )
        self.assertFalse(replay_gate.passed)

    def test_missing_database_is_reported_without_being_created(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "missing.db"

            report = build_release_readiness(
                database,
                ROOT / "config" / "personal_v1.json",
                root / "missing-suite.json",
            )

        self.assertFalse(report.automated_ready)
        self.assertFalse(database.exists())
