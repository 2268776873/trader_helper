from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trade_helper.cash_management import (
    CashPoolTransition,
    CashPools,
    plan_cash_event,
)
from trade_helper.config import strategy_config_from_dict
from trade_helper.ledger import Ledger, _iso, cny_to_fen


@dataclass(frozen=True)
class CashEventResult:
    event_id: str
    snapshot_id: str
    transition: CashPoolTransition
    total_assets_cny: Decimal
    available_cash_cny: Decimal


def apply_account_cash_event(
    database: str | Path,
    *,
    event_id: str,
    snapshot_id: str,
    occurred_at: datetime,
    event_type: str,
    amount_cny: Decimal,
    notes: str = "",
) -> CashEventResult:
    if occurred_at.tzinfo is None:
        raise ValueError("cash event time must include timezone")
    if event_type not in {"DEPOSIT", "WITHDRAWAL"}:
        raise ValueError("account cash event must be DEPOSIT or WITHDRAWAL")
    if amount_cny <= 0:
        raise ValueError("cash event amount must be positive")
    ledger = Ledger(database)
    ledger.initialize()
    with ledger.transaction() as connection:
        snapshot = connection.execute(
            """
            SELECT * FROM account_snapshots
            ORDER BY as_of DESC, snapshot_id DESC LIMIT 1
            """
        ).fetchone()
        if snapshot is None:
            raise ValueError("account snapshot is required before cash events")
        runtime = connection.execute(
            "SELECT * FROM strategy_runtime WHERE runtime_id = 1"
        ).fetchone()
        if runtime is None:
            raise ValueError("strategy runtime is not initialized")
        config_row = connection.execute(
            """
            SELECT content_json FROM config_versions
            WHERE config_version = ?
            """,
            (runtime["config_version"],),
        ).fetchone()
        if config_row is None:
            raise ValueError("runtime config version is missing")
        config = strategy_config_from_dict(
            json.loads(config_row["content_json"])
        )
        position_rows = connection.execute(
            """
            SELECT asset_id, etf_code, quantity, broker_market_value_fen
            FROM position_snapshots WHERE snapshot_id = ?
            """,
            (snapshot["snapshot_id"],),
        ).fetchall()
        trade_rows = connection.execute(
            """
            SELECT trade_time, asset_id, etf_code, side, quantity, price_milli
            FROM trades WHERE status = 'FILLED'
            ORDER BY trade_time, trade_id
            """
        ).fetchall()

        snapshot_at = datetime.fromisoformat(snapshot["as_of"])
        if occurred_at <= snapshot_at:
            raise ValueError("cash event must occur after the latest snapshot")
        quantities = {
            str(row["asset_id"]): int(row["quantity"])
            for row in position_rows
        }
        values = {
            str(row["asset_id"]):
            Decimal(row["broker_market_value_fen"] or 0) / 100
            for row in position_rows
        }
        codes = {
            str(row["asset_id"]): str(row["etf_code"])
            for row in position_rows
        }
        cash = (
            Decimal(snapshot["available_cash_fen"])
            + Decimal(snapshot["frozen_cash_fen"])
        ) / 100
        total = Decimal(snapshot["total_assets_fen"]) / 100
        for trade in trade_rows:
            trade_time = datetime.fromisoformat(trade["trade_time"])
            if trade_time <= snapshot_at or trade_time > occurred_at:
                continue
            asset_id = str(trade["asset_id"])
            gross = (
                Decimal(trade["quantity"])
                * Decimal(trade["price_milli"])
                / 1000
            )
            quantities.setdefault(asset_id, 0)
            values.setdefault(asset_id, Decimal("0"))
            codes.setdefault(asset_id, str(trade["etf_code"]))
            direction = 1 if trade["side"] == "BUY" else -1
            quantities[asset_id] += direction * int(trade["quantity"])
            values[asset_id] += direction * gross
            cash -= direction * gross
        if cash < 0 or any(value < 0 for value in values.values()):
            raise ValueError("projected account state is negative")
        if any(quantity < 0 for quantity in quantities.values()):
            raise ValueError("projected position quantity is negative")
        if cash + sum(values.values(), Decimal("0")) != total:
            raise ValueError("projected account state does not reconcile")

        pools = _cash_pools_from_runtime(runtime)
        if pools.total_cny != cash:
            raise ValueError(
                "strategy cash pools do not match projected account cash"
            )
        transition = plan_cash_event(
            config, pools, event_type, amount_cny
        )
        signed_amount = (
            amount_cny if event_type == "DEPOSIT" else -amount_cny
        )
        next_cash = cash + signed_amount
        next_total = total + signed_amount
        if next_cash < 0:
            raise ValueError("withdrawal exceeds available account cash")
        now_iso = _iso(occurred_at)
        connection.execute(
            """
            INSERT INTO cash_flows(
                flow_id, flow_time, flow_type, amount_fen, asset_id, notes
            ) VALUES (?, ?, ?, ?, NULL, ?)
            """,
            (
                event_id, now_iso, event_type,
                cny_to_fen(signed_amount), notes,
            ),
        )
        connection.execute(
            """
            INSERT INTO account_snapshots(
                snapshot_id, as_of, total_assets_fen, available_cash_fen,
                frozen_cash_fen, source, notes
            ) VALUES (?, ?, ?, ?, 0, 'APP_CASH_EVENT', ?)
            """,
            (
                snapshot_id, now_iso, cny_to_fen(next_total),
                cny_to_fen(next_cash), notes,
            ),
        )
        connection.executemany(
            """
            INSERT INTO position_snapshots(
                snapshot_id, asset_id, etf_code, quantity,
                broker_market_value_fen, source
            ) VALUES (?, ?, ?, ?, ?, 'APP_CASH_EVENT')
            """,
            [
                (
                    snapshot_id, asset_id, codes[asset_id],
                    quantities[asset_id], cny_to_fen(value),
                )
                for asset_id, value in values.items()
            ],
        )
        after = transition.after
        connection.execute(
            """
            UPDATE strategy_runtime SET
                base_pool_fen = ?, tactical_sp_fen = ?,
                tactical_nd_fen = ?, tactical_dv_fen = ?,
                strategic_fen = ?,
                base_budget_fen = MIN(base_budget_fen, ?),
                updated_at = ?
            WHERE runtime_id = 1
            """,
            (
                cny_to_fen(after.base_cny),
                cny_to_fen(after.tactical_sp_cny),
                cny_to_fen(after.tactical_nd_cny),
                cny_to_fen(after.tactical_dv_cny),
                cny_to_fen(after.strategic_cny),
                cny_to_fen(after.base_cny),
                now_iso,
            ),
        )
        connection.execute(
            """
            INSERT INTO cash_pool_events(
                event_id, occurred_at, event_type, amount_fen, source_ref,
                before_json, after_json, policy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"POOL-{event_id}", now_iso, event_type,
                cny_to_fen(signed_amount), event_id,
                _cash_pools_json(transition.before),
                _cash_pools_json(after),
                transition.policy,
            ),
        )
    return CashEventResult(
        event_id, snapshot_id, transition, next_total, next_cash
    )


def _cash_pools_from_runtime(row) -> CashPools:
    return CashPools(
        Decimal(row["base_pool_fen"]) / 100,
        Decimal(row["tactical_sp_fen"]) / 100,
        Decimal(row["tactical_nd_fen"]) / 100,
        Decimal(row["tactical_dv_fen"]) / 100,
        Decimal(row["strategic_fen"]) / 100,
    )


def _cash_pools_json(pools: CashPools) -> str:
    return json.dumps(
        {
            "base_cny": str(pools.base_cny),
            "tactical_sp_cny": str(pools.tactical_sp_cny),
            "tactical_nd_cny": str(pools.tactical_nd_cny),
            "tactical_dv_cny": str(pools.tactical_dv_cny),
            "strategic_cny": str(pools.strategic_cny),
            "total_cny": str(pools.total_cny),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
