from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trade_helper.ledger import Ledger
from trade_helper.models import Readiness


@dataclass(frozen=True)
class AssetDashboard:
    asset_id: str
    name: str
    code: str
    market_value_cny: Decimal
    weight: Decimal
    target_weight: Decimal
    drawdown: Decimal | None
    premium: Decimal | None
    state: str


@dataclass(frozen=True)
class AdviceDashboard:
    advice_id: str
    created_at: datetime
    asset_id: str
    code: str
    side: str
    proposed_quantity: int
    filled_quantity: int
    limit_price: Decimal
    status: str
    reason: str


@dataclass(frozen=True)
class HistoryRecord:
    occurred_at: datetime
    category: str
    reference_id: str
    status: str
    summary: str


@dataclass(frozen=True)
class MarketDetail:
    symbol: str
    observed_at: datetime
    readiness: str
    quote_sources: tuple[str, ...]
    valuation_sources: tuple[str, ...]
    other_sources: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ConfigVersionDetail:
    config_version: str
    status: str
    effective_at: str
    is_runtime: bool
    parameters: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class TacticalStateDetail:
    asset_id: str
    level_id: str
    status: str
    filled_cny: Decimal
    near_high_days: int


@dataclass(frozen=True)
class DashboardViewModel:
    has_account: bool
    total_assets_cny: Decimal
    cash_cny: Decimal
    cash_floor_cny: Decimal
    today_buy_limit_cny: Decimal
    reconciliation_status: str
    data_status: Readiness
    latest_decision_at: datetime | None
    latest_decision_status: str | None
    assets: tuple[AssetDashboard, ...]
    cash_pools: tuple[tuple[str, Decimal], ...]
    open_advices: tuple[AdviceDashboard, ...]


def empty_dashboard() -> DashboardViewModel:
    return DashboardViewModel(
        False, Decimal("0"), Decimal("0"), Decimal("50000"), Decimal("0"),
        "RECONCILIATION_REQUIRED", Readiness.BLOCKED, None, None, (),
        (
            ("基础建仓", Decimal("0")),
            ("标普回撤", Decimal("0")),
            ("纳指回撤", Decimal("0")),
            ("红利回撤", Decimal("0")),
            ("战略现金", Decimal("0")),
        ), (),
    )


class DashboardRepository:
    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)

    def load(self) -> DashboardViewModel:
        if not self.database.exists():
            return empty_dashboard()
        ledger = Ledger(self.database)
        ledger.initialize()
        with closing(ledger.connect()) as connection:
            snapshot = connection.execute(
                """
                SELECT * FROM account_snapshots
                ORDER BY as_of DESC, snapshot_id DESC LIMIT 1
                """
            ).fetchone()
            if snapshot is None:
                return empty_dashboard()
            positions = connection.execute(
                """
                SELECT asset_id, etf_code, broker_market_value_fen
                FROM position_snapshots WHERE snapshot_id = ?
                """,
                (snapshot["snapshot_id"],),
            ).fetchall()
            runtime = connection.execute(
                "SELECT * FROM strategy_runtime WHERE runtime_id = 1"
            ).fetchone()
            config = connection.execute(
                """
                SELECT content_json FROM config_versions
                WHERE config_version = (
                    SELECT config_version FROM strategy_runtime WHERE runtime_id = 1
                )
                """
            ).fetchone()
            market_rows = connection.execute(
                """
                SELECT symbol, readiness, payload_json
                FROM market_snapshots
                WHERE observed_at IN (
                    SELECT MAX(observed_at) FROM market_snapshots GROUP BY symbol
                )
                """
            ).fetchall()
            decision = connection.execute(
                """
                SELECT generated_at, status FROM decision_runs
                ORDER BY generated_at DESC, decision_id DESC LIMIT 1
                """
            ).fetchone()
            level_rows = connection.execute(
                """
                SELECT asset_id, status FROM tactical_level_state
                ORDER BY sort_order
                """
            ).fetchall()
            advice_rows = connection.execute(
                """
                SELECT a.*, COALESCE(SUM(f.quantity), 0) AS filled_quantity
                FROM advice a
                LEFT JOIN advice_fills f ON f.advice_id = a.advice_id
                WHERE a.status IN (
                    'PENDING_CONFIRMATION', 'NOT_ATTEMPTED', 'ORDER_SUBMITTED',
                    'PARTIALLY_FILLED'
                )
                GROUP BY a.advice_id
                ORDER BY a.created_at DESC, a.advice_id DESC
                """
            ).fetchall()

        total = Decimal(snapshot["total_assets_fen"]) / 100
        cash = Decimal(snapshot["available_cash_fen"]) / 100
        raw_config = json.loads(config["content_json"]) if config else {}
        config_assets = {
            item["asset_id"]: item for item in raw_config.get("assets", [])
        }
        market_by_symbol = {row["symbol"]: row for row in market_rows}
        level_by_asset: dict[str, list[str]] = {}
        for row in level_rows:
            level_by_asset.setdefault(row["asset_id"], []).append(row["status"])
        assets = []
        for position in positions:
            asset_id = str(position["asset_id"])
            item_config = config_assets.get(asset_id, {})
            value = Decimal(position["broker_market_value_fen"] or 0) / 100
            market = market_by_symbol.get(str(position["etf_code"]))
            payload = json.loads(market["payload_json"]) if market else {}
            ask = payload.get("selected_ask")
            valuation = payload.get("conservative_valuation")
            premium = (
                Decimal(str(ask)) / Decimal(str(valuation)) - 1
                if ask is not None and valuation not in (None, "0", 0)
                else None
            )
            statuses = level_by_asset.get(asset_id, [])
            visible_state = next(
                (
                    state for state in reversed(statuses)
                    if state not in {"ARMED", "DISABLED"}
                ),
                statuses[0] if statuses else "未初始化",
            )
            assets.append(
                AssetDashboard(
                    asset_id,
                    str(item_config.get("display_name") or asset_id),
                    str(position["etf_code"]),
                    value,
                    value / total if total else Decimal("0"),
                    Decimal(str(item_config.get("target_weight") or 0)),
                    None,
                    premium,
                    visible_state,
                )
            )
        readiness_values = {
            Readiness(row["readiness"]) for row in market_rows
        }
        data_status = (
            Readiness.BLOCKED
            if not market_rows or Readiness.BLOCKED in readiness_values
            else Readiness.REVIEW
            if Readiness.REVIEW in readiness_values
            else Readiness.READY
        )
        pools = (
            ("基础建仓", Decimal(runtime["base_pool_fen"]) / 100),
            ("标普回撤", Decimal(runtime["tactical_sp_fen"]) / 100),
            ("纳指回撤", Decimal(runtime["tactical_nd_fen"]) / 100),
            ("红利回撤", Decimal(runtime["tactical_dv_fen"]) / 100),
            ("战略现金", Decimal(runtime["strategic_fen"]) / 100),
        ) if runtime else empty_dashboard().cash_pools
        cash_floor = Decimal(
            str(raw_config.get("cash", {}).get("strategic_floor_cny", 50000))
        )
        daily_ratio = Decimal(
            str(raw_config.get("execution", {}).get("daily_buy_limit_ratio", "0.04"))
        )
        return DashboardViewModel(
            True, total, cash, cash_floor, total * daily_ratio,
            "RECONCILED", data_status,
            datetime.fromisoformat(decision["generated_at"]) if decision else None,
            str(decision["status"]) if decision else None,
            tuple(assets), pools,
            tuple(
                AdviceDashboard(
                    row["advice_id"],
                    datetime.fromisoformat(row["created_at"]),
                    row["asset_id"],
                    row["etf_code"],
                    row["side"],
                    int(row["proposed_quantity"]),
                    int(row["filled_quantity"]),
                    Decimal(row["limit_price_milli"]) / 1000,
                    row["status"],
                    row["reason"],
                )
                for row in advice_rows
            ),
        )

    def load_history(self, limit: int = 200) -> tuple[HistoryRecord, ...]:
        if not self.database.exists():
            return ()
        ledger = Ledger(self.database)
        ledger.initialize()
        with closing(ledger.connect()) as connection:
            decisions = connection.execute(
                """
                SELECT generated_at, decision_id, status, reasons_json
                FROM decision_runs ORDER BY generated_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            trades = connection.execute(
                """
                SELECT trade_time, trade_id, status, side, etf_code, quantity,
                       price_milli
                FROM trades ORDER BY trade_time DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            flows = connection.execute(
                """
                SELECT flow_time, flow_id, flow_type, amount_fen
                FROM cash_flows ORDER BY flow_time DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        records = [
            HistoryRecord(
                datetime.fromisoformat(row["generated_at"]),
                "决策",
                row["decision_id"],
                row["status"],
                "；".join(json.loads(row["reasons_json"])) or "规则计算完成",
            )
            for row in decisions
        ]
        records.extend(
            HistoryRecord(
                datetime.fromisoformat(row["trade_time"]),
                "成交",
                row["trade_id"],
                row["status"],
                (
                    f"{row['side']} {row['etf_code']} {row['quantity']:,}份 "
                    f"@ {Decimal(row['price_milli']) / 1000:.3f}"
                ),
            )
            for row in trades
        )
        records.extend(
            HistoryRecord(
                datetime.fromisoformat(row["flow_time"]),
                "资金",
                row["flow_id"],
                row["flow_type"],
                f"{Decimal(row['amount_fen']) / 100:+,.2f} 元",
            )
            for row in flows
        )
        records.sort(key=lambda item: item.occurred_at, reverse=True)
        return tuple(records[:limit])

    def load_market_details(self) -> tuple[MarketDetail, ...]:
        if not self.database.exists():
            return ()
        ledger = Ledger(self.database)
        ledger.initialize()
        with closing(ledger.connect()) as connection:
            rows = connection.execute(
                """
                SELECT m.* FROM market_snapshots m
                JOIN (
                    SELECT symbol, MAX(observed_at) AS observed_at
                    FROM market_snapshots GROUP BY symbol
                ) latest
                ON latest.symbol = m.symbol
                AND latest.observed_at = m.observed_at
                ORDER BY m.symbol
                """
            ).fetchall()
        details = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            observations = payload.get("observations", [])
            details.append(
                MarketDetail(
                    row["symbol"],
                    datetime.fromisoformat(row["observed_at"]),
                    row["readiness"],
                    tuple(
                        sorted(
                            {
                                str(item["source"])
                                for item in payload.get("quotes", [])
                            }
                        )
                    ),
                    tuple(
                        sorted(
                            {
                                str(item["source"])
                                for item in observations
                                if item.get("kind") == "VALUATION"
                            }
                        )
                    ),
                    tuple(
                        sorted(
                            {
                                f"{item.get('kind')}:{item.get('source')}"
                                for item in observations
                                if item.get("kind") != "VALUATION"
                            }
                        )
                    ),
                    tuple(json.loads(row["reasons_json"])),
                )
            )
        return tuple(details)

    def load_config_versions(
        self,
    ) -> tuple[tuple[ConfigVersionDetail, ...], tuple[TacticalStateDetail, ...]]:
        if not self.database.exists():
            return (), ()
        ledger = Ledger(self.database)
        ledger.initialize()
        with closing(ledger.connect()) as connection:
            runtime = connection.execute(
                "SELECT config_version FROM strategy_runtime WHERE runtime_id = 1"
            ).fetchone()
            rows = connection.execute(
                """
                SELECT config_version, status, effective_at, content_json
                FROM config_versions ORDER BY effective_at DESC, config_version DESC
                """
            ).fetchall()
            levels = connection.execute(
                """
                SELECT asset_id, level_id, status, filled_fen, near_high_days
                FROM tactical_level_state ORDER BY sort_order
                """
            ).fetchall()
        runtime_version = runtime["config_version"] if runtime else None
        versions = []
        for row in rows:
            raw = json.loads(row["content_json"])
            assets = {
                item["asset_id"]: item for item in raw.get("assets", [])
            }
            parameters = (
                (
                    "目标权重",
                    " / ".join(
                        f"{asset_id} {assets.get(asset_id, {}).get('target_weight', '-')}"
                        for asset_id in ("SP500", "NASDAQ", "DIVIDEND")
                    ),
                ),
                (
                    "现金底线",
                    str(raw.get("cash", {}).get("strategic_floor_cny", "-")),
                ),
                (
                    "单日买入上限",
                    str(raw.get("execution", {}).get("daily_buy_limit_ratio", "-")),
                ),
                (
                    "整手份额",
                    str(raw.get("execution", {}).get("board_lot", "-")),
                ),
                (
                    "价格止损",
                    str(raw.get("sell_policy", {}).get("price_stop_loss", "-")),
                ),
                (
                    "自动下单",
                    str(raw.get("execution", {}).get("automatic_ordering", "-")),
                ),
            )
            versions.append(
                ConfigVersionDetail(
                    row["config_version"], row["status"], row["effective_at"],
                    row["config_version"] == runtime_version, parameters,
                )
            )
        return (
            tuple(versions),
            tuple(
                TacticalStateDetail(
                    row["asset_id"], row["level_id"], row["status"],
                    Decimal(row["filled_fen"]) / 100, row["near_high_days"],
                )
                for row in levels
            ),
        )
