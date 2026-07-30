from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, ROUND_DOWN

from .config import StrategyConfig


@dataclass(frozen=True)
class TacticalInput:
    asset_id: str
    total_assets_cny: Decimal
    cash_cny: Decimal
    position_value_cny: Decimal
    today_buy_cny: Decimal
    drawdown: Decimal
    ask_price: Decimal
    nav_estimate_1: Decimal
    nav_estimate_2: Decimal
    tactical_cash_cny: Decimal
    filled_levels: frozenset[str] = frozenset()
    level_filled_cny: tuple[tuple[str, Decimal], ...] = ()
    data_valid: bool = True


@dataclass(frozen=True)
class Advice:
    action: str
    asset_id: str
    level_id: str | None
    amount_cny: Decimal
    quantity: int
    limit_price: Decimal | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class BaseCandidate:
    asset_id: str
    position_value_cny: Decimal
    ask_price: Decimal
    nav_estimate_1: Decimal
    nav_estimate_2: Decimal
    data_valid: bool = True


@dataclass(frozen=True)
class BasePlanInput:
    total_assets_cny: Decimal
    cash_cny: Decimal
    base_pool_cny: Decimal
    today_buy_cny: Decimal
    candidates: tuple[BaseCandidate, ...]


@dataclass(frozen=True)
class CycleState:
    near_high_days: int
    level_statuses: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class BaseBudgetState:
    available_cny: Decimal
    released_months: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RebalanceInput:
    asset_id: str
    total_assets_cny: Decimal
    position_value_cny: Decimal
    bid_price: Decimal
    days_above_max: int = 0
    premium: Decimal | None = None
    structural_issue: bool = False


def release_monthly_base_budget(
    config: StrategyConfig,
    today: date,
    a_share_trading_day_number: int,
    state: BaseBudgetState,
) -> BaseBudgetState:
    plan = config.raw["base_plan"]
    month = today.strftime("%Y-%m")
    if not plan["release_start"] <= month <= plan["release_end"]:
        return state
    if a_share_trading_day_number != int(plan["trading_day_number"]):
        return state
    if month in state.released_months:
        return state
    return BaseBudgetState(
        available_cny=state.available_cny + Decimal(str(plan["monthly_release_cny"])),
        released_months=state.released_months | {month},
    )


def evaluate_base_plan(config: StrategyConfig, value: BasePlanInput) -> Advice:
    execution = config.raw["execution"]
    base_plan = config.raw["base_plan"]
    daily_room = (
        value.total_assets_cny * Decimal(str(execution["daily_buy_limit_ratio"]))
        - value.today_buy_cny
    )
    cash_room = value.cash_cny - config.cash.strategic_floor_cny
    budget = min(
        value.base_pool_cny,
        Decimal(str(base_plan["monthly_execution_cap_cny"])),
        daily_room,
        cash_room,
    )
    if budget < Decimal(str(execution["minimum_order_cny"])):
        return _blocked("", None, "基础建仓可执行预算不足")

    by_id = {asset.asset_id: asset for asset in config.assets}
    ranked = sorted(
        value.candidates,
        key=lambda item: (
            value.total_assets_cny * by_id[item.asset_id].target_weight
            - item.position_value_cny
        ),
        reverse=True,
    )
    blocked_reasons: list[str] = []
    for candidate in ranked:
        asset = by_id[candidate.asset_id]
        gap = value.total_assets_cny * asset.target_weight - candidate.position_value_cny
        weight_room = value.total_assets_cny * asset.max_weight - candidate.position_value_cny
        if gap <= 0 or weight_room <= 0:
            blocked_reasons.append(f"{candidate.asset_id}无欠配空间")
            continue
        if not candidate.data_valid:
            blocked_reasons.append(f"{candidate.asset_id}数据质量未通过")
            continue
        if not _valuations_agree(config, candidate.ask_price, candidate.nav_estimate_1, candidate.nav_estimate_2):
            blocked_reasons.append(f"{candidate.asset_id}估值源差异过大")
            continue
        conservative_nav = min(candidate.nav_estimate_1, candidate.nav_estimate_2)
        premium = candidate.ask_price / conservative_nav - Decimal("1")
        rule = base_plan["premium_rules"][candidate.asset_id]
        full_limit = Decimal(str(rule["full"]))
        half_limit = Decimal(str(rule["half"]))
        if premium <= full_limit:
            ratio = Decimal("1")
        elif premium <= half_limit:
            ratio = Decimal("0.5")
        else:
            blocked_reasons.append(f"{candidate.asset_id}溢价不合格")
            continue
        amount_room = min(budget * ratio, gap, weight_room)
        advice = _make_buy_advice(
            config, candidate.asset_id, None, amount_room, candidate.ask_price,
            conservative_nav, half_limit, "基础预算、欠配和溢价均满足"
        )
        if advice.action == "BUY":
            return advice
        blocked_reasons.extend(advice.reasons)
    return Advice("BLOCKED", "", None, Decimal("0"), 0, None, tuple(blocked_reasons) or ("无合格资产",))


def evaluate_tactical(config: StrategyConfig, value: TacticalInput) -> Advice:
    asset = next(item for item in config.assets if item.asset_id == value.asset_id)
    if not value.data_valid:
        return _blocked(value.asset_id, None, "数据质量未通过")
    if not _valuations_agree(config, value.ask_price, value.nav_estimate_1, value.nav_estimate_2):
        return _blocked(value.asset_id, None, "估值源差异过大")

    levels = config.raw["tactical_levels"][value.asset_id]
    triggered = [
        level
        for level in levels
        if value.drawdown >= Decimal(str(level["drawdown"]))
        and level["level_id"] not in value.filled_levels
    ]
    if not triggered:
        return Advice("HOLD", value.asset_id, None, Decimal("0"), 0, None, ("无新回撤档位",))

    level = triggered[0]
    level_id = str(level["level_id"])
    premium_limit = Decimal(str(level["premium_limit"]))
    conservative_nav = min(value.nav_estimate_1, value.nav_estimate_2)
    premium = value.ask_price / conservative_nav - Decimal("1")
    if premium > premium_limit:
        return _blocked(value.asset_id, level_id, "场内溢价超过档位上限")

    execution = config.raw["execution"]
    daily_room = (
        value.total_assets_cny * Decimal(str(execution["daily_buy_limit_ratio"]))
        - value.today_buy_cny
    )
    cash_room = value.cash_cny - config.cash.strategic_floor_cny
    weight_room = value.total_assets_cny * asset.max_weight - value.position_value_cny
    filled_by_level = dict(value.level_filled_cny)
    planned = Decimal(str(level["amount_cny"])) - filled_by_level.get(level_id, Decimal("0"))
    amount_room = min(planned, value.tactical_cash_cny, daily_room, cash_room, weight_room)
    if amount_room < Decimal(str(execution["minimum_order_cny"])):
        return _blocked(value.asset_id, level_id, "可执行金额低于最小订单")

    return _make_buy_advice(
        config, value.asset_id, level_id, amount_room, value.ask_price,
        conservative_nav, premium_limit, "回撤与溢价均满足"
    )


def update_cycle(
    drawdown: Decimal,
    new_250_day_high: bool,
    state: CycleState,
) -> CycleState:
    near_high_days = state.near_high_days + 1 if drawdown <= Decimal("0.02") else 0
    if new_250_day_high or near_high_days >= 20:
        return CycleState(
            near_high_days=0,
            level_statuses=tuple((level_id, "ARMED") for level_id, _ in state.level_statuses),
        )
    return CycleState(near_high_days=near_high_days, level_statuses=state.level_statuses)


def plan_tactical_orders(
    config: StrategyConfig,
    values: tuple[TacticalInput, ...],
) -> tuple[Advice, ...]:
    asset_order = {
        asset_id: index
        for index, asset_id in enumerate(config.raw["portfolio_ordering"]["asset_order"])
    }
    asset_by_id = {asset.asset_id: asset for asset in config.assets}

    def priority(value: TacticalInput) -> tuple[Decimal, Decimal, int]:
        levels = config.raw["tactical_levels"][value.asset_id]
        depth = sum(
            1 for level in levels
            if value.drawdown >= Decimal(str(level["drawdown"]))
        )
        gap = (
            value.total_assets_cny * asset_by_id[value.asset_id].target_weight
            - value.position_value_cny
        )
        return (-Decimal(depth), -gap, asset_order[value.asset_id])

    ordered = sorted(values, key=priority)
    advices: list[Advice] = []
    shared_today_buy = max((value.today_buy_cny for value in values), default=Decimal("0"))
    shared_cash = min((value.cash_cny for value in values), default=Decimal("0"))
    for value in ordered:
        advice = evaluate_tactical(
            config,
            replace(value, today_buy_cny=shared_today_buy, cash_cny=shared_cash),
        )
        advices.append(advice)
        if advice.action == "BUY":
            shared_today_buy += advice.amount_cny
            shared_cash -= advice.amount_cny
    return tuple(advices)


def evaluate_rebalance(config: StrategyConfig, value: RebalanceInput) -> Advice:
    asset = next(item for item in config.assets if item.asset_id == value.asset_id)
    policy = config.raw["sell_policy"]
    if value.structural_issue:
        return Advice(
            "REVIEW_EXIT", value.asset_id, None, Decimal("0"), 0, value.bid_price,
            ("产品发生结构性变化，需人工评估替代方案",),
        )
    current_weight = value.position_value_cny / value.total_assets_cny
    hard_limit = asset.target_weight + Decimal(str(policy["hard_overweight_above_target"]))
    persistent = (
        current_weight > asset.max_weight
        and value.days_above_max >= int(policy["days_above_max_before_rebalance"])
    )
    extreme_premium = (
        value.premium is not None
        and value.premium >= Decimal(str(policy["extreme_qdii_premium"]))
        and value.asset_id in {"SP500", "NASDAQ"}
        and current_weight > asset.target_weight
    )
    if not (current_weight >= hard_limit or persistent or extreme_premium):
        return Advice("HOLD", value.asset_id, None, Decimal("0"), 0, None, ("无需卖出再平衡",))
    target_weight = asset.target_weight if extreme_premium else asset.max_weight
    sell_value = value.position_value_cny - value.total_assets_cny * target_weight
    lot = int(config.raw["execution"]["board_lot"])
    quantity = int((sell_value / value.bid_price / lot).to_integral_value(rounding=ROUND_DOWN)) * lot
    amount = (value.bid_price * quantity).quantize(Decimal("0.01"))
    if quantity <= 0:
        return Advice("HOLD", value.asset_id, None, Decimal("0"), 0, None, ("整手取整后无需卖出",))
    reason = "极端QDII溢价，卖出超过目标的部分" if extreme_premium else "持续或严重超配，卖回允许上限"
    return Advice("SELL", value.asset_id, None, amount, quantity, value.bid_price, (reason,))


def apply_fill(planned_cny: Decimal, previously_filled_cny: Decimal, actual_cny: Decimal) -> tuple[str, Decimal]:
    if actual_cny < 0:
        raise ValueError("actual fill cannot be negative")
    filled = min(planned_cny, previously_filled_cny + actual_cny)
    return ("FILLED" if filled >= planned_cny else "PARTIALLY_FILLED", filled)


def _make_buy_advice(
    config: StrategyConfig,
    asset_id: str,
    level_id: str | None,
    amount_room: Decimal,
    ask_price: Decimal,
    conservative_nav: Decimal,
    premium_limit: Decimal,
    reason: str,
) -> Advice:
    execution = config.raw["execution"]
    max_price = (conservative_nav * (Decimal("1") + premium_limit)).quantize(
        Decimal("0.001"), rounding=ROUND_DOWN
    )
    if ask_price > max_price:
        return _blocked(asset_id, level_id, "卖一价超过最高允许买价")
    limit_price = ask_price
    lot = int(execution["board_lot"])
    quantity = int((amount_room / limit_price / lot).to_integral_value(rounding=ROUND_DOWN)) * lot
    amount = (limit_price * quantity).quantize(Decimal("0.01"))
    if amount < Decimal(str(execution["minimum_order_cny"])):
        return _blocked(asset_id, level_id, "整手取整后低于最小订单")
    return Advice("BUY", asset_id, level_id, amount, quantity, limit_price, (reason,))


def _blocked(asset_id: str, level_id: str | None, reason: str) -> Advice:
    return Advice("BLOCKED", asset_id, level_id, Decimal("0"), 0, None, (reason,))


def _valuations_agree(
    config: StrategyConfig,
    ask_price: Decimal,
    nav_1: Decimal,
    nav_2: Decimal,
) -> bool:
    premium_difference = abs(ask_price / nav_1 - ask_price / nav_2)
    limit = Decimal(str(config.raw["data_quality"]["maximum_valuation_premium_difference"]))
    return premium_difference <= limit
