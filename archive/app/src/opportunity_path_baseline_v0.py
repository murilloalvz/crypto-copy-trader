"""SIG-FAST V0 paired random baseline (F3 of the 2026-10-08 work order).

Edge is never the signal's own path metrics in isolation -- it is the signal's
metrics MINUS this baseline's metrics. This module builds the baseline side
only: for each signal at time T, sample K tokens eligible at that same T (same
venue, same age bracket, same minimum recent activity) with a fixed seed, and
run them through the exact same F2 instrument (`opportunity_path_metrics_v0`)
so the two sides are measured identically.

This module does not decide what counts as an "eligible token" from a live
database -- the caller supplies the candidate pool and each candidate's own
trade history. That keeps this module pure and testable with synthetic data,
and keeps it from reading any real outcome itself (F1c/F2's own guardrail).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Mapping, Sequence

from src.opportunity_path_metrics_v0 import (
    WINDOW_GRID_SECONDS,
    CausalEntry,
    CostModel,
    PathTrade,
    WindowMetrics,
    compute_window_metrics,
    find_causal_entry,
)

VERSION = "opportunity_path_baseline_v0"

DEFAULT_K = 5


@dataclass(frozen=True)
class TokenCandidate:
    """One token in the eligibility pool as of the signal's time T.

    `age_seconds_at_signal` and `recent_activity_count` are the caller's own
    measurements as of T (causal by construction if the caller computed them
    that way) -- this module does not recompute them.
    """

    token_mint: str
    venue: str
    age_seconds_at_signal: int
    recent_activity_count: int


@dataclass(frozen=True)
class BaselineSampleResult:
    signal_token_mint: str
    seed: int
    k_requested: int
    pool_size: int
    eligible_size: int
    k_sampled: int
    insufficient_pool: bool
    baseline_token_mints: tuple[str, ...]


def eligible_candidates(
    pool: Sequence[TokenCandidate],
    *,
    signal_token_mint: str,
    signal_venue: str,
    signal_age_seconds: int,
    age_tolerance_seconds: int,
    min_activity_count: int,
) -> list[TokenCandidate]:
    if age_tolerance_seconds < 0:
        raise ValueError("age_tolerance_seconds cannot be negative")
    if min_activity_count < 0:
        raise ValueError("min_activity_count cannot be negative")

    lower = signal_age_seconds - age_tolerance_seconds
    upper = signal_age_seconds + age_tolerance_seconds
    return [
        candidate
        for candidate in pool
        if candidate.token_mint != signal_token_mint
        and candidate.venue == signal_venue
        and lower <= candidate.age_seconds_at_signal <= upper
        and candidate.recent_activity_count >= min_activity_count
    ]


def sample_baseline_tokens(
    pool: Sequence[TokenCandidate],
    *,
    signal_token_mint: str,
    signal_venue: str,
    signal_age_seconds: int,
    age_tolerance_seconds: int,
    min_activity_count: int,
    k: int = DEFAULT_K,
    seed: int,
) -> BaselineSampleResult:
    """Deterministic given the same pool contents and seed, regardless of the
    pool's input order (candidates are sorted by token_mint before sampling)."""

    if k <= 0:
        raise ValueError("k must be positive")

    eligible = eligible_candidates(
        pool,
        signal_token_mint=signal_token_mint,
        signal_venue=signal_venue,
        signal_age_seconds=signal_age_seconds,
        age_tolerance_seconds=age_tolerance_seconds,
        min_activity_count=min_activity_count,
    )
    ordered = sorted(eligible, key=lambda c: c.token_mint)
    rng = random.Random(seed)
    insufficient = len(ordered) < k
    chosen = ordered if insufficient else rng.sample(ordered, k)

    return BaselineSampleResult(
        signal_token_mint=signal_token_mint,
        seed=seed,
        k_requested=k,
        pool_size=len(pool),
        eligible_size=len(ordered),
        k_sampled=len(chosen),
        insufficient_pool=insufficient,
        baseline_token_mints=tuple(c.token_mint for c in chosen),
    )


@dataclass(frozen=True)
class BaselineTokenPathMetrics:
    token_mint: str
    entry: CausalEntry
    window_metrics: Mapping[int, WindowMetrics]


def compute_baseline_token_path_metrics(
    token_mint: str,
    trades: Sequence[PathTrade],
    *,
    signal_time: int,
    entry_latency_seconds: int,
    size_sol: float,
    cost_model: CostModel,
    window_seconds_grid: Sequence[int] = WINDOW_GRID_SECONDS,
) -> BaselineTokenPathMetrics:
    """Runs this one baseline token through the exact same F2 primitives used
    for the signal side, so the two sides are directly comparable."""

    entry = find_causal_entry(
        trades,
        signal_time=signal_time,
        entry_latency_seconds=entry_latency_seconds,
        size_sol=size_sol,
        cost_model=cost_model,
    )
    if entry.trade_chain_time is None or entry.execution_price_sol is None:
        return BaselineTokenPathMetrics(token_mint=token_mint, entry=entry, window_metrics={})

    windows = {
        window_seconds: compute_window_metrics(
            trades,
            entry_chain_time=entry.trade_chain_time,
            entry_execution_price_sol=entry.execution_price_sol,
            window_seconds=window_seconds,
        )
        for window_seconds in window_seconds_grid
    }
    return BaselineTokenPathMetrics(token_mint=token_mint, entry=entry, window_metrics=windows)


@dataclass(frozen=True)
class PairedBaseline:
    sample: BaselineSampleResult
    token_metrics: tuple[BaselineTokenPathMetrics, ...]


def build_paired_baseline(
    pool: Sequence[TokenCandidate],
    trades_by_mint: Mapping[str, Sequence[PathTrade]],
    *,
    signal_token_mint: str,
    signal_venue: str,
    signal_time: int,
    signal_age_seconds: int,
    entry_latency_seconds: int,
    size_sol: float,
    cost_model: CostModel,
    age_tolerance_seconds: int,
    min_activity_count: int,
    k: int = DEFAULT_K,
    seed: int,
    window_seconds_grid: Sequence[int] = WINDOW_GRID_SECONDS,
) -> PairedBaseline:
    sample = sample_baseline_tokens(
        pool,
        signal_token_mint=signal_token_mint,
        signal_venue=signal_venue,
        signal_age_seconds=signal_age_seconds,
        age_tolerance_seconds=age_tolerance_seconds,
        min_activity_count=min_activity_count,
        k=k,
        seed=seed,
    )
    token_metrics = tuple(
        compute_baseline_token_path_metrics(
            mint,
            trades_by_mint.get(mint, ()),
            signal_time=signal_time,
            entry_latency_seconds=entry_latency_seconds,
            size_sol=size_sol,
            cost_model=cost_model,
            window_seconds_grid=window_seconds_grid,
        )
        for mint in sample.baseline_token_mints
    )
    return PairedBaseline(sample=sample, token_metrics=token_metrics)
