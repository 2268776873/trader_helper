import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zoneinfo import ZoneInfo

from trade_helper.config import load_strategy_config
from trade_helper.ledger import Ledger
from trade_helper.market_collection import (
    MarketCollectionService,
    load_manual_supplement,
)
from trade_helper.models import Quote, Readiness


ROOT = Path(__file__).resolve().parents[1]


class FakeSource:
    def __init__(
        self, name: str, price: float, fail: bool = False,
        iopv: float | None = None,
    ) -> None:
        self.name = name
        self.price = price
        self.fail = fail
        self.iopv = iopv

    def fetch(self, symbols: tuple[str, ...]) -> tuple[Quote, ...]:
        if self.fail:
            raise RuntimeError("offline")
        now = datetime(2026, 7, 30, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        return tuple(
            Quote(
                symbol, symbol, now, self.price, self.price, self.price,
                self.iopv, self.name,
            )
            for symbol in symbols
        )


class MarketCollectionTests(TestCase):
    def test_automatic_sources_need_no_manual_market_input(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "account.db")
            ledger.initialize()
            service = MarketCollectionService(
                ledger,
                load_strategy_config(ROOT / "config" / "personal_v1.json"),
                (
                    FakeSource("q1", 2.10, iopv=2.00),
                    FakeSource("q2", 2.101, iopv=2.001),
                ),
            )
            result = service.collect(
                observed_at=datetime(
                    2026, 7, 30, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai")
                )
            )
            self.assertTrue(result.usable)
            self.assertEqual(3, ledger.count("reference_series"))
            self.assertTrue(
                all(
                    len(
                        {
                            item.source for item in snapshot.observations
                            if item.kind.value == "VALUATION"
                        }
                    ) == 2
                    for snapshot in result.snapshots
                )
            )

    def supplements(self) -> dict[str, dict[str, object]]:
        return {
            asset: {
                "valuations": [
                    {"source": "v1", "value": "2"},
                    {"source": "v2", "value": "2.001"},
                ],
                "index": {"source": "index", "value": "100"},
                "fx": {"source": "fx", "value": "7.1"},
                "reference_value_cny": "100",
            }
            for asset in ("SP500", "NASDAQ", "DIVIDEND")
        }

    def test_collects_ready_snapshots_and_reference_values(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "account.db")
            ledger.initialize()
            service = MarketCollectionService(
                ledger,
                load_strategy_config(ROOT / "config" / "personal_v1.json"),
                (FakeSource("q1", 2), FakeSource("q2", 2.001)),
            )
            result = service.collect(
                observed_at=datetime(
                    2026, 7, 30, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai")
                ),
                supplements=self.supplements(),
            )
            self.assertTrue(all(item.readiness == Readiness.READY for item in result.snapshots))
            self.assertTrue(result.usable)
            self.assertFalse(result.degraded)
            self.assertEqual(3, ledger.count("market_snapshots"))
            self.assertEqual(3, ledger.count("reference_series"))

    def test_source_failure_is_persisted_as_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "account.db")
            ledger.initialize()
            service = MarketCollectionService(
                ledger,
                load_strategy_config(ROOT / "config" / "personal_v1.json"),
                (FakeSource("q1", 2), FakeSource("q2", 2, fail=True)),
            )
            result = service.collect(
                observed_at=datetime(
                    2026, 7, 30, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai")
                ),
                supplements=self.supplements(),
            )
            self.assertTrue(all(item.readiness == Readiness.BLOCKED for item in result.snapshots))
            self.assertFalse(result.usable)
            self.assertTrue(result.degraded)
            self.assertIn("q2: offline", result.source_errors)

    def test_broker_quote_can_replace_one_failed_public_quote_source(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "account.db")
            ledger.initialize()
            service = MarketCollectionService(
                ledger,
                load_strategy_config(ROOT / "config" / "personal_v1.json"),
                (FakeSource("q1", 2), FakeSource("q2", 2, fail=True)),
            )
            supplements = self.supplements()
            for item in supplements.values():
                item["quote"] = {
                    "source": "BROKER_MANUAL",
                    "last": 2,
                    "bid": 2,
                    "ask": 2,
                }
            result = service.collect(
                observed_at=datetime(
                    2026, 7, 30, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai")
                ),
                supplements=supplements,
            )
            self.assertTrue(
                all(item.readiness == Readiness.READY for item in result.snapshots)
            )
            self.assertTrue(result.usable)
            self.assertTrue(result.degraded)
            self.assertTrue(
                all("q2: offline" in item.reasons for item in result.snapshots)
            )

    def test_manual_supplement_rejects_invalid_numeric_data_cleanly(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "observed_at": "2026-07-30T14:00:00+08:00",
                        "assets": {
                            "SP500": {
                                "valuations": [
                                    {"source": "v1", "value": "NaN"}
                                ]
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError, r"SP500\.valuations\[0\]\.value"
            ):
                load_manual_supplement(path)

    def test_manual_supplement_rejects_missing_source_cleanly(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "observed_at": "2026-07-30T14:00:00+08:00",
                        "assets": {
                            "SP500": {
                                "quote": {"last": 2, "bid": 2, "ask": 2}
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, r"SP500\.quote\.source"):
                load_manual_supplement(path)

    def test_write_manual_supplement_round_trip(self) -> None:
        from trade_helper.market_collection import write_manual_supplement

        observed_at = datetime(2026, 7, 30, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        assets = {
            "SP500": {
                "quote": {
                    "source": "BROKER_MANUAL",
                    "last": 2.000, "bid": 1.999, "ask": 2.000,
                },
                "valuations": [
                    {"source": "VALUATION_SOURCE_A", "value": 2.000},
                    {"source": "VALUATION_SOURCE_B", "value": 2.001},
                ],
                "index": {"source": "INDEX_SOURCE", "value": 6500},
                "fx": {"source": "FX_SOURCE", "value": 7.15},
                "reference_value_cny": 100.0,
            },
            "NASDAQ": {
                "valuations": [
                    {"source": "VALUATION_SOURCE_A", "value": 2.0},
                ],
                "announcement": {
                    "source": "FUND_ANNOUNCEMENT",
                    "blocking": True,
                    "detail": "客户端录入",
                },
            },
            "DIVIDEND": {},
        }
        with TemporaryDirectory() as directory:
            target = Path(directory) / "today-market.json"
            written = write_manual_supplement(target, observed_at, assets)
            self.assertEqual(written, target)
            parsed_at, parsed_assets = load_manual_supplement(target)
            self.assertEqual(parsed_at, observed_at)
            self.assertEqual(parsed_assets["SP500"]["quote"]["source"], "BROKER_MANUAL")
            self.assertEqual(
                parsed_assets["SP500"]["valuations"][1]["value"], 2.001
            )
            self.assertTrue(
                parsed_assets["NASDAQ"]["announcement"]["blocking"]
            )
            self.assertEqual(parsed_assets["DIVIDEND"], {})

    def test_write_manual_supplement_rejects_invalid_payload(self) -> None:
        from trade_helper.market_collection import write_manual_supplement

        observed_at = datetime(2026, 7, 30, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        assets = {
            "SP500": {
                "valuations": [{"value": 2.0}],
            },
        }
        with TemporaryDirectory() as directory:
            target = Path(directory) / "today-market.json"
            with self.assertRaisesRegex(ValueError, r"source is required"):
                write_manual_supplement(target, observed_at, assets)
            self.assertFalse(target.exists())
