from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

from trade_helper.config import ConfigError, load_strategy_config
from trade_helper.ledger import CURRENT_SCHEMA_VERSION, Ledger


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    message: str


@dataclass(frozen=True)
class DoctorReport:
    ready: bool
    checks: tuple[CheckResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {"ready": self.ready, "checks": [asdict(item) for item in self.checks]}


def run_doctor(
    database: str | Path,
    config: str | Path,
) -> DoctorReport:
    checks: list[CheckResult] = []
    python_ok = sys.version_info >= (3, 11)
    checks.append(
        CheckResult(
            "python",
            "PASS" if python_ok else "FAIL",
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
    )
    try:
        strategy = load_strategy_config(config)
        config_ok = strategy.status == "ACTIVE"
        checks.append(
            CheckResult(
                "config",
                "PASS" if config_ok else "FAIL",
                f"{strategy.config_version} / {strategy.status}",
            )
        )
    except (OSError, ValueError, ConfigError) as error:
        checks.append(CheckResult("config", "FAIL", str(error)))

    database_path = Path(database)
    if not database_path.exists():
        checks.append(CheckResult("database", "FAIL", "本地数据库不存在"))
        return DoctorReport(False, tuple(checks))
    ledger = Ledger(database_path)
    try:
        ledger.initialize()
        with closing(ledger.connect()) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            snapshot_count = connection.execute(
                "SELECT COUNT(*) FROM account_snapshots"
            ).fetchone()[0]
            runtime_count = connection.execute(
                "SELECT COUNT(*) FROM strategy_runtime"
            ).fetchone()[0]
            unresolved = connection.execute(
                """
                SELECT COUNT(*) FROM advice WHERE status IN (
                    'PENDING_CONFIRMATION', 'ORDER_SUBMITTED', 'PARTIALLY_FILLED'
                )
                """
            ).fetchone()[0]
            schema_version = int(
                connection.execute(
                    """
                    SELECT value FROM schema_metadata
                    WHERE key = 'schema_version'
                    """
                ).fetchone()[0]
            )
    except sqlite3.Error as error:
        checks.append(CheckResult("database", "FAIL", str(error)))
        return DoctorReport(False, tuple(checks))
    checks.append(
        CheckResult(
            "schema_version",
            "PASS" if schema_version == CURRENT_SCHEMA_VERSION else "FAIL",
            f"数据库 V{schema_version} / 程序 V{CURRENT_SCHEMA_VERSION}",
        )
    )
    checks.append(
        CheckResult(
            "database", "PASS" if integrity == "ok" else "FAIL",
            f"SQLite integrity_check: {integrity}",
        )
    )
    checks.append(
        CheckResult(
            "account_snapshot", "PASS" if snapshot_count else "WARN",
            f"{snapshot_count} 个账户快照",
        )
    )
    checks.append(
        CheckResult(
            "strategy_runtime", "PASS" if runtime_count == 1 else "FAIL",
            f"{runtime_count} 个当前运行状态",
        )
    )
    checks.append(
        CheckResult(
            "unresolved_advice", "WARN" if unresolved else "PASS",
            f"{unresolved} 条未完成建议",
        )
    )
    return DoctorReport(
        all(item.status != "FAIL" for item in checks),
        tuple(checks),
    )
