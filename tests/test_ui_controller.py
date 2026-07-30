from pathlib import Path
import json
from datetime import datetime, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest import TestCase

from openpyxl import Workbook

from trade_helper.ledger import CashFlow, Ledger
from trade_helper.execution import Advice, AdviceStatus, ExecutionLedger
from trade_helper.models import Quote
from trade_helper.ui.controller import (
    AccountForm, DesktopController, PositionForm,
)


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

    def test_account_form_is_atomic_and_must_reconcile(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "account.db"
            controller = DesktopController(database)
            positions = (
                PositionForm("SP500", "513500", 24000, Decimal("60000")),
                PositionForm("NASDAQ", "513100", 30000, Decimal("60000")),
                PositionForm("DIVIDEND", "515450", 21000, Decimal("30000")),
            )
            with self.assertRaises(ValueError):
                controller.record_account(
                    AccountForm(Decimal("499999"), Decimal("350000"), positions)
                )
            controller.record_account(
                AccountForm(Decimal("500000"), Decimal("350000"), positions)
            )
            ledger = Ledger(database)
            self.assertEqual(1, ledger.count("account_snapshots"))
            self.assertEqual(3, ledger.count("position_snapshots"))

    def test_market_collection_returns_client_friendly_summary(self) -> None:
        class Source:
            def __init__(self, name: str, price: float) -> None:
                self.name = name
                self.price = price

            def fetch(self, symbols: tuple[str, ...]) -> tuple[Quote, ...]:
                now = datetime(
                    2026, 7, 30, 14, 0, tzinfo=timezone.utc
                )
                return tuple(
                    Quote(
                        symbol, symbol, now, self.price, self.price,
                        self.price, None, self.name,
                    )
                    for symbol in symbols
                )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            supplement = root / "market.json"
            assets = {}
            for asset_id in ("SP500", "NASDAQ", "DIVIDEND"):
                assets[asset_id] = {
                    "valuations": [
                        {"source": "v1", "value": 2},
                        {"source": "v2", "value": 2.001},
                    ],
                    "index": {"source": "index", "value": 100},
                    "fx": {"source": "fx", "value": 7.1},
                    "reference_value_cny": 100,
                }
            supplement.write_text(
                json.dumps(
                    {
                        "observed_at": "2026-07-30T22:00:00+08:00",
                        "assets": assets,
                    }
                ),
                encoding="utf-8",
            )
            controller = DesktopController(root / "account.db")

            summary = controller.collect_market(
                supplement,
                Path(__file__).resolve().parents[1]
                / "config" / "personal_v1.json",
                sources=(Source("q1", 2), Source("q2", 2.001)),
            )

            self.assertTrue(summary.usable)
            self.assertFalse(summary.degraded)
            self.assertEqual(3, len(summary.snapshots))

    def test_client_restore_creates_automatic_safety_backup(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active.db"
            source = root / "source.db"
            active_ledger = Ledger(active)
            active_ledger.initialize()
            active_ledger.add_cash_flow(
                CashFlow(
                    "ACTIVE-FLOW", datetime.now(timezone.utc), "DEPOSIT",
                    Decimal("100"),
                )
            )
            source_ledger = Ledger(source)
            source_ledger.initialize()
            source_ledger.add_cash_flow(
                CashFlow(
                    "SOURCE-FLOW", datetime.now(timezone.utc), "DEPOSIT",
                    Decimal("200"),
                )
            )
            source_backup = root / "source.thbackup"
            DesktopController(source).create_database_backup(source_backup)

            result = DesktopController(active).restore_database_backup(
                source_backup
            )

            self.assertIsNotNone(result.safety_backup)
            self.assertTrue(result.safety_backup.is_file())
            self.assertEqual(1, Ledger(active).count("cash_flows"))
