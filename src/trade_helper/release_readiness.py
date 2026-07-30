from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from trade_helper.backup import create_backup, restore_backup
from trade_helper.config import load_strategy_config
from trade_helper.doctor import run_doctor
from trade_helper.replay_suite import run_replay_suite
from trade_helper.shadow_run import build_shadow_report


@dataclass(frozen=True)
class ReleaseGate:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class ReleaseReadinessReport:
    automated_ready: bool
    gates: tuple[ReleaseGate, ...]
    manual_gates: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "automated_ready": self.automated_ready,
            "gates": [asdict(item) for item in self.gates],
            "manual_gates": list(self.manual_gates),
            "release_ready": self.automated_ready
            and not self.manual_gates,
        }


def build_release_readiness(
    database: str | Path,
    config_path: str | Path,
    replay_suite_manifest: str | Path,
    *,
    required_shadow_days: int = 20,
) -> ReleaseReadinessReport:
    gates = []
    doctor = run_doctor(database, config_path)
    gates.append(
        ReleaseGate(
            "doctor",
            doctor.ready,
            "all doctor checks have no FAIL"
            if doctor.ready
            else "doctor contains one or more FAIL checks",
        )
    )

    try:
        shadow = build_shadow_report(
            database, required_trading_days=required_shadow_days
        )
        shadow_passed = shadow.completed
        shadow_message = (
            f"{shadow.observed_trading_days}/"
            f"{shadow.required_trading_days} days; "
            + (
                "acceptance passed"
                if shadow.completed
                else "; ".join(shadow.acceptance_issues)
            )
        )
    except (OSError, ValueError) as error:
        shadow_passed = False
        shadow_message = str(error)
    gates.append(
        ReleaseGate(
            "shadow_run",
            shadow_passed,
            shadow_message,
        )
    )

    try:
        suite = run_replay_suite(
            replay_suite_manifest,
            load_strategy_config(config_path),
        )
        coverage = suite.to_dict()["coverage"]
        replay_passed = bool(coverage["complete"])
        replay_message = (
            f"{len(suite.scenarios)} mandatory scenarios executed"
        )
    except (OSError, ValueError) as error:
        replay_passed = False
        replay_message = str(error)
    gates.append(
        ReleaseGate("historical_replay", replay_passed, replay_message)
    )

    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "account.thbackup"
            restored = root / "restored.db"
            created = create_backup(database, backup)
            recovered = restore_backup(backup, restored)
            restored_doctor = run_doctor(restored, config_path)
            backup_passed = (
                created == recovered and restored_doctor.ready
            )
            backup_message = (
                "verified backup restored and passed doctor"
                if backup_passed
                else "restored backup did not pass doctor"
            )
    except (OSError, ValueError, RuntimeError) as error:
        backup_passed = False
        backup_message = str(error)
    gates.append(
        ReleaseGate("backup_restore", backup_passed, backup_message)
    )

    return ReleaseReadinessReport(
        all(item.passed for item in gates),
        tuple(gates),
        (
            "Clean Windows 10 x64 client acceptance",
            "Clean Windows 11 x64 client acceptance",
            "125% and 150% DPI visual acceptance",
            "Current real account and cash reconciliation confirmed by user",
            "Unsigned-build warning and manual-ordering policy confirmed",
        ),
    )
