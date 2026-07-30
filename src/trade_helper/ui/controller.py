from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from trade_helper.execution import (
    AdviceStatus,
    ExecutionLedger,
    Fill,
    OrderAttempt,
)
from trade_helper.excel_import import ImportIssue, commit_preview, preview_workbook
from trade_helper.ledger import Ledger, LedgerConflict


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
