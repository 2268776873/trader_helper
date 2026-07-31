from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class ProxyReplayConversion:
    input_path: str
    output_path: str
    audit_path: str
    rows: int
    proxy_kind: str = "PROXY"


REQUIRED_COLUMNS = (
    "trading_date",
    "SP500_index",
    "NASDAQ_index",
    "DIVIDEND_index",
    "USD_CNY",
)


def convert_proxy_csv(
    input_path: str | Path,
    output_path: str | Path,
    *,
    audit_path: str | Path | None = None,
    source_notes: str,
) -> ProxyReplayConversion:
    if not source_notes.strip():
        raise ValueError("proxy conversion requires source_notes")
    source = Path(input_path)
    target = Path(output_path)
    audit = Path(audit_path) if audit_path is not None else target.with_suffix(
        ".audit.json"
    )
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream)
        missing = sorted(set(REQUIRED_COLUMNS) - set(rows.fieldnames or ()))
        if missing:
            raise ValueError(f"proxy CSV is missing columns: {missing}")
        parsed = []
        for row_number, row in enumerate(rows, start=2):
            try:
                trading_date = date.fromisoformat(row["trading_date"])
                parsed.append(
                    (
                        trading_date,
                        _positive(row["SP500_index"], row_number),
                        _positive(row["NASDAQ_index"], row_number),
                        _positive(row["DIVIDEND_index"], row_number),
                        _positive(row["USD_CNY"], row_number),
                    )
                )
            except (KeyError, ValueError) as error:
                raise ValueError(
                    f"invalid proxy row {row_number}: {error}"
                ) from error
    if len(parsed) < 2:
        raise ValueError("proxy replay requires at least two rows")
    dates = [item[0] for item in parsed]
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise ValueError("proxy dates must be unique and increasing")
    bases = {
        "SP500": parsed[0][1] * parsed[0][4],
        "NASDAQ": parsed[0][2] * parsed[0][4],
        "DIVIDEND": parsed[0][3],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        header = ["trading_date"]
        for asset_id in ("SP500", "NASDAQ", "DIVIDEND"):
            header.extend(
                [
                    f"{asset_id}_price",
                    f"{asset_id}_nav_1",
                    f"{asset_id}_nav_2",
                    f"{asset_id}_reference",
                ]
            )
        writer.writerow(header)
        for trading_date, sp, nd, dv, fx in parsed:
            values = {
                "SP500": sp * fx / bases["SP500"],
                "NASDAQ": nd * fx / bases["NASDAQ"],
                "DIVIDEND": dv / bases["DIVIDEND"],
            }
            rendered = [trading_date.isoformat()]
            for asset_id in ("SP500", "NASDAQ", "DIVIDEND"):
                value = values[asset_id]
                rendered.extend([value, value, value, value])
            writer.writerow(rendered)
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(
        json.dumps(
            {
                "kind": "PROXY",
                "source_notes": source_notes.strip(),
                "input_columns": list(REQUIRED_COLUMNS),
                "transformation": {
                    "SP500": "SP500_index * USD_CNY, normalized to first row",
                    "NASDAQ": "NASDAQ_index * USD_CNY, normalized to first row",
                    "DIVIDEND": "DIVIDEND_index, normalized to first row",
                    "price_and_nav": "equal normalized proxy value; no ETF premium inferred",
                },
                "rows": len(parsed),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return ProxyReplayConversion(
        str(source), str(target), str(audit), len(parsed)
    )


def _positive(raw: object, row_number: int) -> Decimal:
    try:
        value = Decimal(str(raw))
    except Exception as error:
        raise ValueError(f"row {row_number} contains a non-numeric value") from error
    if not value.is_finite() or value <= 0:
        raise ValueError(f"row {row_number} contains a non-positive value")
    return value
