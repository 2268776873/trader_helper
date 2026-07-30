from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zoneinfo import ZoneInfo

from trade_helper.config import load_strategy_config
from trade_helper.decision import DecisionStatus
from trade_helper.example_data import create_example_database
from trade_helper.ledger import Ledger
from trade_helper.ui.view_model import DashboardRepository


ROOT = Path(__file__).resolve().parents[1]


class ExampleDatabaseTests(TestCase):
    def test_example_account_completes_client_decision_walkthrough(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "example.db"
            outcome = create_example_database(
                database,
                load_strategy_config(ROOT / "config" / "personal_v1.json"),
                now=datetime(
                    2026, 9, 14, 14, 0,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            )
            ledger = Ledger(database)
            dashboard = DashboardRepository(database).load()

            self.assertEqual(DecisionStatus.READY, outcome.status)
            self.assertEqual(1, ledger.count("account_snapshots"))
            self.assertEqual(3, ledger.count("market_snapshots"))
            self.assertEqual(1, ledger.count("decision_runs"))
            self.assertTrue(dashboard.has_account)
            self.assertEqual(3, len(dashboard.assets))
            self.assertEqual(1, len(dashboard.open_advices))

    def test_example_database_never_overwrites_existing_file(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "example.db"
            database.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                create_example_database(
                    database,
                    load_strategy_config(ROOT / "config" / "personal_v1.json"),
                    now=datetime(
                        2026, 9, 14, 14, 0,
                        tzinfo=ZoneInfo("Asia/Shanghai"),
                    ),
                )
