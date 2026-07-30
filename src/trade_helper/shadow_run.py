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
    coverage_completed: bool
    completed: bool
    ready_days: int
    blocked_days: int
    total_advices: int
    unresolved_advices: int
    missing_calendar_dates: tuple[date, ...]
    closed_dates_with_decisions: tuple[date, ...]
    advice_dates_without_decisions: tuple[date, ...]
    duplicate_successful_decision_dates: tuple[date, ...]
    unknown_decision_statuses: tuple[str, ...]
    acceptance_issues: tuple[str, ...]
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
        payload["advice_dates_without_decisions"] = [
            item.isoformat()
            for item in self.advice_dates_without_decisions
        ]
        payload["duplicate_successful_decision_dates"] = [
            item.isoformat()
            for item in self.duplicate_successful_decision_dates
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
    database_path = Path(database)
    if not database_path.is_file():
        raise FileNotFoundError(
            f"shadow-run database does not exist: {database_path}"
        )
    ledger = Ledger(database_path)
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
    advice_dates_without_decisions = tuple(
        sorted(set(advices_by_day) - set(decisions_by_day))
    )
    known_statuses = {"READY", "NO_ACTION", "BLOCKED"}
    unknown_statuses = tuple(
        sorted(
            {
                row["status"]
                for rows in decisions_by_day.values()
                for row in rows
                if row["status"] not in known_statuses
            }
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
    coverage_completed = observed >= required_trading_days
    duplicate_successful = tuple(
        item.trading_date
        for item in days
        if item.ready_count > 1
    )
    unresolved = sum(item.unresolved_advice_count for item in days)
    issues = []
    if not coverage_completed:
        issues.append(
            f"only {observed}/{required_trading_days} open trading days observed"
        )
    if missing_calendar_dates:
        issues.append(
            f"{len(missing_calendar_dates)} decision dates lack calendar audit"
        )
    if closed_dates_with_decisions:
        issues.append(
            f"{len(closed_dates_with_decisions)} closed dates contain decisions"
        )
    if advice_dates_without_decisions:
        issues.append(
            f"{len(advice_dates_without_decisions)} advice dates lack decisions"
        )
    if unknown_statuses:
        issues.append(
            "unknown decision statuses: " + ", ".join(unknown_statuses)
        )
    if duplicate_successful:
        issues.append(
            f"{len(duplicate_successful)} dates contain duplicate successful decisions"
        )
    if unresolved:
        issues.append(f"{unresolved} advices remain unresolved")
    return ShadowRunReport(
        now or datetime.now().astimezone(),
        required_trading_days,
        observed,
        coverage_completed,
        not issues,
        sum(item.ready_count > 0 and item.blocked_count == 0 for item in days),
        sum(item.blocked_count > 0 for item in days),
        sum(item.advice_count for item in days),
        unresolved,
        missing_calendar_dates,
        closed_dates_with_decisions,
        advice_dates_without_decisions,
        duplicate_successful,
        unknown_statuses,
        tuple(issues),
        days,
    )


def write_shadow_report(report: ShadowRunReport, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
