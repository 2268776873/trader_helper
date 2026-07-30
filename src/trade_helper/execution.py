from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from trade_helper.cash_management import CashPools, plan_cash_event
from trade_helper.config import strategy_config_from_dict
from trade_helper.ledger import (
    Ledger, LedgerConflict, _iso, cny_to_fen, price_to_milli,
)


class AdviceStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Advice:
    advice_id: str
    created_at: datetime
    config_version: str
    asset_id: str
    etf_code: str
    side: str
    proposed_quantity: int
    limit_price: Decimal
    reason: str
    level_id: str | None = None
    funding_pool: str | None = None


@dataclass(frozen=True)
class OrderAttempt:
    attempt_id: str
    advice_id: str
    attempted_at: datetime
    status: AdviceStatus
    broker_order_id: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class Fill:
    fill_id: str
    advice_id: str
    filled_at: datetime
    quantity: int
    price: Decimal
    attempt_id: str | None = None


class ExecutionLedger:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def create_advice(self, advice: Advice) -> None:
        if advice.side not in {"BUY", "SELL"}:
            raise ValueError("advice side must be BUY or SELL")
        if advice.proposed_quantity <= 0:
            raise ValueError("proposed quantity must be positive")
        try:
            with self.ledger.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO advice(
                        advice_id, created_at, config_version, asset_id, etf_code,
                        side, proposed_quantity, limit_price_milli, status, reason,
                        level_id, funding_pool
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        advice.advice_id, _iso(advice.created_at),
                        advice.config_version, advice.asset_id, advice.etf_code,
                        advice.side, advice.proposed_quantity,
                        price_to_milli(advice.limit_price),
                        AdviceStatus.PENDING_CONFIRMATION.value, advice.reason,
                        advice.level_id, advice.funding_pool,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise LedgerConflict(f"advice conflict: {advice.advice_id}") from error

    def record_attempt(self, attempt: OrderAttempt) -> None:
        allowed = {
            AdviceStatus.NOT_ATTEMPTED,
            AdviceStatus.ORDER_SUBMITTED,
            AdviceStatus.CANCELLED,
            AdviceStatus.EXPIRED,
            AdviceStatus.REJECTED,
        }
        if attempt.status not in allowed:
            raise ValueError("attempt status cannot claim an unrecorded fill")
        try:
            with self.ledger.transaction() as connection:
                advice = connection.execute(
                    "SELECT status FROM advice WHERE advice_id = ?",
                    (attempt.advice_id,),
                ).fetchone()
                if advice is None:
                    raise ValueError("unknown advice_id")
                if advice["status"] == AdviceStatus.FILLED.value:
                    raise ValueError("filled advice cannot receive another attempt")
                connection.execute(
                    """
                    INSERT INTO order_attempts(
                        attempt_id, advice_id, attempted_at, status,
                        broker_order_id, notes
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt.attempt_id, attempt.advice_id,
                        _iso(attempt.attempted_at), attempt.status.value,
                        attempt.broker_order_id, attempt.notes,
                    ),
                )
                connection.execute(
                    "UPDATE advice SET status = ? WHERE advice_id = ?",
                    (attempt.status.value, attempt.advice_id),
                )
        except sqlite3.IntegrityError as error:
            raise LedgerConflict(f"attempt conflict: {attempt.attempt_id}") from error

    def record_fill(self, fill: Fill) -> AdviceStatus:
        if fill.quantity <= 0:
            raise ValueError("fill quantity must be positive")
        try:
            with self.ledger.transaction() as connection:
                advice = connection.execute(
                    """
                    SELECT asset_id, etf_code, side, proposed_quantity,
                           config_version, level_id, funding_pool
                    FROM advice WHERE advice_id = ?
                    """,
                    (fill.advice_id,),
                ).fetchone()
                if advice is None:
                    raise ValueError("unknown advice_id")
                if fill.attempt_id is not None:
                    attempt = connection.execute(
                        """
                        SELECT 1 FROM order_attempts
                        WHERE attempt_id = ? AND advice_id = ?
                        """,
                        (fill.attempt_id, fill.advice_id),
                    ).fetchone()
                    if attempt is None:
                        raise ValueError("attempt does not belong to advice")
                prior = connection.execute(
                    "SELECT COALESCE(SUM(quantity), 0) AS quantity FROM advice_fills WHERE advice_id = ?",
                    (fill.advice_id,),
                ).fetchone()
                total = int(prior["quantity"]) + fill.quantity
                if total > int(advice["proposed_quantity"]):
                    raise ValueError("filled quantity exceeds proposed quantity")
                status = (
                    AdviceStatus.FILLED
                    if total == int(advice["proposed_quantity"])
                    else AdviceStatus.PARTIALLY_FILLED
                )
                actual_fen = cny_to_fen(
                    Decimal(fill.quantity) * fill.price
                )
                if advice["funding_pool"]:
                    if advice["side"] == "BUY":
                        self._apply_buy_fill_state(
                            connection, advice, actual_fen, status,
                            fill.filled_at,
                        )
                    else:
                        self._apply_sell_fill_state(
                            connection, advice, actual_fen, fill.filled_at,
                            fill.fill_id,
                        )
                connection.execute(
                    """
                    INSERT INTO advice_fills(
                        fill_id, advice_id, attempt_id, filled_at, quantity, price_milli
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fill.fill_id, fill.advice_id, fill.attempt_id,
                        _iso(fill.filled_at), fill.quantity, price_to_milli(fill.price),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO trades(
                        trade_id, trade_time, asset_id, etf_code, side,
                        quantity, price_milli, status, source, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'FILLED', 'APP_FORM', ?)
                    """,
                    (
                        fill.fill_id, _iso(fill.filled_at), advice["asset_id"],
                        advice["etf_code"], advice["side"], fill.quantity,
                        price_to_milli(fill.price), f"advice:{fill.advice_id}",
                    ),
                )
                connection.execute(
                    "UPDATE advice SET status = ? WHERE advice_id = ?",
                    (status.value, fill.advice_id),
                )
                return status
        except sqlite3.IntegrityError as error:
            raise LedgerConflict(f"fill conflict: {fill.fill_id}") from error

    @staticmethod
    def _apply_buy_fill_state(
        connection: sqlite3.Connection,
        advice: sqlite3.Row,
        actual_fen: int,
        advice_status: AdviceStatus,
        filled_at: datetime,
    ) -> None:
        runtime = connection.execute(
            "SELECT * FROM strategy_runtime WHERE runtime_id = 1"
        ).fetchone()
        if runtime is None:
            raise ValueError("strategy runtime is not initialized")
        pool = advice["funding_pool"]
        if pool == "BASE":
            if (
                int(runtime["base_pool_fen"]) < actual_fen
                or int(runtime["base_budget_fen"]) < actual_fen
            ):
                raise ValueError("base funding pool is insufficient for fill")
            connection.execute(
                """
                UPDATE strategy_runtime SET
                    base_pool_fen = base_pool_fen - ?,
                    base_budget_fen = base_budget_fen - ?,
                    updated_at = ?
                WHERE runtime_id = 1
                """,
                (actual_fen, actual_fen, _iso(filled_at)),
            )
            return
        if pool != "TACTICAL":
            raise ValueError(f"unknown advice funding pool: {pool}")
        level_id = advice["level_id"]
        if not level_id:
            raise ValueError("tactical advice is missing level_id")
        column_by_asset = {
            "SP500": "tactical_sp_fen",
            "NASDAQ": "tactical_nd_fen",
            "DIVIDEND": "tactical_dv_fen",
        }
        column = column_by_asset.get(advice["asset_id"])
        if column is None:
            raise ValueError("tactical advice has unknown asset")
        if int(runtime[column]) < actual_fen:
            raise ValueError("tactical funding pool is insufficient for fill")
        level = connection.execute(
            """
            SELECT filled_fen FROM tactical_level_state
            WHERE asset_id = ? AND level_id = ?
            """,
            (advice["asset_id"], level_id),
        ).fetchone()
        if level is None:
            raise ValueError("tactical level state is missing")
        config_row = connection.execute(
            "SELECT content_json FROM config_versions WHERE config_version = ?",
            (advice["config_version"],),
        ).fetchone()
        if config_row is None:
            raise ValueError("advice config version is missing")
        config = json.loads(config_row["content_json"])
        configured_level = next(
            (
                item
                for item in config["tactical_levels"][advice["asset_id"]]
                if item["level_id"] == level_id
            ),
            None,
        )
        if configured_level is None:
            raise ValueError("advice level is absent from its config version")
        planned_fen = cny_to_fen(configured_level["amount_cny"])
        filled_fen = min(
            planned_fen, int(level["filled_fen"]) + actual_fen
        )
        level_status = (
            "FILLED"
            if advice_status == AdviceStatus.FILLED
            or filled_fen >= planned_fen
            else "PARTIALLY_FILLED"
        )
        connection.execute(
            f"""
            UPDATE strategy_runtime SET
                {column} = {column} - ?,
                updated_at = ?
            WHERE runtime_id = 1
            """,
            (actual_fen, _iso(filled_at)),
        )
        connection.execute(
            """
            UPDATE tactical_level_state SET
                status = ?, filled_fen = ?, updated_at = ?
            WHERE asset_id = ? AND level_id = ?
            """,
            (
                level_status, filled_fen, _iso(filled_at),
                advice["asset_id"], level_id,
            ),
        )

    @staticmethod
    def _apply_sell_fill_state(
        connection: sqlite3.Connection,
        advice: sqlite3.Row,
        actual_fen: int,
        filled_at: datetime,
        fill_id: str,
    ) -> None:
        if advice["funding_pool"] != "STRATEGIC":
            raise ValueError(
                "sell proceeds must be assigned to strategic cash"
            )
        runtime = connection.execute(
            "SELECT * FROM strategy_runtime WHERE runtime_id = 1"
        ).fetchone()
        if runtime is None:
            raise ValueError("strategy runtime is not initialized")
        config_row = connection.execute(
            "SELECT content_json FROM config_versions WHERE config_version = ?",
            (advice["config_version"],),
        ).fetchone()
        if config_row is None:
            raise ValueError("advice config version is missing")
        config = strategy_config_from_dict(
            json.loads(config_row["content_json"])
        )
        before = CashPools(
            Decimal(runtime["base_pool_fen"]) / 100,
            Decimal(runtime["tactical_sp_fen"]) / 100,
            Decimal(runtime["tactical_nd_fen"]) / 100,
            Decimal(runtime["tactical_dv_fen"]) / 100,
            Decimal(runtime["strategic_fen"]) / 100,
        )
        transition = plan_cash_event(
            config,
            before,
            "SELL_PROCEEDS",
            Decimal(actual_fen) / 100,
        )
        connection.execute(
            """
            UPDATE strategy_runtime SET
                base_pool_fen = ?,
                tactical_sp_fen = ?,
                tactical_nd_fen = ?,
                tactical_dv_fen = ?,
                strategic_fen = ?,
                updated_at = ?
            WHERE runtime_id = 1
            """,
            (
                cny_to_fen(transition.after.base_cny),
                cny_to_fen(transition.after.tactical_sp_cny),
                cny_to_fen(transition.after.tactical_nd_cny),
                cny_to_fen(transition.after.tactical_dv_cny),
                cny_to_fen(transition.after.strategic_cny),
                _iso(filled_at),
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
                f"POOL-{fill_id}",
                _iso(filled_at),
                transition.event_type,
                actual_fen,
                fill_id,
                ExecutionLedger._cash_pools_json(transition.before),
                ExecutionLedger._cash_pools_json(transition.after),
                transition.policy,
            ),
        )

    @staticmethod
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

    def status(self, advice_id: str) -> AdviceStatus:
        with closing(self.ledger.connect()) as connection:
            row = connection.execute(
                "SELECT status FROM advice WHERE advice_id = ?", (advice_id,)
            ).fetchone()
        if row is None:
            raise ValueError("unknown advice_id")
        return AdviceStatus(row["status"])
