from datetime import datetime, timezone
from unittest import TestCase

from trade_helper.providers.eastmoney import EastmoneyEtfProvider


class EastmoneyEtfProviderTests(TestCase):
    def test_parse_many_extracts_iopv_and_market_time(self) -> None:
        quote = EastmoneyEtfProvider.parse_many_row(
            {
                "f2": 2533,
                "f12": "513500",
                "f14": "标普500ETF博时",
                "f31": 2533,
                "f32": 2534,
                "f124": 1785741731,
                "f145": 2403,
            }
        )
        self.assertEqual("513500", quote.symbol)
        self.assertEqual(2.533, quote.last_price)
        self.assertEqual(2.403, quote.iopv)
        self.assertIsNotNone(quote.observed_at.tzinfo)

    def test_parse_keeps_missing_iopv_explicit(self) -> None:
        observed_at = datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)

        quote = EastmoneyEtfProvider.parse(
            "513500",
            {"f43": 2345, "f57": "513500", "f58": "标普500ETF"},
            observed_at,
        )

        self.assertEqual("513500", quote.symbol)
        self.assertEqual(2.345, quote.last_price)
        self.assertIsNone(quote.bid1)
        self.assertIsNone(quote.ask1)
        self.assertIsNone(quote.iopv)
        self.assertEqual(observed_at, quote.observed_at)

    def test_parse_rejects_non_positive_price(self) -> None:
        quote = EastmoneyEtfProvider.parse(
            "513100",
            {"f43": 0, "f57": "513100", "f58": "纳指ETF"},
            datetime.now(timezone.utc),
        )

        self.assertIsNone(quote.last_price)

    def test_parse_uses_market_timestamp_instead_of_fetch_time(self) -> None:
        quote = EastmoneyEtfProvider.parse(
            "515450",
            {
                "f43": 1458,
                "f57": "515450",
                "f58": "红利低波50ETF南方",
                "f86": 1785380836,
            },
        )

        self.assertEqual(1785380836, int(quote.observed_at.timestamp()))
