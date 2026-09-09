"""Causal fixed-bin market intensity adapter with explicit coverage.

A missing event is NOT equivalent to an observed zero.  This research adapter only
emits a numeric zero for a bin when callers provide explicit coverage proving that the
whole market-time bin was observed and that coverage itself was available by `as_of`.

Coverage is an input assertion from an acquisition system.  This module never infers
coverage from the presence of neighboring trades, a run start/end time, or a sparse
historical corpus.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.market_opportunity_radar import MarketTradeObservation


CAUSAL_INTENSITY_VERSION = "causal_market_intensity_v0"


@dataclass(frozen=True)
class MarketCoverageInterval:
    """Explicit collector coverage over a half-open market-time interval [start, end).

    `available_at` is when the system could causally rely on the coverage assertion.
    `token_mint=None` means the interval is valid for every token in the stated source
    scope; otherwise it applies only to the exact mint.
    """

    start_chain_time: int
    end_chain_time: int
    available_at: int
    source: str
    token_mint: str | None = None
    evidence_key: str | None = None

    def __post_init__(self) -> None:
        if self.start_chain_time < 0 or self.end_chain_time <= self.start_chain_time:
            raise ValueError("coverage interval must have non-negative start and positive width")
        if self.available_at < 0:
            raise ValueError("coverage available_at must be non-negative")
        if not self.source.strip():
            raise ValueError("coverage source cannot be empty")
        if self.token_mint is not None and not self.token_mint.strip():
            raise ValueError("coverage token_mint cannot be blank")
        if self.evidence_key is not None and not self.evidence_key.strip():
            raise ValueError("coverage evidence_key cannot be blank")


@dataclass(frozen=True)
class IntensityBinV0:
    token_mint: str
    bin_start_chain_time: int
    bin_end_chain_time: int
    as_of: int
    status: str  # OBSERVED | MISSING
    event_count: int | None
    buy_count: int | None
    sell_count: int | None
    coverage_sources: tuple[str, ...]
    coverage_evidence_keys: tuple[str, ...]
    event_transaction_keys: tuple[str, ...]
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class CausalIntensitySeriesV0:
    method_version: str
    token_mint: str
    as_of: int
    bin_seconds: int
    bins: tuple[IntensityBinV0, ...]
    observed_bin_count: int
    missing_bin_count: int
    observed_coverage_pct: float


def _fully_covered(
    *,
    start: int,
    end: int,
    token_mint: str,
    as_of: int,
    coverage: tuple[MarketCoverageInterval, ...],
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    """Return whether the complete bin is covered by causally available intervals.

    Multiple overlapping/adjacent intervals may jointly cover one bin.  Intervals for
    another exact mint are ignored.  Global intervals (`token_mint=None`) are allowed.
    """

    eligible = [
        row
        for row in coverage
        if row.available_at <= as_of
        and (row.token_mint is None or row.token_mint == token_mint)
        and row.end_chain_time > start
        and row.start_chain_time < end
    ]
    eligible.sort(key=lambda row: (row.start_chain_time, row.end_chain_time, row.source))

    cursor = start
    used: list[MarketCoverageInterval] = []
    for row in eligible:
        if row.end_chain_time <= cursor:
            continue
        if row.start_chain_time > cursor:
            break
        used.append(row)
        cursor = max(cursor, row.end_chain_time)
        if cursor >= end:
            sources = tuple(sorted({item.source for item in used}))
            evidence = tuple(
                sorted({item.evidence_key for item in used if item.evidence_key is not None})
            )
            return True, sources, evidence
    return False, (), ()


def build_causal_intensity_series_v0(
    *,
    token_mint: str,
    as_of: int,
    start_chain_time: int,
    end_chain_time: int,
    trades: tuple[MarketTradeObservation, ...] | list[MarketTradeObservation] = (),
    coverage: tuple[MarketCoverageInterval, ...] | list[MarketCoverageInterval] = (),
    bin_seconds: int = 1,
) -> CausalIntensitySeriesV0:
    """Build a fixed-bin count series without converting unknown time into zeros."""

    if not token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if as_of < 0:
        raise ValueError("as_of must be non-negative")
    if start_chain_time < 0 or end_chain_time <= start_chain_time:
        raise ValueError("invalid series interval")
    if bin_seconds <= 0:
        raise ValueError("bin_seconds must be positive")
    if (end_chain_time - start_chain_time) % bin_seconds:
        raise ValueError("series interval width must be divisible by bin_seconds")
    if end_chain_time > as_of + 1:
        # Half-open bins may end one second after an inclusive as_of when bin_seconds=1.
        # For wider bins, callers should choose an end boundary whose market contents are
        # already complete at as_of.
        raise ValueError("series cannot extend materially beyond as_of")

    normalized_coverage = tuple(coverage)
    for row in normalized_coverage:
        if not isinstance(row, MarketCoverageInterval):
            raise TypeError("coverage rows must be MarketCoverageInterval")

    eligible_trades: list[MarketTradeObservation] = []
    for trade in trades:
        if trade.token_mint != token_mint:
            continue
        if trade.observed_at > as_of:
            continue
        if not (start_chain_time <= trade.chain_time < end_chain_time):
            continue
        eligible_trades.append(trade)

    bins: list[IntensityBinV0] = []
    observed = 0
    missing = 0
    for bin_start in range(start_chain_time, end_chain_time, bin_seconds):
        bin_end = bin_start + bin_seconds
        covered, sources, evidence = _fully_covered(
            start=bin_start,
            end=bin_end,
            token_mint=token_mint,
            as_of=as_of,
            coverage=normalized_coverage,
        )
        if not covered:
            missing += 1
            bins.append(
                IntensityBinV0(
                    token_mint=token_mint,
                    bin_start_chain_time=bin_start,
                    bin_end_chain_time=bin_end,
                    as_of=as_of,
                    status="MISSING",
                    event_count=None,
                    buy_count=None,
                    sell_count=None,
                    coverage_sources=(),
                    coverage_evidence_keys=(),
                    event_transaction_keys=(),
                    data_quality_flags=("collector_coverage_unknown",),
                )
            )
            continue

        rows = [
            trade
            for trade in eligible_trades
            if bin_start <= trade.chain_time < bin_end
        ]
        observed += 1
        tx_keys = tuple(
            sorted({trade.transaction_key for trade in rows if trade.transaction_key is not None})
        )
        flags: list[str] = []
        if rows and len(tx_keys) < len(rows):
            flags.append("partial_transaction_identity_coverage")
        bins.append(
            IntensityBinV0(
                token_mint=token_mint,
                bin_start_chain_time=bin_start,
                bin_end_chain_time=bin_end,
                as_of=as_of,
                status="OBSERVED",
                event_count=len(rows),
                buy_count=sum(trade.side == "buy" for trade in rows),
                sell_count=sum(trade.side == "sell" for trade in rows),
                coverage_sources=sources,
                coverage_evidence_keys=evidence,
                event_transaction_keys=tx_keys,
                data_quality_flags=tuple(flags),
            )
        )

    total = len(bins)
    return CausalIntensitySeriesV0(
        method_version=CAUSAL_INTENSITY_VERSION,
        token_mint=token_mint,
        as_of=as_of,
        bin_seconds=bin_seconds,
        bins=tuple(bins),
        observed_bin_count=observed,
        missing_bin_count=missing,
        observed_coverage_pct=(100.0 * observed / total if total else 0.0),
    )
