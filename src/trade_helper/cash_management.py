from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .config import StrategyConfig


@dataclass(frozen=True)
class CashPools:
    base_cny: Decimal
    tactical_sp_cny: Decimal
    tactical_nd_cny: Decimal
    tactical_dv_cny: Decimal
    strategic_cny: Decimal

    @property
    def total_cny(self) -> Decimal:
        return (
            self.base_cny
            + self.tactical_sp_cny
            + self.tactical_nd_cny
            + self.tactical_dv_cny
            + self.strategic_cny
        )


@dataclass(frozen=True)
class CashPoolTransition:
    event_type: str
    amount_cny: Decimal
    before: CashPools
    after: CashPools
    policy: str

    @property
    def allocations(self) -> tuple[tuple[str, Decimal], ...]:
        return tuple(
            (name, after - before)
            for name, before, after in (
                ("BASE", self.before.base_cny, self.after.base_cny),
                (
                    "TACTICAL_SP500",
                    self.before.tactical_sp_cny,
                    self.after.tactical_sp_cny,
                ),
                (
                    "TACTICAL_NASDAQ",
                    self.before.tactical_nd_cny,
                    self.after.tactical_nd_cny,
                ),
                (
                    "TACTICAL_DIVIDEND",
                    self.before.tactical_dv_cny,
                    self.after.tactical_dv_cny,
                ),
                (
                    "STRATEGIC",
                    self.before.strategic_cny,
                    self.after.strategic_cny,
                ),
            )
        )


def plan_cash_event(
    config: StrategyConfig,
    pools: CashPools,
    event_type: str,
    amount_cny: Decimal,
) -> CashPoolTransition:
    if amount_cny <= 0:
        raise ValueError("cash event amount must be positive")
    if event_type == "DEPOSIT":
        after = apply_actual_cash_flow(config, pools, amount_cny)
        policy = "CONFIG_DEPOSIT_70_30_WITH_TACTICAL_ASSET_RATIOS"
    elif event_type == "WITHDRAWAL":
        after = apply_actual_cash_flow(config, pools, -amount_cny)
        policy = "BASE_THEN_TACTICAL_PRO_RATA_THEN_STRATEGIC"
    elif event_type == "SELL_PROCEEDS":
        after = CashPools(
            pools.base_cny,
            pools.tactical_sp_cny,
            pools.tactical_nd_cny,
            pools.tactical_dv_cny,
            pools.strategic_cny + amount_cny,
        )
        policy = "APPROVED_OPTION_A_TO_STRATEGIC_CASH"
    else:
        raise ValueError(f"unsupported cash event type: {event_type}")
    expected = (
        pools.total_cny - amount_cny
        if event_type == "WITHDRAWAL"
        else pools.total_cny + amount_cny
    )
    if after.total_cny != expected:
        raise ValueError("cash pool transition does not conserve cash")
    return CashPoolTransition(event_type, amount_cny, pools, after, policy)


def apply_actual_cash_flow(
    config: StrategyConfig,
    pools: CashPools,
    amount_cny: Decimal,
) -> CashPools:
    if amount_cny == 0:
        raise ValueError("cash flow cannot be zero")
    if amount_cny > 0:
        return _apply_deposit(config, pools, amount_cny)
    return _apply_withdrawal(pools, -amount_cny)


def buying_is_blocked(config: StrategyConfig, pools: CashPools) -> bool:
    return pools.total_cny < config.cash.strategic_floor_cny


def _apply_deposit(
    config: StrategyConfig,
    pools: CashPools,
    amount: Decimal,
) -> CashPools:
    allocation = config.raw["contributions"]["deposit_allocation"]
    base_add = amount * Decimal(str(allocation["base_pool_ratio"]))
    tactical_add = amount - base_add
    ratios = allocation["tactical_asset_ratios"]
    sp_add = tactical_add * Decimal(str(ratios["SP500"]))
    nd_add = tactical_add * Decimal(str(ratios["NASDAQ"]))
    dv_add = tactical_add - sp_add - nd_add
    return CashPools(
        pools.base_cny + base_add,
        pools.tactical_sp_cny + sp_add,
        pools.tactical_nd_cny + nd_add,
        pools.tactical_dv_cny + dv_add,
        pools.strategic_cny,
    )


def _apply_withdrawal(pools: CashPools, amount: Decimal) -> CashPools:
    if amount > pools.total_cny:
        raise ValueError("withdrawal exceeds strategy cash")
    base_take = min(amount, pools.base_cny)
    remaining = amount - base_take
    tactical_total = pools.tactical_sp_cny + pools.tactical_nd_cny + pools.tactical_dv_cny
    tactical_take = min(remaining, tactical_total)
    if tactical_total > 0:
        sp_take = tactical_take * pools.tactical_sp_cny / tactical_total
        nd_take = tactical_take * pools.tactical_nd_cny / tactical_total
    else:
        sp_take = Decimal("0")
        nd_take = Decimal("0")
    dv_take = tactical_take - sp_take - nd_take
    strategic_take = remaining - tactical_take
    return CashPools(
        pools.base_cny - base_take,
        pools.tactical_sp_cny - sp_take,
        pools.tactical_nd_cny - nd_take,
        pools.tactical_dv_cny - dv_take,
        pools.strategic_cny - strategic_take,
    )
