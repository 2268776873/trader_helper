from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

from trade_helper.config import StrategyConfig
from trade_helper.ledger import Ledger
from trade_helper.market_data import (
    MarketDataStore,
    MarketSnapshot,
    Observation,
    ObservationKind,
    aggregate_market_data,
)
from trade_helper.models import Quote, Readiness
from trade_helper.providers.eastmoney import EastmoneyEtfProvider
from trade_helper.providers.sina import SinaEtfProvider
from trade_helper.reference_series import ReferencePoint, ReferenceSeriesStore


class QuoteSource(Protocol):
    name: str

    def fetch(self, symbols: tuple[str, ...]) -> tuple[Quote, ...]: ...


class SinaSource:
    name = "sina"

    def __init__(self) -> None:
        self.provider = SinaEtfProvider()

    def fetch(self, symbols: tuple[str, ...]) -> tuple[Quote, ...]:
        return tuple(self.provider.fetch_many(symbols))


class EastmoneySource:
    name = "eastmoney"

    def __init__(self) -> None:
        self.provider = EastmoneyEtfProvider()

    def fetch(self, symbols: tuple[str, ...]) -> tuple[Quote, ...]:
        return tuple(self.provider.fetch(symbol) for symbol in symbols)


@dataclass(frozen=True)
class CollectionResult:
    snapshots: tuple[MarketSnapshot, ...]
    source_errors: tuple[str, ...]

    @property
    def usable(self) -> bool:
        return bool(self.snapshots) and all(
            snapshot.readiness == Readiness.READY for snapshot in self.snapshots
        )

    @property
    def degraded(self) -> bool:
        return bool(self.source_errors)


def load_manual_supplement(
    path: str | Path,
) -> tuple[datetime, dict[str, dict[str, object]]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"manual supplement is not valid JSON: line {error.lineno}, "
            f"column {error.colno}"
        ) from error
    if not isinstance(payload, dict):
        raise ValueError("manual supplement root must be an object")
    try:
        observed_at = datetime.fromisoformat(str(payload["observed_at"]))
    except KeyError as error:
        raise ValueError("manual supplement observed_at is required") from error
    except ValueError as error:
        raise ValueError("manual supplement observed_at must be ISO-8601") from error
    if observed_at.tzinfo is None:
        raise ValueError("manual supplement observed_at must include timezone")
    assets = payload.get("assets")
    if not isinstance(assets, dict):
        raise ValueError("manual supplement assets must be an object")
    for asset_id, supplement in assets.items():
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise ValueError("manual supplement asset id must be non-empty")
        if not isinstance(supplement, dict):
            raise ValueError(f"{asset_id} supplement must be an object")
        _validate_supplement(asset_id, supplement)
    return observed_at, assets


def _validate_supplement(asset_id: str, supplement: dict[str, object]) -> None:
    valuations = supplement.get("valuations", [])
    if not isinstance(valuations, list):
        raise ValueError(f"{asset_id}.valuations must be a list")
    for index, item in enumerate(valuations):
        _validate_value_source(f"{asset_id}.valuations[{index}]", item)
    for field in ("index", "fx"):
        item = supplement.get(field)
        if item is not None:
            _validate_value_source(f"{asset_id}.{field}", item)
    quote = supplement.get("quote")
    if quote is not None:
        if not isinstance(quote, dict):
            raise ValueError(f"{asset_id}.quote must be an object")
        _source(f"{asset_id}.quote", quote)
        for field in ("last", "bid", "ask"):
            value = quote.get(field)
            if value is not None:
                _positive_decimal(f"{asset_id}.quote.{field}", value)
    reference = supplement.get("reference_value_cny")
    if reference is not None:
        _positive_decimal(f"{asset_id}.reference_value_cny", reference)
    announcement = supplement.get("announcement")
    if announcement is not None:
        if not isinstance(announcement, dict):
            raise ValueError(f"{asset_id}.announcement must be an object")
        _source(f"{asset_id}.announcement", announcement)


def _validate_value_source(path: str, item: object) -> None:
    if not isinstance(item, dict):
        raise ValueError(f"{path} must be an object")
    _source(path, item)
    if "value" not in item:
        raise ValueError(f"{path}.value is required")
    _positive_decimal(f"{path}.value", item["value"])


def _source(path: str, item: dict[str, object]) -> str:
    source = str(item.get("source", "")).strip()
    if not source:
        raise ValueError(f"{path}.source is required")
    return source


def _positive_decimal(path: str, value: object) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{path} must be numeric") from error
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{path} must be a finite positive number")
    return number


class MarketCollectionService:
    def __init__(
        self,
        ledger: Ledger,
        config: StrategyConfig,
        sources: tuple[QuoteSource, ...] | None = None,
    ) -> None:
        self.ledger = ledger
        self.config = config
        self.sources = sources or (SinaSource(), EastmoneySource())

    def collect(
        self,
        *,
        observed_at: datetime,
        supplements: dict[str, dict[str, object]],
    ) -> CollectionResult:
        symbols = tuple(asset.etf_code for asset in self.config.assets)
        quotes: list[Quote] = []
        errors: list[str] = []
        for source in self.sources:
            try:
                quotes.extend(source.fetch(symbols))
            except Exception as error:
                errors.append(f"{source.name}: {error}")
        market_store = MarketDataStore(self.ledger)
        reference_store = ReferenceSeriesStore(self.ledger)
        snapshots = []
        for asset in self.config.assets:
            supplement = supplements.get(asset.asset_id, {})
            observations = self._observations(observed_at, supplement)
            asset_quotes = list(quotes)
            manual_quote = supplement.get("quote")
            if manual_quote is not None:
                asset_quotes.append(
                    Quote(
                        asset.etf_code,
                        asset.display_name,
                        observed_at,
                        float(manual_quote["last"])
                        if manual_quote.get("last") is not None else None,
                        float(manual_quote["bid"])
                        if manual_quote.get("bid") is not None else None,
                        float(manual_quote["ask"])
                        if manual_quote.get("ask") is not None else None,
                        None,
                        str(manual_quote["source"]),
                    )
                )
            snapshot = aggregate_market_data(
                snapshot_id=f"MKT-{asset.etf_code}-{observed_at:%Y%m%dT%H%M%S%z}",
                symbol=asset.etf_code,
                now=observed_at,
                quotes=tuple(asset_quotes),
                observations=observations,
                maximum_premium_difference=Decimal(
                    str(
                        self.config.raw["data_quality"][
                            "maximum_valuation_premium_difference"
                        ]
                    )
                ),
            )
            if errors:
                snapshot = replace(
                    snapshot,
                    reasons=(*snapshot.reasons, *errors),
                )
            market_store.save(snapshot)
            snapshots.append(snapshot)
            reference_value = supplement.get("reference_value_cny")
            if reference_value is not None:
                reference_store.add(
                    ReferencePoint(
                        asset.asset_id,
                        observed_at.date(),
                        Decimal(str(reference_value)),
                        "COMPOSITE",
                        observed_at,
                    )
                )
        return CollectionResult(tuple(snapshots), tuple(errors))

    @staticmethod
    def _observations(
        observed_at: datetime,
        supplement: dict[str, object],
    ) -> tuple[Observation, ...]:
        result: list[Observation] = []
        valuations = supplement.get("valuations", [])
        if not isinstance(valuations, list):
            raise ValueError("valuations must be a list")
        for item in valuations:
            result.append(
                Observation(
                    ObservationKind.VALUATION,
                    str(item["source"]),
                    observed_at,
                    Decimal(str(item["value"])),
                )
            )
        for field, kind in (
            ("index", ObservationKind.INDEX),
            ("fx", ObservationKind.FX),
        ):
            item = supplement.get(field)
            if item is not None:
                result.append(
                    Observation(
                        kind, str(item["source"]), observed_at,
                        Decimal(str(item["value"])),
                    )
                )
        announcement = supplement.get("announcement")
        if announcement is not None:
            result.append(
                Observation(
                    ObservationKind.ANNOUNCEMENT,
                    str(announcement["source"]),
                    observed_at,
                    blocking=bool(announcement.get("blocking", False)),
                    detail=str(announcement.get("detail", "")),
                )
            )
        return tuple(result)
