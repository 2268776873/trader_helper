import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from trade_helper.config import load_strategy_config
from trade_helper.replay_suite import (
    REQUIRED_SCENARIOS,
    _validate_scenario_period,
    run_replay_suite,
)


ROOT = Path(__file__).resolve().parents[1]


class ReplaySuiteTests(TestCase):
    def setUp(self) -> None:
        self.config = load_strategy_config(ROOT / "config" / "personal_v1.json")
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_requires_exact_mandatory_scenario_coverage(self) -> None:
        manifest = self.root / "suite.json"
        manifest.write_text(
            json.dumps(
                {
                    "scenarios": [
                        {
                            "scenario_id": "GFC_2008",
                            "input": "missing.csv",
                            "initial_account": "missing.json",
                            "source_notes": "test",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            run_replay_suite(manifest, self.config)

    def test_runs_all_scenarios_and_records_input_hashes(self) -> None:
        account = self.root / "account.json"
        account.write_text(
            json.dumps(
                {
                    "cash_cny": 350000,
                    "quantities": {
                        "SP500": 0,
                        "NASDAQ": 0,
                        "DIVIDEND": 0,
                    },
                }
            ),
            encoding="utf-8",
        )
        header = ["trading_date"]
        for asset_id in ("SP500", "NASDAQ", "DIVIDEND"):
            header.extend(
                [
                    f"{asset_id}_price",
                    f"{asset_id}_nav_1",
                    f"{asset_id}_nav_2",
                    f"{asset_id}_reference",
                ]
            )
        csv_text = ",".join(header) + "\n"
        csv_text += "2024-01-02," + ",".join(["1"] * 12) + "\n"
        csv_text += "2024-01-03," + ",".join(["1"] * 12) + "\n"
        scenarios = []
        for scenario_id in sorted(REQUIRED_SCENARIOS):
            input_path = self.root / f"{scenario_id}.csv"
            input_path.write_text(csv_text, encoding="utf-8")
            scenarios.append(
                {
                    "scenario_id": scenario_id,
                    "input": input_path.name,
                    "initial_account": account.name,
                    "source_notes": "synthetic unit-test fixture",
                }
            )
        manifest = self.root / "suite.json"
        manifest.write_text(
            json.dumps({"scenarios": scenarios}),
            encoding="utf-8",
        )

        with patch(
            "trade_helper.replay_suite._validate_scenario_period"
        ):
            result = run_replay_suite(manifest, self.config)
        payload = result.to_dict()

        self.assertTrue(payload["coverage"]["complete"])
        self.assertEqual(4, len(result.scenarios))
        self.assertTrue(
            all(len(item.input_sha256) == 64 for item in result.scenarios)
        )

    def test_source_notes_are_mandatory_for_auditability(self) -> None:
        scenarios = [
            {
                "scenario_id": scenario_id,
                "input": "missing.csv",
                "initial_account": "missing.json",
                "source_notes": "",
            }
            for scenario_id in sorted(REQUIRED_SCENARIOS)
        ]
        manifest = self.root / "suite.json"
        manifest.write_text(
            json.dumps({"scenarios": scenarios}),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "source_notes"):
            run_replay_suite(manifest, self.config)

    def test_rejects_short_or_wrong_historical_period(self) -> None:
        with self.assertRaisesRegex(ValueError, "coverage is insufficient"):
            _validate_scenario_period(
                "DOT_COM_2000",
                date(2024, 1, 1),
                date(2024, 1, 2),
                2,
            )
