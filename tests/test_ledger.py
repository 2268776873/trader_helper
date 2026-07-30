from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.ledger import (
    AccountSnapshot,
    CashFlow,
    Ledger,
    LedgerConflict,
    PositionSnapshot,
    Trade,
    cny_to_fen,
    price_to_milli,
)


class LedgerTests(TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = Ledger(Path(self.directory.name) / "account.db")
        self.ledger.initialize()
        self.now = datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)

    def test_money_uses_integer_storage_units(self) -> None:
        self.assertEqual(12346, cny_to_fen("123.456"))
        self.assertEqual(2040, price_to_milli("2.040"))

    def test_adds_atomic_snapshot_with_three_positions(self) -> None:
        snapshot = AccountSnapshot(
            snapshot_id="SNAP-1",
            as_of=self.now,
            total_assets_cny=Decimal("500000"),
            available_cash_cny=Decimal("350000"),
        )
        positions = (
            PositionSnapshot("SNAP-1", "SP500", "513500", 24000, Decimal("60000")),
            PositionSnapshot("SNAP-1", "NASDAQ", "513100", 30000, Decimal("60000")),
            PositionSnapshot("SNAP-1", "DIVIDEND", "515450", 21000, Decimal("30000")),
        )

        self.ledger.add_snapshot(snapshot, positions)

        self.assertEqual(1, self.ledger.count("account_snapshots"))
        self.assertEqual(3, self.ledger.count("position_snapshots"))

    def test_duplicate_snapshot_does_not_add_more_positions(self) -> None:
        snapshot = AccountSnapshot(
            "SNAP-1",
            self.now,
            Decimal("500000"),
            Decimal("350000"),
        )
        positions = (
            PositionSnapshot("SNAP-1", "SP500", "513500", 24000),
        )
        self.ledger.add_snapshot(snapshot, positions)

        with self.assertRaises(LedgerConflict):
            self.ledger.add_snapshot(snapshot, positions)

        self.assertEqual(1, self.ledger.count("account_snapshots"))
        self.assertEqual(1, self.ledger.count("position_snapshots"))

    def test_records_trade_without_commission_fields(self) -> None:
        self.ledger.add_trade(
            Trade(
                trade_id="TRD-1",
                trade_time=self.now,
                asset_id="DIVIDEND",
                etf_code="515450",
                side="BUY",
                quantity=6800,
                price=Decimal("1.458"),
            )
        )

        self.assertEqual(1, self.ledger.count("trades"))

    def test_records_actual_cash_flow(self) -> None:
        self.ledger.add_cash_flow(
            CashFlow(
                flow_id="FLOW-1",
                flow_time=self.now,
                flow_type="DEPOSIT",
                amount_cny=Decimal("16000"),
            )
        )

        self.assertEqual(1, self.ledger.count("cash_flows"))
