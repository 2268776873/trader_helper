from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trade_helper.models import Quote


class EastmoneyError(RuntimeError):
    """Raised when the public endpoint cannot provide a usable response."""


class EastmoneyEtfProvider:
    """Small public-data probe.

    The endpoint is suitable for feasibility testing, not a contractual
    exchange feed. Field f43 is latest price and f57/f58 identify the fund.
    IOPV availability is deliberately optional until verified by live probes.
    """

    _URL = "https://push2.eastmoney.com/api/qt/stock/get"
    _MANY_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    _FIELDS = "f43,f57,f58,f60,f86,f169,f170"
    _MANY_FIELDS = "f2,f12,f14,f31,f32,f124,f145"

    def __init__(self, timeout_seconds: float = 8.0) -> None:
        self._timeout_seconds = timeout_seconds

    def fetch(self, symbol: str, observed_at: datetime | None = None) -> Quote:
        params = urlencode(
            {
                "secid": f"1.{symbol}",
                "fields": self._FIELDS,
                "invt": "2",
                "fltt": "1",
            }
        )
        request = Request(
            f"{self._URL}?{params}",
            headers={"User-Agent": "trade-helper-feasibility/0.1"},
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.load(response)
        except Exception as error:
            raise EastmoneyError(f"request failed: {error}") from error

        data = payload.get("data")
        if not isinstance(data, dict):
            raise EastmoneyError("response has no data object")

        return self.parse(symbol, data, observed_at)

    def fetch_many(self, symbols: tuple[str, ...]) -> list[Quote]:
        params = urlencode(
            {
                "secids": ",".join(f"1.{symbol}" for symbol in symbols),
                "fields": self._MANY_FIELDS,
                "invt": "2",
                "fltt": "1",
            }
        )
        request = Request(
            f"{self._MANY_URL}?{params}",
            headers={"User-Agent": "trade-helper/0.1"},
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.load(response)
        except Exception as error:
            raise EastmoneyError(f"request failed: {error}") from error
        data = payload.get("data")
        rows = data.get("diff") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise EastmoneyError("response has no quote rows")
        quotes = [self.parse_many_row(row) for row in rows if isinstance(row, dict)]
        returned = {item.symbol for item in quotes}
        missing = set(symbols) - returned
        if missing:
            raise EastmoneyError(f"response missing symbols: {sorted(missing)}")
        return quotes

    @staticmethod
    def parse_many_row(data: dict[str, Any]) -> Quote:
        def scaled(value: Any) -> float | None:
            if isinstance(value, (int, float)) and value > 0:
                return float(value) / 1000
            return None

        timestamp = data.get("f124")
        if not isinstance(timestamp, (int, float)):
            raise EastmoneyError("response has no usable market timestamp")
        return Quote(
            symbol=str(data.get("f12") or ""),
            name=str(data.get("f14") or ""),
            observed_at=datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(),
            last_price=scaled(data.get("f2")),
            bid1=scaled(data.get("f31")),
            ask1=scaled(data.get("f32")),
            iopv=scaled(data.get("f145")),
            source="eastmoney_public_quote",
        )

    @staticmethod
    def parse(
        symbol: str,
        data: dict[str, Any],
        observed_at: datetime | None = None,
    ) -> Quote:
        def scaled_price(value: Any) -> float | None:
            if isinstance(value, (int, float)) and value > 0:
                return float(value) / 1000
            return None

        market_timestamp = data.get("f86")
        if observed_at is None and isinstance(market_timestamp, (int, float)):
            observed_at = datetime.fromtimestamp(
                market_timestamp,
                tz=timezone.utc,
            ).astimezone()
        if observed_at is None:
            raise EastmoneyError("response has no usable market timestamp")

        returned_symbol = str(data.get("f57") or symbol)
        return Quote(
            symbol=returned_symbol,
            name=str(data.get("f58") or ""),
            observed_at=observed_at,
            last_price=scaled_price(data.get("f43")),
            bid1=None,
            ask1=None,
            iopv=None,
            source="eastmoney_public_quote",
        )
