from __future__ import annotations

import argparse
import json
from uuid import uuid4
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Sequence

from trade_helper.feasibility import assess_quote, overall_readiness
from trade_helper.excel_import import commit_preview, preview_workbook
from trade_helper.ledger import Ledger, LedgerConflict
from trade_helper.backup import BackupError, create_backup, restore_backup
from trade_helper.shadow_run import build_shadow_report, write_shadow_report
from trade_helper.replay import (
    SensitivityVariant, calculate_replay_metrics, compare_sensitivity,
    load_replay_csv,
    write_replay_report,
)
from trade_helper.doctor import run_doctor
from trade_helper.config import load_strategy_config
from trade_helper.decision_service import DailyDecisionService, DecisionInputError
from trade_helper.trading_calendar import TradingCalendarStore, load_calendar_csv
from trade_helper.market_collection import (
    MarketCollectionService,
    load_manual_supplement,
)
from trade_helper.example_data import create_example_database
from zoneinfo import ZoneInfo
from trade_helper.models import ProbeResult, Readiness
from trade_helper.providers.sina import SinaError, SinaEtfProvider


SYMBOLS = ("513500", "513100", "515450")


def run_probe() -> dict[str, object]:
    now = datetime.now().astimezone()
    provider = SinaEtfProvider()
    results: list[ProbeResult] = []

    try:
        quotes = {quote.symbol: quote for quote in provider.fetch_many(SYMBOLS)}
        for symbol in SYMBOLS:
            quote = quotes[symbol]
            results.append(assess_quote(quote, now))
    except SinaError as error:
        for symbol in SYMBOLS:
            results.append(
                ProbeResult(
                    symbol=symbol,
                    readiness=Readiness.BLOCKED,
                    reasons=(str(error),),
                    quote=None,
                )
            )

    return {
        "generated_at": now.isoformat(),
        "purpose": "DATA_FEASIBILITY_ONLY",
        "overall_readiness": overall_readiness(results).value,
        "results": [result.to_dict() for result in results],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trade-helper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    probe = subparsers.add_parser("probe", help="probe public ETF quote availability")
    probe.add_argument("--output", type=Path)
    excel_preview = subparsers.add_parser(
        "excel-preview", help="validate an account workbook without writing data"
    )
    excel_preview.add_argument("workbook", type=Path)
    excel_import = subparsers.add_parser(
        "excel-import", help="validate and atomically import an account workbook"
    )
    excel_import.add_argument("workbook", type=Path)
    excel_import.add_argument("--database", type=Path, required=True)
    backup = subparsers.add_parser("backup", help="create a verified local backup")
    backup.add_argument("--database", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    restore = subparsers.add_parser("restore", help="verify and restore a local backup")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--database", type=Path, required=True)
    shadow = subparsers.add_parser(
        "shadow-report", help="summarize audited shadow-run coverage"
    )
    shadow.add_argument("--database", type=Path, required=True)
    shadow.add_argument("--output", type=Path)
    shadow.add_argument("--required-days", type=int, default=20)
    replay = subparsers.add_parser(
        "replay-report", help="calculate a fixed set of historical replay metrics"
    )
    replay.add_argument("input", type=Path)
    replay.add_argument("--output", type=Path)
    sensitivity = subparsers.add_parser(
        "sensitivity-report",
        help="compare complete replay metrics across parameter variants",
    )
    sensitivity.add_argument("inputs", type=Path, nargs="+")
    sensitivity.add_argument("--baseline", required=True)
    sensitivity.add_argument("--output", type=Path)
    doctor = subparsers.add_parser(
        "doctor", help="run local release and data readiness checks"
    )
    doctor.add_argument("--database", type=Path, required=True)
    doctor.add_argument(
        "--config", type=Path, default=Path("config/personal_v1.json")
    )
    calendar = subparsers.add_parser(
        "calendar-import", help="import an explicit A-share trading calendar"
    )
    calendar.add_argument("input", type=Path)
    calendar.add_argument("--database", type=Path, required=True)
    calendar.add_argument("--source", default="MANUAL_CSV")
    daily = subparsers.add_parser(
        "daily-decision", help="run and audit the daily decision from persisted data"
    )
    daily.add_argument("--database", type=Path, required=True)
    daily.add_argument(
        "--config", type=Path, default=Path("config/personal_v1.json")
    )
    collect = subparsers.add_parser(
        "market-collect",
        help="collect public quotes plus audited manual valuation supplements",
    )
    collect.add_argument("supplement", type=Path)
    collect.add_argument("--database", type=Path, required=True)
    collect.add_argument(
        "--config", type=Path, default=Path("config/personal_v1.json")
    )
    example = subparsers.add_parser(
        "example-init", help="create a non-overwriting SAMPLE database"
    )
    example.add_argument("--database", type=Path, required=True)
    example.add_argument(
        "--config", type=Path, default=Path("config/personal_v1.json")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "shadow-report":
        report = build_shadow_report(
            args.database, required_trading_days=args.required_days
        )
        if args.output:
            write_shadow_report(report, args.output)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.completed else 5
    if args.command == "replay-report":
        metrics = calculate_replay_metrics(load_replay_csv(args.input))
        if args.output:
            write_replay_report(metrics, args.output)
        print(json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "sensitivity-report":
        variants = tuple(
            SensitivityVariant(
                item.stem,
                calculate_replay_metrics(load_replay_csv(item)),
            )
            for item in args.inputs
        )
        report = compare_sensitivity(variants, baseline=args.baseline)
        rendered = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    if args.command == "doctor":
        report = run_doctor(args.database, args.config)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.ready else 6
    if args.command == "calendar-import":
        ledger = Ledger(args.database)
        ledger.initialize()
        days = load_calendar_csv(args.input, args.source)
        TradingCalendarStore(ledger).replace(days)
        print(json.dumps({"ok": True, "rows": len(days)}, ensure_ascii=False))
        return 0
    if args.command == "daily-decision":
        now = datetime.now().astimezone()
        ledger = Ledger(args.database)
        ledger.initialize()
        calendar = TradingCalendarStore(ledger)
        try:
            day_number = calendar.trading_day_number(now.date())
            if day_number is None:
                print(
                    json.dumps(
                        {"ok": True, "skipped": True, "reason": "A股休市"},
                        ensure_ascii=False,
                    )
                )
                return 0
            decision_service = DailyDecisionService(
                ledger, load_strategy_config(args.config)
            )
            existing = decision_service.successful_decision_on(now.date())
            if existing is not None:
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "skipped": True,
                            "reason": "当日已有成功决策",
                            "decision_id": existing.decision_id,
                            "status": existing.status,
                        },
                        ensure_ascii=False,
                    )
                )
                return 0
            outcome = decision_service.execute(
                decision_id=f"DEC-{now:%Y%m%d-%H%M%S}-{uuid4().hex[:8]}",
                now=now,
                a_share_trading_day_number=day_number,
            )
        except (ValueError, DecisionInputError) as error:
            print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
            return 7
        print(
            json.dumps(
                {
                    "ok": True,
                    "decision_id": outcome.decision_id,
                    "status": outcome.status.value,
                    "reasons": outcome.reasons,
                    "advice_count": len(outcome.advices),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "market-collect":
        observed_at, supplements = load_manual_supplement(args.supplement)
        ledger = Ledger(args.database)
        ledger.initialize()
        result = MarketCollectionService(
            ledger, load_strategy_config(args.config)
        ).collect(observed_at=observed_at, supplements=supplements)
        print(
            json.dumps(
                {
                    "ok": result.usable,
                    "degraded": result.degraded,
                    "source_errors": result.source_errors,
                    "snapshots": [
                        {
                            "symbol": item.symbol,
                            "readiness": item.readiness.value,
                            "reasons": item.reasons,
                        }
                        for item in result.snapshots
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if result.usable else 8
    if args.command == "example-init":
        example_now = datetime(
            2026, 9, 14, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai")
        )
        try:
            outcome = create_example_database(
                args.database,
                load_strategy_config(args.config),
                now=example_now,
            )
        except (FileExistsError, ValueError) as error:
            print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
            return 9
        print(
            json.dumps(
                {
                    "ok": True,
                    "database": str(args.database),
                    "sample": True,
                    "decision_status": outcome.status.value,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command in {"backup", "restore"}:
        try:
            manifest = (
                create_backup(args.database, args.output)
                if args.command == "backup"
                else restore_backup(args.backup, args.database)
            )
        except BackupError as error:
            print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
            return 4
        print(
            json.dumps(
                {"ok": True, "manifest": asdict(manifest)},
                ensure_ascii=False, indent=2,
            )
        )
        return 0

    if args.command in {"excel-preview", "excel-import"}:
        preview = preview_workbook(args.workbook)
        payload: dict[str, object] = {
            "source": preview.source_name,
            "content_hash": preview.content_hash,
            "valid": preview.valid,
            "row_counts": preview.row_counts,
            "issues": [asdict(issue) for issue in preview.issues],
        }
        exit_code = 0 if preview.valid else 2
        if args.command == "excel-import" and preview.valid:
            ledger = Ledger(args.database)
            ledger.initialize()
            try:
                payload["imported"] = commit_preview(ledger, preview)
            except LedgerConflict as error:
                payload["imported"] = False
                payload["issues"] = [
                    {"sheet": "", "row": 0, "field": "", "message": str(error)}
                ]
                exit_code = 3
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return exit_code

    report = run_probe()
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
