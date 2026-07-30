from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zoneinfo import ZoneInfo

from trade_helper.config import load_strategy_config
from trade_helper.ledger import Ledger
from trade_helper.market_collection import MarketCollectionService
from trade_helper.models import Quote, Readiness


ROOT = Path(__file__).resolve().parents[1]


class FakeSource:
    def __init__(self, name: str, price: float, fail: bool = False) -> None:
        self.name = name
        self.price = price
        self.fail = fail

    def fetch(self, symbols: tuple[str, ...]) -> tuple[Quote, ...]:
        if self.fail:
            raise RuntimeError("offline")
        now = datetime(2026, 7, 30, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        return tuple(
            Quote(symbol, symbol, now, self.price, self.price, self.price, None, self.name)
            for symbol in symbols
        )


class MarketCollectionTests(TestCase):
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
