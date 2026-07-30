from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from trade_helper.ledger import CURRENT_SCHEMA_VERSION


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupManifest:
    format_version: int
    created_at: str
    database_sha256: str
    database_size: int
    schema_version: int | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_database(path: Path) -> int:
    try:
        connection = sqlite3.connect(path)
        row = connection.execute("PRAGMA integrity_check").fetchone()
        tables = {
            item[0]
            for item in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        schema_row = connection.execute(
            """
            SELECT value FROM schema_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()
    except sqlite3.Error as error:
        raise BackupError(f"database validation failed: {error}") from error
    finally:
        if "connection" in locals():
            connection.close()
    if row is None or row[0] != "ok":
        raise BackupError("database integrity check failed")
    required = {"schema_metadata", "account_snapshots", "trades", "cash_flows"}
    if not required.issubset(tables):
        raise BackupError("backup does not contain a Trade Helper database")
    try:
        schema_version = int(schema_row[0]) if schema_row is not None else 0
    except (TypeError, ValueError) as error:
        raise BackupError("backup schema version is invalid") from error
    if schema_version <= 0:
        raise BackupError("backup schema version is missing")
    if schema_version > CURRENT_SCHEMA_VERSION:
        raise BackupError(
            f"backup schema V{schema_version} is newer than program "
            f"schema V{CURRENT_SCHEMA_VERSION}"
        )
    return schema_version


def create_backup(database: str | Path, destination: str | Path) -> BackupManifest:
    source = Path(database)
    target = Path(destination)
    if not source.exists():
        raise BackupError(f"database does not exist: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        snapshot = Path(directory) / "account.db"
        source_connection = sqlite3.connect(source)
        target_connection = sqlite3.connect(snapshot)
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
            source_connection.close()
        schema_version = _verify_database(snapshot)
        manifest = BackupManifest(
            1,
            datetime.now().astimezone().isoformat(),
            _sha256(snapshot),
            snapshot.stat().st_size,
            schema_version,
        )
        with zipfile.ZipFile(
            target, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.write(snapshot, "account.db")
            archive.writestr(
                "manifest.json",
                json.dumps(manifest.__dict__, ensure_ascii=False, indent=2),
            )
    return manifest


def restore_backup(backup: str | Path, destination: str | Path) -> BackupManifest:
    source = Path(backup)
    target = Path(destination)
    if not source.exists():
        raise BackupError(f"backup does not exist: {source}")
    with tempfile.TemporaryDirectory() as directory:
        extracted = Path(directory)
        try:
            with zipfile.ZipFile(source) as archive:
                names = set(archive.namelist())
                if names != {"account.db", "manifest.json"}:
                    raise BackupError("backup contains unexpected files")
                archive.extractall(extracted)
        except zipfile.BadZipFile as error:
            raise BackupError("backup archive is invalid") from error
        try:
            payload = json.loads(
                (extracted / "manifest.json").read_text(encoding="utf-8")
            )
            manifest = BackupManifest(**payload)
        except (OSError, TypeError, ValueError) as error:
            raise BackupError("backup manifest is invalid") from error
        database = extracted / "account.db"
        if manifest.format_version != 1:
            raise BackupError("unsupported backup format version")
        if database.stat().st_size != manifest.database_size:
            raise BackupError("backup database size does not match manifest")
        if _sha256(database) != manifest.database_sha256:
            raise BackupError("backup checksum verification failed")
        schema_version = _verify_database(database)
        if (
            manifest.schema_version is not None
            and manifest.schema_version != schema_version
        ):
            raise BackupError(
                "backup schema version does not match manifest"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_target = target.with_suffix(target.suffix + ".restoring")
        temporary_target.write_bytes(database.read_bytes())
        temporary_target.replace(target)
        return manifest
