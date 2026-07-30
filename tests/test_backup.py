from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import zipfile

from trade_helper.backup import BackupError, create_backup, restore_backup
from trade_helper.ledger import (
    CURRENT_SCHEMA_VERSION,
    AccountSnapshot,
    Ledger,
)


class BackupTests(TestCase):
    def test_backup_and_restore_preserve_database(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.db"
            ledger = Ledger(source)
            ledger.initialize()
            ledger.add_snapshot(
                AccountSnapshot(
                    "S1", datetime(2026, 7, 30, tzinfo=timezone.utc),
                    Decimal("500000"), Decimal("350000"),
                ),
                (),
            )
            archive = root / "account.thbackup"
            manifest = create_backup(source, archive)
            restored = root / "restored.db"
            restored_manifest = restore_backup(archive, restored)

            self.assertEqual(manifest, restored_manifest)
            self.assertEqual(CURRENT_SCHEMA_VERSION, manifest.schema_version)
            self.assertEqual(1, Ledger(restored).count("account_snapshots"))

    def test_tampered_backup_is_rejected_before_destination_changes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.db"
            Ledger(source).initialize()
            archive = root / "account.thbackup"
            create_backup(source, archive)
            with zipfile.ZipFile(archive, "a") as bundle:
                bundle.writestr("unexpected.txt", "tampered")
            destination = root / "destination.db"

            with self.assertRaises(BackupError):
                restore_backup(archive, destination)

            self.assertFalse(destination.exists())

    def test_future_database_schema_cannot_be_backed_up(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.db"
            ledger = Ledger(source)
            ledger.initialize()
            with ledger.transaction() as connection:
                connection.execute(
                    """
                    UPDATE schema_metadata SET value = '999'
                    WHERE key = 'schema_version'
                    """
                )

            with self.assertRaisesRegex(BackupError, "newer than program"):
                create_backup(source, root / "future.thbackup")
