from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from trade_helper.models import ProbeResult, Quote, Readiness


def assess_quote(
    quote: Quote,
    now: datetime,
    *,
    max_age: timedelta = timedelta(minutes=5),
    independent_valuation_count: int = 1,
) -> ProbeResult:
    reasons: list[str] = []

    if quote.last_price is None:
        reasons.append("缺少有效最新价")
    if quote.observed_at > now + timedelta(seconds=30):
        reasons.append("行情时间戳位于未来")
    elif now - quote.observed_at > max_age:
        reasons.append("行情超过允许的新鲜度")
    if quote.iopv is None:
        reasons.append("公开行情未提供已验证的IOPV")
    if independent_valuation_count < 2:
        reasons.append("缺少第二个独立估值源，必须在券商客户端复核")

    blocking = {
        "缺少有效最新价",
        "行情时间戳位于未来",
        "行情超过允许的新鲜度",
    }
    if any(reason in blocking for reason in reasons):
        readiness = Readiness.BLOCKED
    elif reasons:
        readiness = Readiness.REVIEW
    else:
        readiness = Readiness.READY

    return ProbeResult(
        symbol=quote.symbol,
        readiness=readiness,
        reasons=tuple(reasons),
        quote=quote,
    )


def overall_readiness(results: Iterable[ProbeResult]) -> Readiness:
    states = {result.readiness for result in results}
    if Readiness.BLOCKED in states:
        return Readiness.BLOCKED
    if Readiness.REVIEW in states:
        return Readiness.REVIEW
    return Readiness.READY
