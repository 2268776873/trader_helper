from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest import TestCase

from openpyxl import Workbook

from trade_helper.ledger import Ledger
from trade_helper.execution import Advice, AdviceStatus, ExecutionLedger
from trade_helper.ui.controller import DesktopController


HEADERS = {
    "账户快照": ["snapshot_id", "as_of", "total_assets", "available_cash", "frozen_cash", "source", "notes"],
    "持仓快照": ["snapshot_id", "as_of", "asset_id", "etf_code", "quantity", "broker_market_value", "source", "notes"],
    "交易流水": ["trade_id", "trade_time", "asset_id", "etf_code", "side", "quantity", "price", "gross_amount", "net_cash_flow", "status", "order_id", "source", "notes"],
    "资金流水": ["flow_id", "flow_time", "flow_type", "amount", "asset_id", "etf_code", "description", "source", "notes"],
}


class DesktopControllerTests(TestCase):
    def workbook(self, root: Path) -> Path:
        book = Workbook()
        book.remove(book.active)
        for name, headers in HEADERS.items():
            sheet = book.create_sheet(name)
            sheet.append(["title"])
            sheet.append([])
            sheet.append(headers)
        book["账户快照"].append(["S1", "2026-07-30 14:00:00", 500000, 350000, 0, "MANUAL", ""])
        book["持仓快照"].append(["S1", "", "SP500", "513500", 24000, 60000, "MANUAL", ""])
        path = root / "account.xlsx"
        book.save(path)
        book.close()
        return path

    def test_preview_commit_and_duplicate_feedback(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            controller = DesktopController(root / "account.db")
            workbook = self.workbook(root)
            preview = controller.preview_excel(workbook)
            result = controller.commit_excel(preview.content_hash)
            repeated = controller.preview_excel(workbook)
            duplicate = controller.commit_excel(repeated.content_hash)

            ledger = Ledger(root / "account.db")
            self.assertTrue(preview.valid)
            self.assertTrue(result.imported)
            self.assertTrue(duplicate.duplicate)
            self.assertEqual(1, ledger.count("account_snapshots"))

    def test_execution_feedback_only_records_actual_fills_as_trades(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "account.db"
            ledger = Ledger(database)
            ledger.initialize()
            now = datetime(2026, 7, 30, tzinfo=timezone.utc)
            ExecutionLedger(ledger).create_advice(
                Advice(
                    "ADV-1", now, "personal-v1", "SP500", "513500",
                    "BUY", 1000, Decimal("2.000"), "test",
                )
            )
            controller = DesktopController(database)

            controller.record_attempt(
                "ADV-1", AdviceStatus.ORDER_SUBMITTED, occurred_at=now
            )
            self.assertEqual(0, ledger.count("trades"))
            status = controller.record_fill(
                "ADV-1", 400, Decimal("1.999"), occurred_at=now
            )

            self.assertEqual(AdviceStatus.PARTIALLY_FILLED, status)
            self.assertEqual(1, ledger.count("trades"))
