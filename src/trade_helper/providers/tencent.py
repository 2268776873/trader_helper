from __future__ import annotations

import re
from datetime import datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from trade_helper.models import Quote


class TencentError(RuntimeError):
    """Raised when Tencent's public ETF quote response is unusable."""


class TencentEtfProvider:
    _URL = "https://qt.gtimg.cn/q="
    _LINE_PATTERN = re.compile(r'v_sh(?P<symbol>\d+)="(?P<data>.*)";')

    def __init__(self, timeout_seconds: float = 8.0) -> None:
        self._timeout_seconds = timeout_seconds

    def fetch_many(self, symbols: tuple[str, ...]) -> list[Quote]:
        instruments = ",".join(f"sh{symbol}" for symbol in symbols)
        request = Request(
            f"{self._URL}{instruments}",
            headers={
                "Referer": "https://gu.qq.com/",
                "User-Agent": "trade-helper/0.1",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                text = response.read().decode("gb18030")
        except Exception as error:
            raise TencentError(f"request failed: {error}") from error
        quotes = [self.parse_line(line) for line in text.splitlines() if line.strip()]
        returned = {item.symbol for item in quotes}
        missing = set(symbols) - returned
        if missing:
            raise TencentError(f"response missing symbols: {sorted(missing)}")
        return quotes

    @classmethod
    def parse_line(cls, line: str) -> Quote:
        match = cls._LINE_PATTERN.fullmatch(line.strip())
        if match is None:
            raise TencentError("malformed quote line")
        fields = match.group("data").split("~")
        if len(fields) < 82:
            raise TencentError("quote line has too few fields")

        def positive(index: int) -> float | None:
            try:
                value = float(fields[index])
            except (ValueError, IndexError):
                return None
            return value if value > 0 else None

        try:
            observed_at = datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(
                tzinfo=ZoneInfo("Asia/Shanghai")
            )
        except (ValueError, IndexError) as error:
            raise TencentError("quote has no usable market timestamp") from error
        # Field 78 is the intraday ETF reference value used by Tencent's own
        # displayed premium (field 77). Field 81 is the latest published NAV.
        return Quote(
            symbol=match.group("symbol"),
            name=fields[1],
            observed_at=observed_at,
            last_price=positive(3),
            bid1=positive(9),
            ask1=positive(19),
            iopv=positive(78),
            source="tencent_public_quote",
        )
