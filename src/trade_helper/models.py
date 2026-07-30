from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class Readiness(StrEnum):
    BLOCKED = "BLOCKED"
    REVIEW = "REVIEW"
    READY = "READY"


@dataclass(frozen=True)
class Quote:
    symbol: str
    name: str
    observed_at: datetime
    last_price: float | None
    bid1: float | None
    ask1: float | None
    iopv: float | None
    source: str

    @property
    def premium(self) -> float | None:
        reference_price = self.ask1 or self.last_price
        if reference_price is None or self.iopv is None or self.iopv <= 0:
            return None
        return reference_price / self.iopv - 1


@dataclass(frozen=True)
class ProbeResult:
    symbol: str
    readiness: Readiness
    reasons: tuple[str, ...]
    quote: Quote | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["readiness"] = self.readiness.value
        if self.quote is not None:
            payload["quote"]["observed_at"] = self.quote.observed_at.isoformat()
            payload["quote"]["premium"] = self.quote.premium
        return payload
