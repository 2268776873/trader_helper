from unittest import TestCase

from trade_helper.providers.tencent import TencentError, TencentEtfProvider


class TencentEtfProviderTests(TestCase):
    def test_parse_extracts_quote_iopv_and_market_time(self) -> None:
        fields = [""] * 88
        fields[1] = "标普500ETF博时"
        fields[3] = "2.533"
        fields[9] = "2.532"
        fields[19] = "2.533"
        fields[30] = "20260803144530"
        fields[77] = "5.40"
        fields[78] = "2.4033"
        fields[81] = "2.3867"
        line = f'v_sh513500="{"~".join(fields)}";'

        quote = TencentEtfProvider.parse_line(line)

        self.assertEqual("513500", quote.symbol)
        self.assertEqual(2.533, quote.last_price)
        self.assertEqual(2.532, quote.bid1)
        self.assertEqual(2.4033, quote.iopv)
        self.assertEqual("2026-08-03T14:45:30+08:00", quote.observed_at.isoformat())

    def test_rejects_malformed_line(self) -> None:
        with self.assertRaises(TencentError):
            TencentEtfProvider.parse_line("bad")
