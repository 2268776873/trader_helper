from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime
from decimal import Decimal

from trade_helper.config import StrategyConfig
from trade_helper.decision import (
    DecisionOutcome,
    DecisionRequest,
    DecisionStore,
    run_daily_decision,
)
from trade_helper.ledger import Ledger
from trade_helper.market_data import MarketSnapshot
from trade_helper.models import Readiness
from trade_helper.reference_series import ReferenceSeriesStore
from trade_helper.state_store import StrategyStateStore
from trade_helper.strategy import BaseCandidate, BasePlanInput, TacticalInput


class DecisionInputError(RuntimeError):
    pass


class DailyDecisionService:
    def __init__(self, ledger: Ledger, config: StrategyConfig) -> None:
        self.ledger = ledger
        self.config = config
        self.states = StrategyStateStore(ledger)

    def build_request(
        self,
        *,
        decision_id: str,
        now: datetime,
        a_share_trading_day_number: int,
    ) -> DecisionRequest:
        if now.tzinfo is None:
            raise ValueError("decision time must include timezone")
        runtime = self.states.initialize_runtime(self.config)
        with closing(self.ledger.connect()) as connection:
            snapshot = connection.execute(
                """
                SELECT * FROM account_snapshots
                ORDER BY as_of DESC, snapshot_id DESC LIMIT 1
                """
            ).fetchone()
            if snapshot is None:
                raise DecisionInputError("账户尚无快照，无法构建决策输入")
            positions = connection.execute(
                """
                SELECT asset_id, etf_code, broker_market_value_fen
                FROM position_snapshots WHERE snapshot_id = ?
                """,
                (snapshot["snapshot_id"],),
            ).fetchall()
            market_rows = connection.execute(
                """
                SELECT m.* FROM market_snapshots m
                JOIN (
                    SELECT symbol, MAX(observed_at) AS observed_at
                    FROM market_snapshots GROUP BY symbol
                ) latest
                ON latest.symbol = m.symbol
                AND latest.observed_at = m.observed_at
                """
            ).fetchall()
            trade_rows = connection.execute(
                "SELECT trade_time, side, quantity, price_milli FROM trades"
            ).fetchall()
        total = Decimal(snapshot["total_assets_fen"]) / 100
        cash = (
            Decimal(snapshot["available_cash_fen"])
            + Decimal(snapshot["frozen_cash_fen"])
        ) / 100
        values = {
            row["asset_id"]: Decimal(row["broker_market_value_fen"] or 0) / 100
            for row in positions
        }
        reconciled = cash + sum(values.values(), start=Decimal("0")) == total
        today_buy = sum(
            (
                Decimal(row["quantity"]) * Decimal(row["price_milli"]) / 1000
                for row in trade_rows
                if row["side"] == "BUY"
                and datetime.fromisoformat(row["trade_time"]).date() == now.date()
            ),
            start=Decimal("0"),
        )
        market_by_symbol = {row["symbol"]: row for row in market_rows}
        reference = ReferenceSeriesStore(self.ledger)
        markets: list[MarketSnapshot] = []
        tactical: list[TacticalInput] = []
        base_candidates: list[BaseCandidate] = []
        level_states = {
            item.asset_id: [] for item in runtime.tactical_levels
        }
        for item in runtime.tactical_levels:
            level_states.setdefault(item.asset_id, []).append(item)
        pool_by_asset = {
            "SP500": runtime.cash_pools.tactical_sp_cny,
            "NASDAQ": runtime.cash_pools.tactical_nd_cny,
            "DIVIDEND": runtime.cash_pools.tactical_dv_cny,
        }
        for asset in self.config.assets:
            row = market_by_symbol.get(asset.etf_code)
            reasons: list[str] = []
            payload: dict[str, object] = {}
            if row is None:
                readiness = Readiness.BLOCKED
                generated_at = now
                reasons.append("缺少市场快照")
            else:
                readiness = Readiness(row["readiness"])
                generated_at = datetime.fromisoformat(row["observed_at"])
                payload = json.loads(row["payload_json"])
                reasons.extend(json.loads(row["reasons_json"]))
            try:
                drawdown = reference.drawdown(asset.asset_id, now.date()).drawdown
            except ValueError as error:
                drawdown = Decimal("0")
                readiness = Readiness.BLOCKED
                reasons.append(str(error))
            valuations = [
                Decimal(str(item["value"]))
                for item in payload.get("observations", [])
                if item.get("kind") == "VALUATION" and item.get("value") is not None
            ]
            ask_raw = payload.get("selected_ask")
            data_valid = (
                readiness == Readiness.READY
                and ask_raw is not None
                and len(valuations) >= 2
            )
            if not data_valid:
                reasons.append("缺少可执行卖一价或双估值")
            ask = Decimal(str(ask_raw)) if ask_raw is not None else Decimal("1")
            nav_1 = valuations[0] if valuations else Decimal("1")
            nav_2 = valuations[1] if len(valuations) > 1 else nav_1
            markets.append(
                MarketSnapshot(
                    row["snapshot_id"] if row else f"MISSING-{asset.etf_code}",
                    asset.etf_code, generated_at, readiness, tuple(reasons),
                    (), (), ask if ask_raw is not None else None,
                    min(valuations) if valuations else None,
                )
            )
            states = level_states.get(asset.asset_id, [])
            tactical.append(
                TacticalInput(
                    asset.asset_id, total, cash, values.get(asset.asset_id, Decimal("0")),
                    today_buy, drawdown, ask, nav_1, nav_2,
                    pool_by_asset[asset.asset_id],
                    frozenset(item.level_id for item in states if item.status == "FILLED"),
                    tuple((item.level_id, item.filled_cny) for item in states),
                    data_valid,
                )
            )
            base_candidates.append(
                BaseCandidate(
                    asset.asset_id, values.get(asset.asset_id, Decimal("0")),
                    ask, nav_1, nav_2, data_valid,
                )
            )
        return DecisionRequest(
            decision_id, now, reconciled, a_share_trading_day_number,
            tuple(markets), tuple(tactical),
            BasePlanInput(
                total, cash, runtime.base_budget.available_cny, today_buy,
                tuple(base_candidates),
            ),
        )

    def execute(
        self,
        *,
        decision_id: str,
        now: datetime,
        a_share_trading_day_number: int,
    ) -> DecisionOutcome:
        runtime = self.states.initialize_runtime(self.config)
        request = self.build_request(
            decision_id=decision_id,
            now=now,
            a_share_trading_day_number=a_share_trading_day_number,
        )
        outcome = run_daily_decision(self.config, runtime, request)
        DecisionStore(self.ledger).save(
            outcome, request, self.states, self.config
        )
        return outcome
