from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
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
from trade_helper.models import Quote
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


def load_manual_supplement(
    path: str | Path,
) -> tuple[datetime, dict[str, dict[str, object]]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    observed_at = datetime.fromisoformat(payload["observed_at"])
    if observed_at.tzinfo is None:
        raise ValueError("manual supplement observed_at must include timezone")
    assets = payload.get("assets")
    if not isinstance(assets, dict):
        raise ValueError("manual supplement assets must be an object")
    return observed_at, assets


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
