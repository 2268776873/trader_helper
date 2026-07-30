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
