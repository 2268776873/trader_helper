from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.config import load_strategy_config
from trade_helper.doctor import run_doctor
from trade_helper.ledger import Ledger
from trade_helper.state_store import StrategyStateStore


ROOT = Path(__file__).resolve().parents[1]


class DoctorTests(TestCase):
    def test_missing_database_fails_cleanly(self) -> None:
        with TemporaryDirectory() as directory:
            report = run_doctor(
                Path(directory) / "missing.db",
                ROOT / "config" / "personal_v1.json",
            )
        self.assertFalse(report.ready)
        self.assertEqual("FAIL", report.checks[-1].status)

    def test_initialized_runtime_passes_required_checks(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "account.db"
            ledger = Ledger(database)
            ledger.initialize()
            config_path = ROOT / "config" / "personal_v1.json"
            StrategyStateStore(ledger).initialize_runtime(
                load_strategy_config(config_path)
            )
            report = run_doctor(database, config_path)

        self.assertTrue(report.ready)
        self.assertFalse(any(item.status == "FAIL" for item in report.checks))
