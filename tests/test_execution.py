from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from trade_helper.execution import (
    Advice,
    AdviceStatus,
    ExecutionLedger,
    Fill,
    OrderAttempt,
)
from trade_helper.ledger import Ledger


class ExecutionLedgerTests(TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        ledger = Ledger(Path(self.directory.name) / "account.db")
        ledger.initialize()
        self.ledger = ledger
        self.execution = ExecutionLedger(ledger)
        self.now = datetime(2026, 7, 30, 6, 0, tzinfo=timezone.utc)
        self.execution.create_advice(
            Advice(
                "ADV-1", self.now, "personal-v1", "DIVIDEND", "515450",
                "BUY", 1000, Decimal("1.500"), "DV_L1",
            )
        )

    def test_advice_and_attempt_do_not_create_a_trade(self) -> None:
        self.execution.record_attempt(
            OrderAttempt(
                "ATT-1", "ADV-1", self.now, AdviceStatus.ORDER_SUBMITTED
            )
        )

        self.assertEqual(AdviceStatus.ORDER_SUBMITTED, self.execution.status("ADV-1"))
        self.assertEqual(0, self.ledger.count("trades"))

    def test_partial_and_full_fills_create_only_actual_trades(self) -> None:
        self.execution.record_attempt(
            OrderAttempt(
                "ATT-1", "ADV-1", self.now, AdviceStatus.ORDER_SUBMITTED
            )
        )
        first = self.execution.record_fill(
            Fill("FILL-1", "ADV-1", self.now, 400, Decimal("1.498"), "ATT-1")
        )
        second = self.execution.record_fill(
            Fill("FILL-2", "ADV-1", self.now, 600, Decimal("1.497"), "ATT-1")
        )

        self.assertEqual(AdviceStatus.PARTIALLY_FILLED, first)
        self.assertEqual(AdviceStatus.FILLED, second)
        self.assertEqual(2, self.ledger.count("trades"))

    def test_fill_cannot_exceed_advice(self) -> None:
        with self.assertRaises(ValueError):
            self.execution.record_fill(
                Fill("FILL-X", "ADV-1", self.now, 1100, Decimal("1.498"))
            )
        self.assertEqual(0, self.ledger.count("trades"))
