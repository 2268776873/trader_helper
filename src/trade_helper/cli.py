from __future__ import annotations

import argparse
import json
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
    calculate_replay_metrics,
    load_replay_csv,
    write_replay_report,
)
from trade_helper.doctor import run_doctor
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
    doctor = subparsers.add_parser(
        "doctor", help="run local release and data readiness checks"
    )
    doctor.add_argument("--database", type=Path, required=True)
    doctor.add_argument(
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
    if args.command == "doctor":
        report = run_doctor(args.database, args.config)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.ready else 6

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
