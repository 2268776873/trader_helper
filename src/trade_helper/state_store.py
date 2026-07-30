from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trade_helper.cash_management import CashPools
from trade_helper.config import StrategyConfig
from trade_helper.ledger import Ledger, LedgerConflict, cny_to_fen
from trade_helper.strategy import BaseBudgetState


LEVEL_STATUSES = {"ARMED", "TRIGGERED", "PARTIALLY_FILLED", "FILLED", "DISABLED"}


@dataclass(frozen=True)
class TacticalLevelState:
    asset_id: str
    level_id: str
    status: str
    filled_cny: Decimal = Decimal("0")
    near_high_days: int = 0


@dataclass(frozen=True)
class RuntimeState:
    config_version: str
    cash_pools: CashPools
    base_budget: BaseBudgetState
    tactical_levels: tuple[TacticalLevelState, ...]


def _fen_to_cny(value: int) -> Decimal:
    return Decimal(value) / Decimal(100)


class StrategyStateStore:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def save_config(self, config: StrategyConfig) -> bool:
        canonical = json.dumps(
            config.raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self.ledger.transaction() as connection:
            existing = connection.execute(
                """
                SELECT content_hash FROM config_versions WHERE config_version = ?
                """,
                (config.config_version,),
            ).fetchone()
            if existing is not None:
                if existing["content_hash"] != digest:
                    raise LedgerConflict(
                        f"config version is immutable: {config.config_version}"
                    )
                return False
            connection.execute(
                """
                INSERT INTO config_versions(
                    config_version, status, effective_at, content_json, content_hash
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    config.config_version, config.status,
                    str(config.raw.get("effective_date", "")), canonical, digest,
                ),
            )
        return True

    def initialize_runtime(self, config: StrategyConfig) -> RuntimeState:
        self.save_config(config)
        pools_raw = config.raw["cash_pools"]
        tactical = pools_raw["tactical_pool_cny"]
        pools = CashPools(
            Decimal(str(pools_raw["base_pool_cny"])),
            Decimal(str(tactical["SP500"])),
            Decimal(str(tactical["NASDAQ"])),
            Decimal(str(tactical["DIVIDEND"])),
            Decimal(str(pools_raw["strategic_cash_cny"])),
        )
        levels = tuple(
            TacticalLevelState(asset.asset_id, str(level["level_id"]), "ARMED")
            for asset in config.assets
            for level in config.raw["tactical_levels"][asset.asset_id]
        )
        state = RuntimeState(
            config.config_version,
            pools,
            BaseBudgetState(Decimal("0"), frozenset()),
            levels,
        )
        try:
            self.save_runtime(state)
        except LedgerConflict:
            return self.load_runtime()
        return state

    def save_runtime(self, state: RuntimeState) -> None:
        now = datetime.now().astimezone().isoformat()
        if len({(item.asset_id, item.level_id) for item in state.tactical_levels}) != len(
            state.tactical_levels
        ):
            raise ValueError("tactical level keys must be unique")
        for item in state.tactical_levels:
            if item.status not in LEVEL_STATUSES:
                raise ValueError(f"invalid tactical level status: {item.status}")
            if item.filled_cny < 0 or item.near_high_days < 0:
                raise ValueError("tactical state values must be non-negative")
        pools = state.cash_pools
        try:
            with self.ledger.transaction() as connection:
                exists = connection.execute(
                    "SELECT 1 FROM strategy_runtime WHERE runtime_id = 1"
                ).fetchone()
                if exists is None:
                    connection.execute(
                        """
                        INSERT INTO strategy_runtime(
                            runtime_id, config_version, base_pool_fen,
                            tactical_sp_fen, tactical_nd_fen, tactical_dv_fen,
                            strategic_fen, base_budget_fen, released_months_json,
                            updated_at
                        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        self._runtime_values(state, now),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE strategy_runtime SET
                            config_version = ?, base_pool_fen = ?,
                            tactical_sp_fen = ?, tactical_nd_fen = ?,
                            tactical_dv_fen = ?, strategic_fen = ?,
                            base_budget_fen = ?, released_months_json = ?,
                            updated_at = ?
                        WHERE runtime_id = 1
                        """,
                        self._runtime_values(state, now),
                    )
                connection.execute("DELETE FROM tactical_level_state")
                connection.executemany(
                    """
                    INSERT INTO tactical_level_state(
                        asset_id, level_id, sort_order, status, filled_fen,
                        near_high_days, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.asset_id, item.level_id, index, item.status,
                            cny_to_fen(item.filled_cny), item.near_high_days, now,
                        )
                        for index, item in enumerate(state.tactical_levels)
                    ],
                )
        except sqlite3.IntegrityError as error:
            raise LedgerConflict("runtime state conflicts with persisted data") from error

    @staticmethod
    def _runtime_values(state: RuntimeState, now: str) -> tuple[object, ...]:
        pools = state.cash_pools
        return (
            state.config_version,
            cny_to_fen(pools.base_cny),
            cny_to_fen(pools.tactical_sp_cny),
            cny_to_fen(pools.tactical_nd_cny),
            cny_to_fen(pools.tactical_dv_cny),
            cny_to_fen(pools.strategic_cny),
            cny_to_fen(state.base_budget.available_cny),
            json.dumps(sorted(state.base_budget.released_months)),
            now,
        )

    def load_runtime(self) -> RuntimeState:
        with closing(self.ledger.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM strategy_runtime WHERE runtime_id = 1"
            ).fetchone()
            if row is None:
                raise ValueError("strategy runtime is not initialized")
            level_rows = connection.execute(
                """
                SELECT asset_id, level_id, status, filled_fen, near_high_days
                FROM tactical_level_state ORDER BY sort_order
                """
            ).fetchall()
        return RuntimeState(
            str(row["config_version"]),
            CashPools(
                _fen_to_cny(row["base_pool_fen"]),
                _fen_to_cny(row["tactical_sp_fen"]),
                _fen_to_cny(row["tactical_nd_fen"]),
                _fen_to_cny(row["tactical_dv_fen"]),
                _fen_to_cny(row["strategic_fen"]),
            ),
            BaseBudgetState(
                _fen_to_cny(row["base_budget_fen"]),
                frozenset(json.loads(row["released_months_json"])),
            ),
            tuple(
                TacticalLevelState(
                    item["asset_id"], item["level_id"], item["status"],
                    _fen_to_cny(item["filled_fen"]), item["near_high_days"],
                )
                for item in level_rows
            ),
        )
