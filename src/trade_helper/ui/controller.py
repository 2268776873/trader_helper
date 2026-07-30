from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from trade_helper.backup import BackupManifest, create_backup, restore_backup
from trade_helper.execution import (
    AdviceStatus,
    ExecutionLedger,
    Fill,
    OrderAttempt,
)
from trade_helper.excel_import import ImportIssue, commit_preview, preview_workbook
from trade_helper.ledger import Ledger, LedgerConflict
from trade_helper.ledger import AccountSnapshot, PositionSnapshot
from trade_helper.config import load_strategy_config
from trade_helper.market_collection import (
    CollectionResult,
    MarketCollectionService,
    QuoteSource,
    load_manual_supplement,
)


@dataclass(frozen=True)
class ImportSummary:
    source_name: str
    valid: bool
    row_counts: dict[str, int]
    issues: tuple[ImportIssue, ...]
    content_hash: str


@dataclass(frozen=True)
class ImportResult:
    imported: bool
    duplicate: bool
    message: str


@dataclass(frozen=True)
class PositionForm:
    asset_id: str
    etf_code: str
    quantity: int
    market_value_cny: Decimal


@dataclass(frozen=True)
class AccountForm:
    total_assets_cny: Decimal
    available_cash_cny: Decimal
    positions: tuple[PositionForm, ...]
    notes: str = ""


@dataclass(frozen=True)
class MarketCollectionSummary:
    usable: bool
    degraded: bool
    source_errors: tuple[str, ...]
    snapshots: tuple[tuple[str, str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class RestoreSummary:
    manifest: BackupManifest
    safety_backup: Path | None


class DesktopController:
    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self._previews: dict[str, object] = {}

    def preview_excel(self, workbook: str | Path) -> ImportSummary:
        preview = preview_workbook(workbook)
        self._previews[preview.content_hash] = preview
        return ImportSummary(
            preview.source_name, preview.valid, preview.row_counts,
            preview.issues, preview.content_hash,
        )

    def commit_excel(self, content_hash: str) -> ImportResult:
        preview = self._previews.pop(content_hash, None)
        if preview is None:
            raise ValueError("导入预览已失效，请重新选择文件")
        if not preview.valid:
            raise ValueError("存在校验错误，不能写入")
        ledger = Ledger(self.database)
        ledger.initialize()
        try:
            imported = commit_preview(ledger, preview)
        except LedgerConflict as error:
            return ImportResult(False, False, str(error))
        return (
            ImportResult(True, False, "账户数据已原子写入")
            if imported
            else ImportResult(False, True, "相同内容已经导入，本次未重复写入")
        )

    def record_attempt(
        self,
        advice_id: str,
        status: AdviceStatus,
        *,
        broker_order_id: str | None = None,
        notes: str = "",
        occurred_at: datetime | None = None,
    ) -> AdviceStatus:
        ledger = Ledger(self.database)
        ledger.initialize()
        ExecutionLedger(ledger).record_attempt(
            OrderAttempt(
                f"ATT-{uuid4().hex}",
                advice_id,
                occurred_at or datetime.now().astimezone(),
                status,
                broker_order_id,
                notes,
            )
        )
        return status

    def record_fill(
        self,
        advice_id: str,
        quantity: int,
        price: Decimal,
        *,
        attempt_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> AdviceStatus:
        ledger = Ledger(self.database)
        ledger.initialize()
        return ExecutionLedger(ledger).record_fill(
            Fill(
                f"FILL-{uuid4().hex}",
                advice_id,
                occurred_at or datetime.now().astimezone(),
                quantity,
                price,
                attempt_id,
            )
        )

    def record_account(
        self,
        form: AccountForm,
        *,
        occurred_at: datetime | None = None,
    ) -> str:
        when = occurred_at or datetime.now().astimezone()
        if when.tzinfo is None:
            raise ValueError("账户快照时间必须包含时区")
        if form.total_assets_cny < 0 or form.available_cash_cny < 0:
            raise ValueError("总资产和现金不能为负数")
        if len(form.positions) != 3:
            raise ValueError("必须填写三只配置 ETF")
        if len({item.asset_id for item in form.positions}) != len(form.positions):
            raise ValueError("资产 ID 不能重复")
        if any(
            item.quantity < 0 or item.market_value_cny < 0
            for item in form.positions
        ):
            raise ValueError("持仓份额和市值不能为负数")
        reconstructed = form.available_cash_cny + sum(
            (item.market_value_cny for item in form.positions),
            start=Decimal("0"),
        )
        if reconstructed != form.total_assets_cny:
            raise ValueError(
                f"账户不平衡：现金加持仓市值为 {reconstructed}，"
                f"但总资产为 {form.total_assets_cny}"
            )
        snapshot_id = f"SNAP-APP-{when:%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
        ledger = Ledger(self.database)
        ledger.initialize()
        ledger.add_snapshot(
            AccountSnapshot(
                snapshot_id, when, form.total_assets_cny,
                form.available_cash_cny, Decimal("0"), "APP_FORM", form.notes,
            ),
            tuple(
                PositionSnapshot(
                    snapshot_id, item.asset_id, item.etf_code, item.quantity,
                    item.market_value_cny, "APP_FORM",
                )
                for item in form.positions
            ),
        )
        return snapshot_id

    def collect_market(
        self,
        supplement: str | Path,
        config: str | Path,
        *,
        sources: tuple[QuoteSource, ...] | None = None,
    ) -> MarketCollectionSummary:
        observed_at, supplements = load_manual_supplement(supplement)
        ledger = Ledger(self.database)
        ledger.initialize()
        result: CollectionResult = MarketCollectionService(
            ledger,
            load_strategy_config(config),
            sources,
        ).collect(observed_at=observed_at, supplements=supplements)
        return MarketCollectionSummary(
            result.usable,
            result.degraded,
            result.source_errors,
            tuple(
                (
                    snapshot.symbol,
                    snapshot.readiness.value,
                    snapshot.reasons,
                )
                for snapshot in result.snapshots
            ),
        )

    def create_database_backup(self, destination: str | Path) -> BackupManifest:
        return create_backup(self.database, destination)

    def restore_database_backup(self, source: str | Path) -> RestoreSummary:
        safety_backup = None
        if self.database.exists():
            stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
            safety_backup = self.database.with_name(
                f"{self.database.stem}.pre-restore-{stamp}.thbackup"
            )
            create_backup(self.database, safety_backup)
        manifest = restore_backup(source, self.database)
        return RestoreSummary(manifest, safety_backup)
