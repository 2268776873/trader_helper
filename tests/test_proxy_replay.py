import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.proxy_replay import convert_proxy_csv


class ProxyReplayTests(TestCase):
    def test_converts_index_fx_rows_and_writes_explicit_proxy_audit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            source.write_text(
                "trading_date,SP500_index,NASDAQ_index,DIVIDEND_index,USD_CNY\n"
                "2000-01-03,100,200,50,8\n"
                "2000-01-04,90,220,45,8.1\n",
                encoding="utf-8",
            )
            target = root / "replay.csv"
            result = convert_proxy_csv(
                source,
                target,
                source_notes="official index close and FX series; test fixture",
            )

            with target.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            audit = json.loads(Path(result.audit_path).read_text(encoding="utf-8"))

        self.assertEqual(2, result.rows)
        self.assertEqual("1", rows[0]["SP500_price"])
        self.assertEqual("PROXY", audit["kind"])
        self.assertIn("no ETF premium", audit["transformation"]["price_and_nav"])

    def test_rejects_missing_columns_and_out_of_order_dates(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bad.csv"
            source.write_text(
                "trading_date,SP500_index\n2000-01-02,1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "missing columns"):
                convert_proxy_csv(source, root / "out.csv", source_notes="x")
