from __future__ import annotations

import csv
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from trade_helper.ledger import Ledger


@dataclass(frozen=True)
class CalendarDay:
    trading_date: date
    is_open: bool
    source: str


class TradingCalendarStore:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def replace(self, days: tuple[CalendarDay, ...]) -> None:
        if not days:
            raise ValueError("calendar import cannot be empty")
        if len({item.trading_date for item in days}) != len(days):
            raise ValueError("calendar dates must be unique")
        imported_at = datetime.now().astimezone().isoformat()
        with self.ledger.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO trading_calendar(
                    trading_date, is_open, source, imported_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(trading_date) DO UPDATE SET
                    is_open = excluded.is_open,
                    source = excluded.source,
                    imported_at = excluded.imported_at
                """,
                [
                    (
                        item.trading_date.isoformat(), int(item.is_open),
                        item.source, imported_at,
                    )
                    for item in days
                ],
            )

    def trading_day_number(self, value: date) -> int | None:
        with closing(self.ledger.connect()) as connection:
            current = connection.execute(
                "SELECT is_open FROM trading_calendar WHERE trading_date = ?",
                (value.isoformat(),),
            ).fetchone()
            if current is None:
                raise ValueError(f"交易日历缺少日期：{value}")
            if not bool(current["is_open"]):
                return None
            row = connection.execute(
                """
                SELECT COUNT(*) AS count FROM trading_calendar
                WHERE trading_date >= ? AND trading_date <= ? AND is_open = 1
                """,
                (
                    value.replace(day=1).isoformat(),
                    value.isoformat(),
                ),
            ).fetchone()
        return int(row["count"])


def load_calendar_csv(path: str | Path, source: str) -> tuple[CalendarDay, ...]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream)
        if rows.fieldnames is None or not {"trading_date", "is_open"}.issubset(
            rows.fieldnames
        ):
            raise ValueError("calendar CSV must contain trading_date and is_open")
        result = []
        for row in rows:
            raw = row["is_open"].strip().lower()
            if raw not in {"1", "0", "true", "false"}:
                raise ValueError(f"invalid is_open value: {row['is_open']}")
            result.append(
                CalendarDay(
                    date.fromisoformat(row["trading_date"]),
                    raw in {"1", "true"},
                    source,
                )
            )
        return tuple(result)
