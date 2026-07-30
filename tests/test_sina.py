from unittest import TestCase

from trade_helper.providers.sina import SinaError, SinaEtfProvider


class SinaEtfProviderTests(TestCase):
    def test_parse_extracts_best_bid_ask_and_market_time(self) -> None:
        line = (
            'var hq_str_sh513500="标普500ETF博时,2.490,2.511,2.477,'
            "2.493,2.473,2.477,2.478,77597500,192433819.000,"
            "276700,2.477,391800,2.476,1817400,2.475,2123800,2.474,"
            "1914100,2.473,522600,2.478,812400,2.479,602300,2.480,"
            '1010500,2.481,416900,2.482,2026-07-30,11:14:10,00,";'
        )

        quote = SinaEtfProvider.parse_line(line)

        self.assertEqual("513500", quote.symbol)
        self.assertEqual(2.477, quote.last_price)
        self.assertEqual(2.477, quote.bid1)
        self.assertEqual(2.478, quote.ask1)
        self.assertEqual("2026-07-30T11:14:10+08:00", quote.observed_at.isoformat())

    def test_parse_rejects_malformed_line(self) -> None:
        with self.assertRaises(SinaError):
            SinaEtfProvider.parse_line("not a quote")
