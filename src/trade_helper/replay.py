from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class ReplayPoint:
    trading_date: date
    portfolio_value_cny: Decimal
    cash_cny: Decimal
    traded_value_cny: Decimal = Decimal("0")


@dataclass(frozen=True)
class ReplayMetrics:
    start_date: date
    end_date: date
    trading_days: int
    total_return: Decimal
    annualized_return: Decimal
    maximum_drawdown: Decimal
    annualized_volatility: Decimal
    turnover_ratio: Decimal
    average_cash_ratio: Decimal
    minimum_cash_cny: Decimal

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        for key, value in tuple(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class SensitivityVariant:
    name: str
    metrics: ReplayMetrics


@dataclass(frozen=True)
class SensitivityReport:
    baseline: str
    variants: tuple[SensitivityVariant, ...]
    annualized_return_range: Decimal
    maximum_drawdown_range: Decimal
    turnover_range: Decimal
    cash_usage_range: Decimal

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline": self.baseline,
            "variants": [
                {"name": item.name, "metrics": item.metrics.to_dict()}
                for item in self.variants
            ],
            "ranges": {
                "annualized_return": str(self.annualized_return_range),
                "maximum_drawdown": str(self.maximum_drawdown_range),
                "turnover": str(self.turnover_range),
                "cash_usage": str(self.cash_usage_range),
            },
            "selection_policy": (
                "Do not select parameters by return alone; review drawdown, "
                "volatility, turnover and cash usage together."
            ),
        }


def compare_sensitivity(
    variants: tuple[SensitivityVariant, ...],
    *,
    baseline: str,
) -> SensitivityReport:
    if len(variants) < 2:
        raise ValueError("sensitivity report requires at least two variants")
    names = [item.name for item in variants]
    if len(set(names)) != len(names):
        raise ValueError("variant names must be unique")
    if baseline not in names:
        raise ValueError("baseline variant is missing")

    def spread(values: list[Decimal]) -> Decimal:
        return max(values) - min(values)

    return SensitivityReport(
        baseline,
        variants,
        spread([item.metrics.annualized_return for item in variants]),
        spread([item.metrics.maximum_drawdown for item in variants]),
        spread([item.metrics.turnover_ratio for item in variants]),
        spread([item.metrics.average_cash_ratio for item in variants]),
    )


def calculate_replay_metrics(
    points: tuple[ReplayPoint, ...],
) -> ReplayMetrics:
    if len(points) < 2:
        raise ValueError("replay requires at least two trading days")
    ordered = tuple(sorted(points, key=lambda item: item.trading_date))
    dates = [item.trading_date for item in ordered]
    if len(set(dates)) != len(dates):
        raise ValueError("replay trading dates must be unique")
    if any(item.portfolio_value_cny <= 0 for item in ordered):
        raise ValueError("portfolio values must be positive")
    if any(
        item.cash_cny < 0
        or item.cash_cny > item.portfolio_value_cny
        or item.traded_value_cny < 0
        for item in ordered
    ):
        raise ValueError("cash and traded values are invalid")

    daily_returns = [
        float(current.portfolio_value_cny / previous.portfolio_value_cny - 1)
        for previous, current in zip(ordered, ordered[1:])
    ]
    total_return = ordered[-1].portfolio_value_cny / ordered[0].portfolio_value_cny - 1
    years = Decimal(len(ordered) - 1) / Decimal(252)
    annualized_return = Decimal(
        str(math.pow(float(1 + total_return), float(1 / years)) - 1)
    )
    mean_return = sum(daily_returns) / len(daily_returns)
    variance = sum(
        (value - mean_return) ** 2 for value in daily_returns
    ) / max(1, len(daily_returns) - 1)
    volatility = Decimal(str(math.sqrt(variance) * math.sqrt(252)))

    peak = ordered[0].portfolio_value_cny
    maximum_drawdown = Decimal("0")
    for item in ordered:
        # Peak contains only current and prior observations; future data is never used.
        peak = max(peak, item.portfolio_value_cny)
        drawdown = Decimal("1") - item.portfolio_value_cny / peak
        maximum_drawdown = max(maximum_drawdown, drawdown)
    average_value = sum(
        (item.portfolio_value_cny for item in ordered), start=Decimal("0")
    ) / len(ordered)
    turnover = sum(
        (item.traded_value_cny for item in ordered), start=Decimal("0")
    ) / average_value
    average_cash = sum(
        (item.cash_cny / item.portfolio_value_cny for item in ordered),
        start=Decimal("0"),
    ) / len(ordered)
    return ReplayMetrics(
        ordered[0].trading_date,
        ordered[-1].trading_date,
        len(ordered),
        total_return,
        annualized_return,
        maximum_drawdown,
        volatility,
        turnover,
        average_cash,
        min(item.cash_cny for item in ordered),
    )


def load_replay_csv(path: str | Path) -> tuple[ReplayPoint, ...]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream)
        required = {
            "trading_date", "portfolio_value_cny", "cash_cny",
            "traded_value_cny",
        }
        if rows.fieldnames is None or not required.issubset(rows.fieldnames):
            raise ValueError(f"replay CSV must contain: {sorted(required)}")
        return tuple(
            ReplayPoint(
                date.fromisoformat(row["trading_date"]),
                Decimal(row["portfolio_value_cny"]),
                Decimal(row["cash_cny"]),
                Decimal(row["traded_value_cny"]),
            )
            for row in rows
        )


def write_replay_report(metrics: ReplayMetrics, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "metrics": metrics.to_dict(),
        "methodology": {
            "trading_days_per_year": 252,
            "maximum_drawdown": "expanding historical peak; no future data",
            "turnover": "sum traded value / average portfolio value",
            "cash_usage": "average daily cash / portfolio value",
        },
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
