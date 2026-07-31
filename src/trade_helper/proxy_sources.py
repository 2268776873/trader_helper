from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


YAHOO_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    "?period1={start}&period2={end}&interval=1d&events=history"
)
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXCHUS"


@dataclass(frozen=True)
class ProxySourceManifest:
    start_date: date
    end_date: date
    output_csv: str
    audit_json: str
    rows: int

    def to_dict(self) -> dict[str, object]:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "output_csv": self.output_csv,
            "audit_json": self.audit_json,
            "rows": self.rows,
        }


def build_proxy_source_csv(
    output_csv: str | Path,
    *,
    start_date: date,
    end_date: date,
    source_dir: str | Path,
    timeout_seconds: int = 30,
) -> ProxySourceManifest:
    if end_date <= start_date:
        raise ValueError("proxy source end_date must be after start_date")
    source_root = Path(source_dir)
    source_root.mkdir(parents=True, exist_ok=True)
    fetch_start = start_date - timedelta(days=7)
    period_start = int(
        datetime.combine(fetch_start, datetime.min.time(), tzinfo=timezone.utc).timestamp()
    )
    period_end = int(
        datetime.combine(end_date, datetime.min.time(), tzinfo=timezone.utc).timestamp()
    )
    source_specs = {
        "SP500_index": (
            "yahoo:^GSPC",
            YAHOO_CHART_URL.format(
                symbol=quote("^GSPC", safe=""),
                start=period_start,
                end=period_end,
            ),
        ),
        "NASDAQ_index": (
            "yahoo:^NDX",
            YAHOO_CHART_URL.format(
                symbol=quote("^NDX", safe=""),
                start=period_start,
                end=period_end,
            ),
        ),
        "DIVIDEND_index": (
            "yahoo:000001.SS",
            YAHOO_CHART_URL.format(
                symbol="000001.SS", start=period_start, end=period_end
            ),
        ),
        "USD_CNY": ("fred:DEXCHUS", FRED_CSV_URL),
    }
    series: dict[str, dict[date, Decimal]] = {}
    source_records = []
    for column, (source_name, url) in source_specs.items():
        raw = _download(url, timeout_seconds)
        safe_name = source_name.replace(":", "_").replace("^", "")
        suffix = ".csv" if source_name.startswith("fred:") else ".json"
        raw_path = source_root / f"{safe_name}{suffix}"
        raw_path.write_bytes(raw)
        if source_name.startswith("fred:"):
            parsed = _parse_fred(raw.decode("utf-8-sig"))
        else:
            parsed = _parse_yahoo(json.loads(raw.decode("utf-8")))
        series[column] = parsed
        source_records.append(
            {
                "column": column,
                "source": source_name,
                "url": url,
                "raw_file": str(raw_path),
                "sha256": _sha256(raw),
                "rows": len(parsed),
            }
        )
    valuation_dates = sorted(set.union(*(set(item) for item in series.values())))
    valuation_dates = [
        item for item in valuation_dates if start_date <= item < end_date
    ]
    rows = []
    for item in valuation_dates:
        values = {}
        for column, observations in series.items():
            available = [observation for observation in observations if observation <= item]
            if not available:
                break
            values[column] = observations[max(available)]
        if len(values) == len(series):
            rows.append((item, values))
    if len(rows) < 2:
        raise ValueError(
            "proxy sources have fewer than two aligned dated observations"
        )
    target = Path(output_csv)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "trading_date",
                "SP500_index",
                "NASDAQ_index",
                "DIVIDEND_index",
                "USD_CNY",
            ]
        )
        for item, values in rows:
            writer.writerow(
                [
                    item.isoformat(),
                    values["SP500_index"],
                    values["NASDAQ_index"],
                    values["DIVIDEND_index"],
                    values["USD_CNY"],
                ]
            )
    audit_path = target.with_suffix(".sources.json")
    audit_path.write_text(
        json.dumps(
            {
                "kind": "PROXY_SOURCE_RAW",
                "start_date": start_date.isoformat(),
                "end_date_exclusive": end_date.isoformat(),
                "dividend_proxy": "000001.SS broad China A-share index; not 515450",
                "alignment": (
                    "valuation-date union with as-of forward fill across market holidays; "
                    "no future observation is used"
                ),
                "sources": source_records,
                "common_rows": len(rows),
                "aligned_rows": len(rows),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return ProxySourceManifest(
        start_date,
        end_date,
        str(target),
        str(audit_path),
        len(rows),
    )


def _download(url: str, timeout_seconds: int) -> bytes:
    request = Request(url, headers={"User-Agent": "TradeHelper/0.1"})
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def _parse_yahoo(payload: dict[str, object]) -> dict[date, Decimal]:
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise ValueError("Yahoo response has no chart object")
    error = chart.get("error")
    if error:
        raise ValueError(f"Yahoo response error: {error}")
    results = chart.get("result")
    if not isinstance(results, list) or not results:
        raise ValueError("Yahoo response has no result")
    result = results[0]
    timestamps = result.get("timestamp") if isinstance(result, dict) else None
    indicators = result.get("indicators") if isinstance(result, dict) else None
    quote_data = indicators.get("quote") if isinstance(indicators, dict) else None
    closes = quote_data[0].get("close") if quote_data else None
    if not isinstance(timestamps, list) or not isinstance(closes, list):
        raise ValueError("Yahoo response has no daily close series")
    parsed = {}
    for timestamp, raw in zip(timestamps, closes):
        if raw is None:
            continue
        parsed[datetime.fromtimestamp(int(timestamp), timezone.utc).date()] = _positive(raw)
    return parsed


def _parse_fred(text: str) -> dict[date, Decimal]:
    parsed = {}
    for row in csv.DictReader(text.splitlines()):
        raw = row.get("DEXCHUS")
        if not raw or raw == ".":
            continue
        parsed[date.fromisoformat(row["observation_date"])] = _positive(raw)
    return parsed


def _positive(raw: object) -> Decimal:
    value = Decimal(str(raw))
    if not value.is_finite() or value <= 0:
        raise ValueError("source value must be finite and positive")
    return value


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
