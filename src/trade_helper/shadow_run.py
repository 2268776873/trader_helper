from __future__ import annotations

import json
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from trade_helper.ledger import Ledger


@dataclass(frozen=True)
class ShadowDay:
    trading_date: date
    decision_count: int
    ready_count: int
    blocked_count: int
    advice_count: int
    unresolved_advice_count: int


@dataclass(frozen=True)
class ShadowRunReport:
    generated_at: datetime
    required_trading_days: int
    observed_trading_days: int
    completed: bool
    ready_days: int
    blocked_days: int
    total_advices: int
    unresolved_advices: int
    missing_calendar_dates: tuple[date, ...]
    closed_dates_with_decisions: tuple[date, ...]
    days: tuple[ShadowDay, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["generated_at"] = self.generated_at.isoformat()
        payload["missing_calendar_dates"] = [
            item.isoformat() for item in self.missing_calendar_dates
        ]
        payload["closed_dates_with_decisions"] = [
            item.isoformat() for item in self.closed_dates_with_decisions
        ]
        for item in payload["days"]:
            item["trading_date"] = item["trading_date"].isoformat()
        return payload


def build_shadow_report(
    database: str | Path,
    *,
    required_trading_days: int = 20,
    now: datetime | None = None,
) -> ShadowRunReport:
    if required_trading_days <= 0:
        raise ValueError("required trading days must be positive")
    ledger = Ledger(database)
    ledger.initialize()
    with closing(ledger.connect()) as connection:
        decisions = connection.execute(
            """
            SELECT decision_id, generated_at, status
            FROM decision_runs ORDER BY generated_at
            """
        ).fetchall()
        advices = connection.execute(
            """
            SELECT advice_id, created_at, status FROM advice
            ORDER BY created_at
            """
        ).fetchall()
        calendar = {
            date.fromisoformat(row["trading_date"]): bool(row["is_open"])
            for row in connection.execute(
                "SELECT trading_date, is_open FROM trading_calendar"
            ).fetchall()
        }
    decisions_by_day: dict[date, list] = {}
    for row in decisions:
        day = datetime.fromisoformat(row["generated_at"]).date()
        decisions_by_day.setdefault(day, []).append(row)
    advices_by_day: dict[date, list] = {}
    for row in advices:
        day = datetime.fromisoformat(row["created_at"]).date()
        advices_by_day.setdefault(day, []).append(row)
    terminal = {"FILLED", "CANCELLED", "EXPIRED", "REJECTED", "NOT_ATTEMPTED"}
    missing_calendar_dates = tuple(
        sorted(day for day in decisions_by_day if day not in calendar)
    )
    closed_dates_with_decisions = tuple(
        sorted(
            day
            for day in decisions_by_day
            if day in calendar and not calendar[day]
        )
    )
    eligible_decisions = {
        day: rows
        for day, rows in decisions_by_day.items()
        if calendar.get(day) is True
    }
    days = tuple(
        ShadowDay(
            day,
            len(rows),
            sum(row["status"] in {"READY", "NO_ACTION"} for row in rows),
            sum(row["status"] == "BLOCKED" for row in rows),
            len(advices_by_day.get(day, [])),
            sum(
                item["status"] not in terminal
                for item in advices_by_day.get(day, [])
            ),
        )
        for day, rows in sorted(eligible_decisions.items())
    )
    observed = len(days)
    return ShadowRunReport(
        now or datetime.now().astimezone(),
        required_trading_days,
        observed,
        observed >= required_trading_days,
        sum(item.ready_count > 0 and item.blocked_count == 0 for item in days),
        sum(item.blocked_count > 0 for item in days),
        sum(item.advice_count for item in days),
        sum(item.unresolved_advice_count for item in days),
        missing_calendar_dates,
        closed_dates_with_decisions,
        days,
    )


def write_shadow_report(report: ShadowRunReport, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
