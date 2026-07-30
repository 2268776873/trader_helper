from __future__ import annotations

import re
from datetime import datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from trade_helper.models import Quote


class SinaError(RuntimeError):
    """Raised when Sina's public quote response is unavailable or malformed."""


class SinaEtfProvider:
    _URL = "https://hq.sinajs.cn/list="
    _LINE_PATTERN = re.compile(r'var hq_str_sh(?P<symbol>\d+)="(?P<data>.*)";')

    def __init__(self, timeout_seconds: float = 8.0) -> None:
        self._timeout_seconds = timeout_seconds

    def fetch_many(self, symbols: tuple[str, ...]) -> list[Quote]:
        instruments = ",".join(f"sh{symbol}" for symbol in symbols)
        request = Request(
            f"{self._URL}{instruments}",
            headers={
                "Referer": "https://finance.sina.com.cn/",
                "User-Agent": "trade-helper-feasibility/0.1",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                text = response.read().decode("gb18030")
        except Exception as error:
            raise SinaError(f"request failed: {error}") from error

        quotes = [self.parse_line(line) for line in text.splitlines() if line.strip()]
        returned_symbols = {quote.symbol for quote in quotes}
        missing = set(symbols) - returned_symbols
        if missing:
            raise SinaError(f"response missing symbols: {sorted(missing)}")
        return quotes

    @classmethod
    def parse_line(cls, line: str) -> Quote:
        match = cls._LINE_PATTERN.fullmatch(line.strip())
        if match is None:
            raise SinaError("malformed quote line")

        fields = match.group("data").split(",")
        if len(fields) < 32:
            raise SinaError("quote line has too few fields")

        def positive_number(index: int) -> float | None:
            try:
                value = float(fields[index])
            except (ValueError, IndexError):
                return None
            return value if value > 0 else None

        try:
            observed_at = datetime.strptime(
                f"{fields[30]} {fields[31]}",
                "%Y-%m-%d %H:%M:%S",
            ).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        except (ValueError, IndexError) as error:
            raise SinaError("quote has no usable market timestamp") from error

        return Quote(
            symbol=match.group("symbol"),
            name=fields[0],
            observed_at=observed_at,
            last_price=positive_number(3),
            bid1=positive_number(11),
            ask1=positive_number(21),
            iopv=None,
            source="sina_public_quote",
        )
