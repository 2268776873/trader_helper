import csv
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from trade_helper.proxy_sources import _parse_fred, _parse_yahoo, build_proxy_source_csv


class ProxySourceTests(TestCase):
    def test_parses_yahoo_and_fred_series(self) -> None:
        yahoo = {
            "chart": {
                "error": None,
                "result": [
                    {
                        "timestamp": [946684800, 946771200],
                        "indicators": {"quote": [{"close": [1, 2]}]},
                    }
                ],
            }
        }
        self.assertEqual(2, len(_parse_yahoo(yahoo)))
        fred = "observation_date,DEXCHUS\n2000-01-03,8.2\n2000-01-04,.\n"
        self.assertEqual({date(2000, 1, 3)}, set(_parse_fred(fred)))

    def test_builds_common_source_csv_and_hash_manifest(self) -> None:
        payloads = {
            "yahoo:^GSPC": {
                "chart": {"error": None, "result": [{"timestamp": [946684800, 946771200], "indicators": {"quote": [{"close": [1, 2]}]}}]}
            },
            "yahoo:^NDX": {
                "chart": {"error": None, "result": [{"timestamp": [946684800, 946771200], "indicators": {"quote": [{"close": [3, 4]}]}}]}
            },
            "yahoo:000001.SS": {
                "chart": {"error": None, "result": [{"timestamp": [946684800, 946771200], "indicators": {"quote": [{"close": [5, 6]}]}}]}
            },
        }
        fred = b"observation_date,DEXCHUS\n2000-01-01,8\n2000-01-02,8.1\n"
        def fake_download(url: str, timeout_seconds: int) -> bytes:
            if "fred" in url:
                return fred
            symbol = url.split("/chart/")[1].split("?")[0]
            symbol = {"%5EGSPC": "yahoo:^GSPC", "%5ENDX": "yahoo:^NDX"}.get(symbol, "yahoo:000001.SS")
            return json.dumps(payloads[symbol]).encode()

        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("trade_helper.proxy_sources._download", side_effect=fake_download):
                result = build_proxy_source_csv(
                    root / "raw.csv",
                    start_date=date(2000, 1, 1),
                    end_date=date(2000, 1, 10),
                    source_dir=root / "sources",
                )
            self.assertEqual(2, result.rows)
            audit = json.loads(Path(result.audit_json).read_text(encoding="utf-8"))
            self.assertEqual("PROXY_SOURCE_RAW", audit["kind"])
            self.assertEqual(64, len(audit["sources"][0]["sha256"]))

    def test_alignment_uses_prior_value_on_market_holiday(self) -> None:
        payloads = {
            "yahoo:^GSPC": [1, 2],
            "yahoo:^NDX": [1, 2],
            "yahoo:000001.SS": [5],
        }
        def fake_download(url: str, timeout_seconds: int) -> bytes:
            if "fred" in url:
                return b"observation_date,DEXCHUS\n2000-01-01,8\n2000-01-02,8.1\n"
            symbol = url.split("/chart/")[1].split("?")[0]
            key = {"%5EGSPC": "yahoo:^GSPC", "%5ENDX": "yahoo:^NDX"}.get(
                symbol, "yahoo:000001.SS"
            )
            timestamps = [946684800, 946771200]
            closes = payloads[key]
            return json.dumps(
                {
                    "chart": {
                        "error": None,
                        "result": [
                            {
                                "timestamp": timestamps[: len(closes)],
                                "indicators": {"quote": [{"close": closes}]},
                            }
                        ],
                    }
                }
            ).encode()

        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("trade_helper.proxy_sources._download", side_effect=fake_download):
                result = build_proxy_source_csv(
                    root / "raw.csv",
                    start_date=date(2000, 1, 1),
                    end_date=date(2000, 1, 4),
                    source_dir=root / "sources",
                )
            self.assertEqual(2, result.rows)
            with (root / "raw.csv").open(encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["DIVIDEND_index"], rows[1]["DIVIDEND_index"])
