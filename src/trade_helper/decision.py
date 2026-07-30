from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime, time
from decimal import Decimal
from enum import StrEnum

from trade_helper.config import StrategyConfig
from trade_helper.execution import AdviceStatus
from trade_helper.ledger import Ledger, LedgerConflict
from trade_helper.market_data import MarketSnapshot
from trade_helper.models import Readiness
from trade_helper.state_store import RuntimeState, StrategyStateStore
from trade_helper.strategy import (
    Advice,
    BasePlanInput,
    TacticalInput,
    evaluate_base_plan,
    plan_tactical_orders,
    release_monthly_base_budget,
)


class DecisionStatus(StrEnum):
    BLOCKED = "BLOCKED"
    READY = "READY"
    NO_ACTION = "NO_ACTION"


@dataclass(frozen=True)
class DecisionRequest:
    decision_id: str
    now: datetime
    reconciled: bool
    a_share_trading_day_number: int
    markets: tuple[MarketSnapshot, ...]
    tactical_inputs: tuple[TacticalInput, ...]
    base_input: BasePlanInput


@dataclass(frozen=True)
class DecisionOutcome:
    decision_id: str
    generated_at: datetime
    config_version: str
    status: DecisionStatus
    reasons: tuple[str, ...]
    advices: tuple[Advice, ...]
    runtime: RuntimeState


def run_daily_decision(
    config: StrategyConfig,
    runtime: RuntimeState,
    request: DecisionRequest,
) -> DecisionOutcome:
    reasons: list[str] = []
    start = time.fromisoformat(config.raw["execution"]["decision_time_start"])
    end = time.fromisoformat(config.raw["execution"]["decision_time_end"])
    local_time = request.now.timetz().replace(tzinfo=None)
    if not start <= local_time <= end:
        reasons.append("当前时间不在14:00至14:50决策窗口")
    if not request.reconciled:
        reasons.append("账户对账未通过：RECONCILIATION_REQUIRED")
    if len(request.markets) != len(config.assets):
        reasons.append("市场数据未覆盖全部配置资产")
    blocked_markets = [
        item.symbol for item in request.markets if item.readiness != Readiness.READY
    ]
    if blocked_markets:
        reasons.append(f"市场数据质量阻断：{','.join(blocked_markets)}")
    if runtime.config_version != config.config_version:
        reasons.append("运行状态与配置版本不一致")
    if reasons:
        return DecisionOutcome(
            request.decision_id, request.now, config.config_version,
            DecisionStatus.BLOCKED, tuple(reasons), (), runtime,
        )

    released = release_monthly_base_budget(
        config, request.now.date(), request.a_share_trading_day_number,
        runtime.base_budget,
    )
    next_runtime = replace(runtime, base_budget=released)
    tactical = plan_tactical_orders(config, request.tactical_inputs)
    advices = list(tactical)
    tactical_buy = sum(
        (item.amount_cny for item in tactical if item.action == "BUY"),
        start=Decimal("0"),
    )
    base_value = replace(
        request.base_input,
        base_pool_cny=released.available_cny,
        today_buy_cny=request.base_input.today_buy_cny + tactical_buy,
        cash_cny=request.base_input.cash_cny - tactical_buy,
    )
    base_advice = evaluate_base_plan(config, base_value)
    advices.append(base_advice)
    actionable = any(item.action in {"BUY", "SELL", "REVIEW_EXIT"} for item in advices)
    status = DecisionStatus.READY if actionable else DecisionStatus.NO_ACTION
    return DecisionOutcome(
        request.decision_id, request.now, config.config_version, status, (),
        tuple(advices), next_runtime,
    )


class DecisionStore:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    @staticmethod
    def _json(value: object) -> str:
        def encode(item):
            if isinstance(item, (datetime, Decimal, StrEnum, frozenset)):
                return sorted(item) if isinstance(item, frozenset) else str(item)
            raise TypeError(f"unsupported JSON value: {type(item)}")

        return json.dumps(value, ensure_ascii=False, default=encode, sort_keys=True)

    def save(
        self,
        outcome: DecisionOutcome,
        request: DecisionRequest,
        state_store: StrategyStateStore,
        config: StrategyConfig | None = None,
    ) -> None:
        """Persist the released-period state, followed by its immutable audit record."""
        # A repeated decision id cannot duplicate a monthly release because released
        # months are idempotent.
        state_store.save_runtime(outcome.runtime)
        try:
            with self.ledger.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO decision_runs(
                        decision_id, generated_at, config_version, status,
                        reasons_json, input_json, output_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        outcome.decision_id, outcome.generated_at.isoformat(),
                        outcome.config_version, outcome.status.value,
                        self._json(outcome.reasons),
                        self._json(asdict(request)),
                        self._json(asdict(outcome)),
                    ),
                )
                if config is not None:
                    asset_by_id = {item.asset_id: item for item in config.assets}
                    for index, item in enumerate(outcome.advices, start=1):
                        if item.action not in {"BUY", "SELL"}:
                            continue
                        asset = asset_by_id[item.asset_id]
                        connection.execute(
                            """
                            INSERT INTO advice(
                                advice_id, created_at, config_version, asset_id,
                                etf_code, side, proposed_quantity,
                                limit_price_milli, status, reason, level_id,
                                funding_pool
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                f"{outcome.decision_id}-A{index}",
                                outcome.generated_at.isoformat(),
                                outcome.config_version,
                                item.asset_id,
                                asset.etf_code,
                                item.action,
                                item.quantity,
                                int(item.limit_price * 1000),
                                AdviceStatus.PENDING_CONFIRMATION.value,
                                "；".join(item.reasons),
                                item.level_id,
                                "TACTICAL" if item.level_id else "BASE",
                            ),
                        )
        except sqlite3.IntegrityError as error:
            raise LedgerConflict(
                f"decision run conflict: {outcome.decision_id}"
            ) from error
