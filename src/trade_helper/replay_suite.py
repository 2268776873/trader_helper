from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from trade_helper.config import StrategyConfig
from trade_helper.strategy_replay import (
    StrategyReplayResult,
    load_historical_replay_csv,
    load_replay_initial_account,
    run_strategy_replay,
)


REQUIRED_SCENARIOS = frozenset(
    {"DOT_COM_2000", "GFC_2008", "DRAWDOWN_2022", "LONG_UPTREND"}
)


@dataclass(frozen=True)
class ReplayScenarioResult:
    scenario_id: str
    input_path: str
    input_sha256: str
    source_notes: str
    replay: StrategyReplayResult

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "input_path": self.input_path,
            "input_sha256": self.input_sha256,
            "source_notes": self.source_notes,
            "replay": self.replay.to_dict(),
        }


@dataclass(frozen=True)
class ReplaySuiteResult:
    scenarios: tuple[ReplayScenarioResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "coverage": {
                "required": sorted(REQUIRED_SCENARIOS),
                "executed": [
                    scenario.scenario_id for scenario in self.scenarios
                ],
                "complete": {
                    scenario.scenario_id for scenario in self.scenarios
                }
                == REQUIRED_SCENARIOS,
            },
            "scenarios": [item.to_dict() for item in self.scenarios],
        }


def run_replay_suite(
    manifest_path: str | Path,
    config: StrategyConfig,
) -> ReplaySuiteResult:
    manifest = Path(manifest_path).resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(
        payload.get("scenarios"), list
    ):
        raise ValueError("replay suite manifest must contain a scenarios list")
    entries = payload["scenarios"]
    scenario_ids = [
        str(item.get("scenario_id"))
        for item in entries
        if isinstance(item, dict)
    ]
    if len(entries) != len(scenario_ids):
        raise ValueError("every replay suite scenario must be an object")
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError("replay suite scenario ids must be unique")
    if set(scenario_ids) != REQUIRED_SCENARIOS:
        missing = sorted(REQUIRED_SCENARIOS - set(scenario_ids))
        extra = sorted(set(scenario_ids) - REQUIRED_SCENARIOS)
        raise ValueError(
            f"replay suite coverage mismatch; missing={missing}, extra={extra}"
        )

    results = []
    for entry in entries:
        source_notes = entry.get("source_notes")
        if not isinstance(source_notes, str) or not source_notes.strip():
            raise ValueError(
                f"{entry['scenario_id']} requires non-empty source_notes"
            )
        input_path = _relative_path(manifest, entry.get("input"))
        account_path = _relative_path(
            manifest, entry.get("initial_account")
        )
        raw = input_path.read_bytes()
        replay = run_strategy_replay(
            config,
            load_historical_replay_csv(input_path, config),
            load_replay_initial_account(account_path, config),
        )
        results.append(
            ReplayScenarioResult(
                entry["scenario_id"],
                str(entry["input"]),
                hashlib.sha256(raw).hexdigest(),
                source_notes.strip(),
                replay,
            )
        )
    return ReplaySuiteResult(tuple(results))


def write_replay_suite(
    result: ReplaySuiteResult,
    output_path: str | Path,
) -> None:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _relative_path(manifest: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("scenario input paths must be non-empty strings")
    candidate = Path(raw)
    return (
        candidate.resolve()
        if candidate.is_absolute()
        else (manifest.parent / candidate).resolve()
    )
