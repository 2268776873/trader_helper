from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a strategy configuration is internally inconsistent."""


@dataclass(frozen=True)
class AssetConfig:
    asset_id: str
    etf_code: str
    display_name: str
    target_weight: Decimal
    min_weight: Decimal
    max_weight: Decimal


@dataclass(frozen=True)
class CashConfig:
    target_weight: Decimal
    min_weight: Decimal
    max_weight: Decimal
    strategic_floor_cny: Decimal


@dataclass(frozen=True)
class StrategyConfig:
    config_version: str
    status: str
    assets: tuple[AssetConfig, ...]
    cash: CashConfig
    raw: dict[str, Any]


def _decimal(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as error:
        raise ConfigError(f"{field} must be numeric") from error


def load_strategy_config(path: str | Path) -> StrategyConfig:
    config_path = Path(path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))

    assets = tuple(
        AssetConfig(
            asset_id=str(item["asset_id"]),
            etf_code=str(item["etf_code"]),
            display_name=str(item["display_name"]),
            target_weight=_decimal(item["target_weight"], "target_weight"),
            min_weight=_decimal(item["min_weight"], "min_weight"),
            max_weight=_decimal(item["max_weight"], "max_weight"),
        )
        for item in raw.get("assets", [])
    )
    cash_raw = raw.get("cash", {})
    cash = CashConfig(
        target_weight=_decimal(cash_raw.get("target_weight"), "cash.target_weight"),
        min_weight=_decimal(cash_raw.get("min_weight"), "cash.min_weight"),
        max_weight=_decimal(cash_raw.get("max_weight"), "cash.max_weight"),
        strategic_floor_cny=_decimal(
            cash_raw.get("strategic_floor_cny"),
            "cash.strategic_floor_cny",
        ),
    )
    config = StrategyConfig(
        config_version=str(raw.get("config_version") or ""),
        status=str(raw.get("status") or ""),
        assets=assets,
        cash=cash,
        raw=raw,
    )
    validate_strategy_config(config)
    return config


def validate_strategy_config(config: StrategyConfig) -> None:
    if not config.config_version:
        raise ConfigError("config_version is required")
    if config.status not in {"DRAFT", "ACTIVE", "RETIRED"}:
        raise ConfigError("status must be DRAFT, ACTIVE, or RETIRED")
    if len(config.assets) != 3:
        raise ConfigError("exactly three assets are required")

    asset_ids = [asset.asset_id for asset in config.assets]
    etf_codes = [asset.etf_code for asset in config.assets]
    if len(set(asset_ids)) != len(asset_ids):
        raise ConfigError("asset_id values must be unique")
    if len(set(etf_codes)) != len(etf_codes):
        raise ConfigError("etf_code values must be unique")

    for asset in config.assets:
        if len(asset.etf_code) != 6 or not asset.etf_code.isdigit():
            raise ConfigError(f"{asset.asset_id}.etf_code must be six digits")
        if not (
            Decimal("0")
            <= asset.min_weight
            <= asset.target_weight
            <= asset.max_weight
            <= Decimal("1")
        ):
            raise ConfigError(f"{asset.asset_id} weight range is invalid")

    if not (
        Decimal("0")
        <= config.cash.min_weight
        <= config.cash.target_weight
        <= config.cash.max_weight
        <= Decimal("1")
    ):
        raise ConfigError("cash weight range is invalid")
    if config.cash.strategic_floor_cny < 0:
        raise ConfigError("strategic cash floor cannot be negative")
    cash_raw = config.raw.get("cash", {})
    if cash_raw.get("internal_pool_management") != "SYSTEM_VIRTUAL_LEDGER":
        raise ConfigError("cash pools must be managed by the system virtual ledger")
    if cash_raw.get("equity_sale_for_withdrawal") != "MANUAL_STRATEGY_REVIEW_REQUIRED":
        raise ConfigError("equity sales for withdrawals must require strategy review")

    total_target = sum(
        (asset.target_weight for asset in config.assets),
        start=config.cash.target_weight,
    )
    if total_target != Decimal("1"):
        raise ConfigError(f"target weights must total 1, got {total_target}")

    initial = config.raw.get("initial_account", {})
    position_values = initial.get("position_market_values_cny", {})
    initial_total = _decimal(initial.get("total_assets_cny"), "total_assets_cny")
    initial_cash = _decimal(initial.get("cash_cny"), "cash_cny")
    positions_total = sum(
        (_decimal(value, f"position_market_values_cny.{key}") for key, value in position_values.items()),
        start=Decimal("0"),
    )
    if positions_total + initial_cash != initial_total:
        raise ConfigError("initial positions plus cash must equal total assets")

    pools = config.raw.get("cash_pools", {})
    tactical = pools.get("tactical_pool_cny", {})
    pool_total = (
        _decimal(pools.get("base_pool_cny"), "base_pool_cny")
        + _decimal(pools.get("strategic_cash_cny"), "strategic_cash_cny")
        + sum(
            (_decimal(value, f"tactical_pool_cny.{key}") for key, value in tactical.items()),
            start=Decimal("0"),
        )
    )
    if pool_total != initial_cash:
        raise ConfigError("cash pools must equal initial cash")

    execution = config.raw.get("execution", {})
    daily_limit = _decimal(execution.get("daily_buy_limit_ratio"), "daily_buy_limit_ratio")
    if not Decimal("0") < daily_limit <= Decimal("1"):
        raise ConfigError("daily_buy_limit_ratio must be within (0, 1]")
    if int(execution.get("board_lot", 0)) <= 0:
        raise ConfigError("board_lot must be positive")

    base_plan = config.raw.get("base_plan", {})
    if _decimal(base_plan.get("monthly_release_cny"), "monthly_release_cny") <= 0:
        raise ConfigError("monthly_release_cny must be positive")
    if _decimal(base_plan.get("monthly_execution_cap_cny"), "monthly_execution_cap_cny") <= 0:
        raise ConfigError("monthly_execution_cap_cny must be positive")

    tactical_levels = config.raw.get("tactical_levels", {})
    for asset in config.assets:
        levels = tactical_levels.get(asset.asset_id, [])
        if len(levels) != 3:
            raise ConfigError(f"{asset.asset_id} must define three tactical levels")
        previous_drawdown = Decimal("0")
        seen_level_ids: set[str] = set()
        for level in levels:
            level_id = str(level.get("level_id") or "")
            drawdown = _decimal(level.get("drawdown"), f"{level_id}.drawdown")
            premium_limit = _decimal(level.get("premium_limit"), f"{level_id}.premium_limit")
            amount = _decimal(level.get("amount_cny"), f"{level_id}.amount_cny")
            if not level_id or level_id in seen_level_ids:
                raise ConfigError(f"{asset.asset_id} level ids must be unique")
            if drawdown <= previous_drawdown or drawdown > Decimal("1"):
                raise ConfigError(f"{asset.asset_id} drawdowns must increase")
            if premium_limit < 0 or amount <= 0:
                raise ConfigError(f"{level_id} premium and amount are invalid")
            seen_level_ids.add(level_id)
            previous_drawdown = drawdown

    data_quality = config.raw.get("data_quality", {})
    source_count = int(data_quality.get("minimum_independent_valuation_sources", 0))
    valuation_difference = _decimal(
        data_quality.get("maximum_valuation_premium_difference"),
        "maximum_valuation_premium_difference",
    )
    if source_count < 2 or not Decimal("0") < valuation_difference <= Decimal("0.05"):
        raise ConfigError("data quality thresholds are invalid")

    ordering = config.raw.get("portfolio_ordering", {})
    if set(ordering.get("asset_order", [])) != set(asset_ids):
        raise ConfigError("portfolio asset_order must contain every configured asset")

    sell_policy = config.raw.get("sell_policy", {})
    if sell_policy.get("price_stop_loss") is not False:
        raise ConfigError("personal V1 must not enable price stop loss")
    if int(sell_policy.get("days_above_max_before_rebalance", 0)) <= 0:
        raise ConfigError("rebalance persistence days must be positive")
    hard_overweight = _decimal(
        sell_policy.get("hard_overweight_above_target"),
        "hard_overweight_above_target",
    )
    if not Decimal("0") < hard_overweight < Decimal("1"):
        raise ConfigError("hard overweight threshold is invalid")

    contributions = config.raw.get("contributions", {})
    if contributions.get("actual_cash_flows_are_authoritative") is not True:
        raise ConfigError("actual cash flows must be authoritative")
    deposit = contributions.get("deposit_allocation", {})
    base_ratio = _decimal(deposit.get("base_pool_ratio"), "base_pool_ratio")
    tactical_ratio = _decimal(deposit.get("tactical_pool_ratio"), "tactical_pool_ratio")
    if base_ratio + tactical_ratio != Decimal("1"):
        raise ConfigError("deposit base and tactical ratios must total 1")
    tactical_ratios = deposit.get("tactical_asset_ratios", {})
    tactical_total = sum(
        (
            _decimal(tactical_ratios.get(asset_id), f"tactical_asset_ratios.{asset_id}")
            for asset_id in asset_ids
        ),
        start=Decimal("0"),
    )
    if tactical_total != Decimal("1"):
        raise ConfigError("tactical asset ratios must total 1")
