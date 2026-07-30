from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal
from pathlib import Path

from trade_helper.cash_management import CashPools
from trade_helper.config import StrategyConfig
from trade_helper.decision import (
    DecisionRequest,
    DecisionStatus,
    run_daily_decision,
)
from trade_helper.market_data import MarketSnapshot
from trade_helper.models import Readiness
from trade_helper.replay import ReplayMetrics, ReplayPoint, calculate_replay_metrics
from trade_helper.state_store import (
    RuntimeState,
    TacticalLevelState,
)
from trade_helper.strategy import (
    BaseBudgetState,
    BaseCandidate,
    BasePlanInput,
    RebalanceInput,
    TacticalInput,
)


CHINA_ZONE = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class HistoricalAssetInput:
    price: Decimal
    nav_estimate_1: Decimal
    nav_estimate_2: Decimal
    reference_value_cny: Decimal


@dataclass(frozen=True)
class HistoricalTradingDay:
    trading_date: date
    assets: dict[str, HistoricalAssetInput]


@dataclass(frozen=True)
class ReplayInitialAccount:
    cash_cny: Decimal
    quantities: dict[str, int]


@dataclass(frozen=True)
class StrategyReplayDay:
    trading_date: date
    status: str
    actions: tuple[str, ...]
    reasons: tuple[str, ...]
    portfolio_value_cny: Decimal
    cash_cny: Decimal
    traded_value_cny: Decimal


@dataclass(frozen=True)
class StrategyReplayResult:
    config_version: str
    execution_assumption: str
    points: tuple[ReplayPoint, ...]
    days: tuple[StrategyReplayDay, ...]
    metrics: ReplayMetrics

    def to_dict(self) -> dict[str, object]:
        return {
            "config_version": self.config_version,
            "execution_assumption": self.execution_assumption,
            "metrics": self.metrics.to_dict(),
            "days": [
                {
                    **asdict(item),
                    "trading_date": item.trading_date.isoformat(),
                    "portfolio_value_cny": str(item.portfolio_value_cny),
                    "cash_cny": str(item.cash_cny),
                    "traded_value_cny": str(item.traded_value_cny),
                }
                for item in self.days
            ],
            "methodology": {
                "lookahead": (
                    "Each decision uses only the current and preceding rows; "
                    "drawdown uses a trailing window of at most 250 rows."
                ),
                "fills": (
                    "All executable recommendations are fully filled on the "
                    "same row at its supplied executable price."
                ),
                "sell_proceeds": "Approved option A: strategic cash.",
                "commission": "Excluded by Personal V1 configuration.",
            },
        }


def load_historical_replay_csv(
    path: str | Path,
    config: StrategyConfig,
) -> tuple[HistoricalTradingDay, ...]:
    asset_ids = tuple(asset.asset_id for asset in config.assets)
    required = {"trading_date"}
    for asset_id in asset_ids:
        required.update(
            {
                f"{asset_id}_price",
                f"{asset_id}_nav_1",
                f"{asset_id}_nav_2",
                f"{asset_id}_reference",
            }
        )
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream)
        if rows.fieldnames is None or not required.issubset(rows.fieldnames):
            missing = sorted(required - set(rows.fieldnames or ()))
            raise ValueError(
                f"historical replay CSV is missing columns: {missing}"
            )
        result = []
        for row_number, row in enumerate(rows, start=2):
            try:
                trading_date = date.fromisoformat(row["trading_date"])
                assets = {
                    asset_id: HistoricalAssetInput(
                        _positive_decimal(
                            row[f"{asset_id}_price"],
                            f"row {row_number} {asset_id}_price",
                        ),
                        _positive_decimal(
                            row[f"{asset_id}_nav_1"],
                            f"row {row_number} {asset_id}_nav_1",
                        ),
                        _positive_decimal(
                            row[f"{asset_id}_nav_2"],
                            f"row {row_number} {asset_id}_nav_2",
                        ),
                        _positive_decimal(
                            row[f"{asset_id}_reference"],
                            f"row {row_number} {asset_id}_reference",
                        ),
                    )
                    for asset_id in asset_ids
                }
            except (KeyError, ValueError) as error:
                raise ValueError(
                    f"invalid historical replay row {row_number}: {error}"
                ) from error
            result.append(HistoricalTradingDay(trading_date, assets))
    _validate_days(tuple(result), asset_ids)
    return tuple(result)


def load_replay_initial_account(
    path: str | Path,
    config: StrategyConfig,
) -> ReplayInitialAccount:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("replay initial account root must be an object")
    cash = _positive_decimal(payload.get("cash_cny"), "cash_cny")
    quantities_raw = payload.get("quantities")
    if not isinstance(quantities_raw, dict):
        raise ValueError("quantities must be an object")
    quantities = {}
    for asset in config.assets:
        raw = quantities_raw.get(asset.asset_id)
        if isinstance(raw, bool):
            raise ValueError(f"{asset.asset_id} quantity must be an integer")
        try:
            quantity = int(raw)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{asset.asset_id} quantity must be an integer"
            ) from error
        if quantity < 0 or quantity % int(
            config.raw["execution"]["board_lot"]
        ) != 0:
            raise ValueError(
                f"{asset.asset_id} quantity must be a non-negative board lot"
            )
        quantities[asset.asset_id] = quantity
    if set(quantities_raw) != set(quantities):
        raise ValueError("initial account contains unknown asset quantities")
    return ReplayInitialAccount(cash, quantities)


def run_strategy_replay(
    config: StrategyConfig,
    days: tuple[HistoricalTradingDay, ...],
    initial: ReplayInitialAccount,
) -> StrategyReplayResult:
    asset_ids = tuple(asset.asset_id for asset in config.assets)
    _validate_days(days, asset_ids)
    if initial.cash_cny != _initial_pools(config).total_cny:
        raise ValueError(
            "initial replay cash must equal configured virtual cash pools"
        )
    if set(initial.quantities) != set(asset_ids):
        raise ValueError("initial replay quantities must cover configured assets")
    board_lot = int(config.raw["execution"]["board_lot"])
    if any(
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity < 0
        or quantity % board_lot != 0
        for quantity in initial.quantities.values()
    ):
        raise ValueError(
            "initial replay quantities must be non-negative board lots"
        )
    runtime = _initial_runtime(config)
    quantities = dict(initial.quantities)
    cash = initial.cash_cny
    references: dict[str, list[Decimal]] = {
        asset_id: [] for asset_id in asset_ids
    }
    days_above_max = {asset_id: 0 for asset_id in asset_ids}
    points: list[ReplayPoint] = []
    audits: list[StrategyReplayDay] = []
    current_month = None
    month_day_number = 0

    for historical_day in days:
        if historical_day.trading_date.strftime("%Y-%m") != current_month:
            current_month = historical_day.trading_date.strftime("%Y-%m")
            month_day_number = 0
        month_day_number += 1
        now = datetime.combine(
            historical_day.trading_date, time(14, 0), tzinfo=CHINA_ZONE
        )
        prices = {
            asset_id: historical_day.assets[asset_id].price
            for asset_id in asset_ids
        }
        position_values = {
            asset_id: Decimal(quantities[asset_id]) * prices[asset_id]
            for asset_id in asset_ids
        }
        total = cash + sum(position_values.values(), Decimal("0"))
        markets = []
        tactical = []
        base_candidates = []
        rebalance = []
        for asset in config.assets:
            value = historical_day.assets[asset.asset_id]
            history = references[asset.asset_id]
            history.append(value.reference_value_cny)
            trailing = history[-250:]
            rolling_high = max(trailing)
            drawdown = Decimal("1") - value.reference_value_cny / rolling_high
            price = value.price
            valuations = (value.nav_estimate_1, value.nav_estimate_2)
            data_valid = _valuations_agree(config, price, valuations)
            readiness = Readiness.READY if data_valid else Readiness.BLOCKED
            markets.append(
                MarketSnapshot(
                    f"REPLAY-{asset.asset_id}-{historical_day.trading_date}",
                    asset.etf_code,
                    now,
                    readiness,
                    () if data_valid else ("historical valuation conflict",),
                    (),
                    (),
                    price,
                    min(valuations),
                )
            )
            levels = tuple(
                item
                for item in runtime.tactical_levels
                if item.asset_id == asset.asset_id
            )
            tactical_pool = {
                "SP500": runtime.cash_pools.tactical_sp_cny,
                "NASDAQ": runtime.cash_pools.tactical_nd_cny,
                "DIVIDEND": runtime.cash_pools.tactical_dv_cny,
            }[asset.asset_id]
            tactical.append(
                TacticalInput(
                    asset.asset_id,
                    total,
                    cash,
                    position_values[asset.asset_id],
                    Decimal("0"),
                    drawdown,
                    price,
                    valuations[0],
                    valuations[1],
                    tactical_pool,
                    frozenset(
                        item.level_id
                        for item in levels if item.status == "FILLED"
                    ),
                    tuple(
                        (item.level_id, item.filled_cny) for item in levels
                    ),
                    data_valid,
                )
            )
            base_candidates.append(
                BaseCandidate(
                    asset.asset_id,
                    position_values[asset.asset_id],
                    price,
                    valuations[0],
                    valuations[1],
                    data_valid,
                )
            )
            weight = (
                position_values[asset.asset_id] / total
                if total else Decimal("0")
            )
            days_above_max[asset.asset_id] = (
                days_above_max[asset.asset_id] + 1
                if weight > asset.max_weight else 0
            )
            premium = price / min(valuations) - 1
            rebalance.append(
                RebalanceInput(
                    asset.asset_id,
                    total,
                    position_values[asset.asset_id],
                    price,
                    days_above_max[asset.asset_id],
                    premium,
                    False,
                )
            )
        request = DecisionRequest(
            f"REPLAY-{historical_day.trading_date}",
            now,
            True,
            month_day_number,
            tuple(markets),
            tuple(tactical),
            BasePlanInput(
                total,
                cash,
                runtime.base_budget.available_cny,
                Decimal("0"),
                tuple(base_candidates),
            ),
            tuple(rebalance),
            True,
        )
        outcome = run_daily_decision(config, runtime, request)
        runtime = outcome.runtime
        traded = Decimal("0")
        actions = []
        if outcome.status != DecisionStatus.BLOCKED:
            for advice in outcome.advices:
                if advice.action not in {"BUY", "SELL"}:
                    continue
                runtime, cash, quantities, value = _fill_replay_advice(
                    config, runtime, cash, quantities, advice
                )
                traded += value
                actions.append(
                    f"{advice.action}:{advice.asset_id}:"
                    f"{advice.quantity}@{advice.limit_price}"
                )
        total_after = cash + sum(
            (
                Decimal(quantities[asset_id]) * prices[asset_id]
                for asset_id in asset_ids
            ),
            Decimal("0"),
        )
        point = ReplayPoint(
            historical_day.trading_date, total_after, cash, traded
        )
        points.append(point)
        audits.append(
            StrategyReplayDay(
                historical_day.trading_date,
                outcome.status.value,
                tuple(actions),
                outcome.reasons,
                total_after,
                cash,
                traded,
            )
        )
    point_tuple = tuple(points)
    return StrategyReplayResult(
        config.config_version,
        "SAME_ROW_FULL_FILL_AT_SUPPLIED_EXECUTABLE_PRICE",
        point_tuple,
        tuple(audits),
        calculate_replay_metrics(point_tuple),
    )


def write_strategy_replay(
    result: StrategyReplayResult,
    report_path: str | Path,
    trajectory_path: str | Path | None = None,
) -> None:
    report = Path(report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if trajectory_path is None:
        return
    target = Path(trajectory_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "trading_date",
                "portfolio_value_cny",
                "cash_cny",
                "traded_value_cny",
            )
        )
        for point in result.points:
            writer.writerow(
                (
                    point.trading_date.isoformat(),
                    point.portfolio_value_cny,
                    point.cash_cny,
                    point.traded_value_cny,
                )
            )


def _initial_pools(config: StrategyConfig) -> CashPools:
    raw = config.raw["cash_pools"]
    tactical = raw["tactical_pool_cny"]
    return CashPools(
        Decimal(str(raw["base_pool_cny"])),
        Decimal(str(tactical["SP500"])),
        Decimal(str(tactical["NASDAQ"])),
        Decimal(str(tactical["DIVIDEND"])),
        Decimal(str(raw["strategic_cash_cny"])),
    )


def _initial_runtime(config: StrategyConfig) -> RuntimeState:
    return RuntimeState(
        config.config_version,
        _initial_pools(config),
        BaseBudgetState(Decimal("0"), frozenset()),
        tuple(
            TacticalLevelState(
                asset.asset_id, str(level["level_id"]), "ARMED"
            )
            for asset in config.assets
            for level in config.raw["tactical_levels"][asset.asset_id]
        ),
    )


def _fill_replay_advice(
    config: StrategyConfig,
    runtime: RuntimeState,
    cash: Decimal,
    quantities: dict[str, int],
    advice,
) -> tuple[RuntimeState, Decimal, dict[str, int], Decimal]:
    if advice.limit_price is None or advice.quantity <= 0:
        raise ValueError("replay received non-executable advice")
    value = Decimal(advice.quantity) * advice.limit_price
    pools = runtime.cash_pools
    next_quantities = dict(quantities)
    if advice.action == "SELL":
        if advice.quantity > next_quantities[advice.asset_id]:
            raise ValueError("replay sell exceeds available position")
        next_quantities[advice.asset_id] -= advice.quantity
        cash += value
        pools = replace(pools, strategic_cny=pools.strategic_cny + value)
        return (
            replace(runtime, cash_pools=pools),
            cash,
            next_quantities,
            value,
        )
    if value > cash:
        raise ValueError("replay buy exceeds account cash")
    cash -= value
    next_quantities[advice.asset_id] += advice.quantity
    if advice.level_id is None:
        if value > pools.base_cny or value > runtime.base_budget.available_cny:
            raise ValueError("replay base fill exceeds its funding state")
        pools = replace(pools, base_cny=pools.base_cny - value)
        runtime = replace(
            runtime,
            cash_pools=pools,
            base_budget=replace(
                runtime.base_budget,
                available_cny=runtime.base_budget.available_cny - value,
            ),
        )
        return runtime, cash, next_quantities, value
    field = {
        "SP500": "tactical_sp_cny",
        "NASDAQ": "tactical_nd_cny",
        "DIVIDEND": "tactical_dv_cny",
    }[advice.asset_id]
    available = getattr(pools, field)
    if value > available:
        raise ValueError("replay tactical fill exceeds its funding pool")
    pools = replace(pools, **{field: available - value})
    configured = next(
        item
        for item in config.raw["tactical_levels"][advice.asset_id]
        if item["level_id"] == advice.level_id
    )
    planned = Decimal(str(configured["amount_cny"]))
    updated_levels = tuple(
        replace(
            item,
            status="FILLED",
            filled_cny=min(planned, item.filled_cny + value),
        )
        if item.asset_id == advice.asset_id
        and item.level_id == advice.level_id
        else item
        for item in runtime.tactical_levels
    )
    return (
        replace(runtime, cash_pools=pools, tactical_levels=updated_levels),
        cash,
        next_quantities,
        value,
    )


def _validate_days(
    days: tuple[HistoricalTradingDay, ...],
    asset_ids: tuple[str, ...],
) -> None:
    if len(days) < 2:
        raise ValueError("strategy replay requires at least two trading days")
    dates = [item.trading_date for item in days]
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise ValueError(
            "historical replay dates must be unique and strictly increasing"
        )
    expected = set(asset_ids)
    for item in days:
        if set(item.assets) != expected:
            raise ValueError(
                f"{item.trading_date} does not cover configured assets"
            )


def _valuations_agree(
    config: StrategyConfig,
    price: Decimal,
    valuations: tuple[Decimal, Decimal],
) -> bool:
    difference = abs(
        price / valuations[0] - price / valuations[1]
    )
    return difference <= Decimal(
        str(
            config.raw["data_quality"][
                "maximum_valuation_premium_difference"
            ]
        )
    )


def _positive_decimal(value: object, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"{field} must be numeric") from error
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{field} must be a finite positive number")
    return number
