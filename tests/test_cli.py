import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from openpyxl import Workbook

from trade_helper.cli import main


class ExcelCliTests(TestCase):
    def test_preview_reports_missing_sheets_without_traceback(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "empty.xlsx"
            workbook = Workbook()
            workbook.save(path)
            workbook.close()
            output = StringIO()

            with redirect_stdout(output):
                result = main(["excel-preview", str(path)])

            payload = json.loads(output.getvalue())
            self.assertEqual(2, result)
            self.assertFalse(payload["valid"])
            self.assertEqual(4, len(payload["issues"]))


class CalendarCliTests(TestCase):
    CSV = Path(__file__).resolve().parents[1] / "data" / "calendar_2026.csv"

    def test_calendar_import_skips_when_date_already_present(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "account.db"
            output = StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "calendar-import", str(self.CSV),
                        "--database", str(database),
                        "--source", "SSE-2026",
                    ]
                )
            self.assertEqual(0, result)
            self.assertTrue(json.loads(output.getvalue())["ok"])

            output = StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "calendar-import", str(self.CSV),
                        "--database", str(database),
                        "--source", "SSE-2026",
                        "--if-missing-date", "2026-08-03",
                    ]
                )
            self.assertEqual(0, result)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["skipped"])
            self.assertIn("已包含", payload["reason"])

    def test_calendar_import_seeds_when_date_missing(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "account.db"
            output = StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "calendar-import", str(self.CSV),
                        "--database", str(database),
                        "--source", "SSE-2026",
                        "--if-missing-date", "2026-08-03",
                    ]
                )
            self.assertEqual(0, result)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(365, payload["rows"])
