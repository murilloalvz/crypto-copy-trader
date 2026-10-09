"""Read-only diagnostic: long-horizon (3600s) route-research baseline rate.

Not a hypothesis test. Does not open a PRE-REGISTRADA line and does not spend
an attempt under docs/research-hypothesis-registry-v1-2026-10-04.md rule 5
(systems/diagnostic work is not an economic verdict). No network calls, no
collection -- reads only outcomes already persisted by a past acquisition.

Point of the diagnostic (per operator review of
docs/strategy-options-move-first-2026-10-07.md, 2026-10-07): the existing
evaluator (`src/route_research_evaluation.py`) excludes UNAVAILABLE/
PROVIDER_ERROR outcomes from its return sample ("missing data"). At long
horizons that silently drops exactly the episodes where the token became too
illiquid to even get an exit quote -- economically a realized total loss for
a route-only paper BUY, not a missing observation. This script reports BOTH
views side by side so the gap is visible instead of hidden.

Population: episodes whose exit quote at ALIVE_AT_HORIZON_SECONDS (+5min) was
AVAILABLE ("alive at +5min"). No slicing by any feature/marker -- diagnostic
only, pooled population exactly as requested.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from src.database import rows
from src.opportunity_route_research_store import (
    RouteResearchForwardOutcome,
    ensure_route_research_schema,
    load_route_research_outcomes,
)
from src.route_research_evaluation import _return_for_available
from src.route_research_feature_robustness_v47 import (
    RobustReturnMetricsV47,
    robust_return_metrics_v47,
)

VERSION = "move_first_long_horizon_baseline_v0"

# "vivo em +5min": the route-only exit quote was still resolvable 300s out.
ALIVE_AT_HORIZON_SECONDS = 300
TARGET_HORIZON_SECONDS = 3600
MISSING_ROUTE_RETURN_PCT = -100.0
_RESOLVED_STATUSES = {"UNAVAILABLE", "PROVIDER_ERROR"}


@dataclass(frozen=True)
class LongHorizonBaselineV0:
    run_key: str
    alive_at_5min: int
    scheduled_3600s_among_alive: int
    available_3600s: int
    missing_route_3600s: int
    pending_3600s: int
    returns_excluding_missing_route: tuple[float, ...]
    returns_including_missing_route: tuple[float, ...]
    excluding_missing_route: RobustReturnMetricsV47
    including_missing_route_as_minus100: RobustReturnMetricsV47


def _compute_from_outcomes(
    run_key: str,
    outcomes: tuple[RouteResearchForwardOutcome, ...],
    *,
    resolve_return=_return_for_available,
) -> LongHorizonBaselineV0:
    alive_episode_keys = {
        item.episode_key
        for item in outcomes
        if item.horizon_seconds == ALIVE_AT_HORIZON_SECONDS and item.status == "AVAILABLE"
    }
    target_rows = [
        item
        for item in outcomes
        if item.horizon_seconds == TARGET_HORIZON_SECONDS and item.episode_key in alive_episode_keys
    ]

    excluding: list[float] = []
    including: list[float] = []
    available = missing_route = pending = 0
    for item in target_rows:
        if item.status == "AVAILABLE":
            value = resolve_return(item)
            excluding.append(value)
            including.append(value)
            available += 1
        elif item.status in _RESOLVED_STATUSES:
            missing_route += 1
            including.append(MISSING_ROUTE_RETURN_PCT)
        elif item.status == "PENDING":
            pending += 1
        else:
            raise ValueError(f"unknown route research outcome status {item.status!r}")

    return LongHorizonBaselineV0(
        run_key=run_key,
        alive_at_5min=len(alive_episode_keys),
        scheduled_3600s_among_alive=len(target_rows),
        available_3600s=available,
        missing_route_3600s=missing_route,
        pending_3600s=pending,
        returns_excluding_missing_route=tuple(excluding),
        returns_including_missing_route=tuple(including),
        excluding_missing_route=robust_return_metrics_v47(excluding),
        including_missing_route_as_minus100=robust_return_metrics_v47(including),
    )


def compute_baseline_v0(run_key: str) -> LongHorizonBaselineV0:
    return _compute_from_outcomes(run_key, load_route_research_outcomes(acquisition_run_key=run_key))


def distinct_run_keys() -> list[str]:
    ensure_route_research_schema()
    return [
        str(row["acquisition_run_key"])
        for row in rows(
            "SELECT DISTINCT acquisition_run_key FROM opportunity_route_research_outcomes "
            "ORDER BY acquisition_run_key"
        )
    ]


def _print_metrics(label: str, metrics: RobustReturnMetricsV47) -> None:
    if metrics.n == 0:
        print(f"    {label}: n=0 (sem dado resolvido)")
        return
    mean_sem_maior = (
        "n/a" if metrics.mean_without_best_pct is None else f"{metrics.mean_without_best_pct:.2f}%"
    )
    print(
        f"    {label}: n={metrics.n} positive_share={metrics.positive_share_pct:.1f}% "
        f"mean={metrics.mean_return_pct:.2f}% median={metrics.median_return_pct:.2f}% "
        f"mean_sem_maior_vencedor={mean_sem_maior} profit_factor={metrics.profit_factor}"
    )


def _print_baseline(result: LongHorizonBaselineV0) -> None:
    print(f"\nrun_key={result.run_key}")
    print(f"  vivos em +5min (300s AVAILABLE): {result.alive_at_5min}")
    print(f"  agendados em 3600s entre vivos: {result.scheduled_3600s_among_alive}")
    print(
        f"  3600s -> AVAILABLE={result.available_3600s} "
        f"rota_faltante(UNAVAILABLE/PROVIDER_ERROR)={result.missing_route_3600s} "
        f"ainda_pendente={result.pending_3600s}"
    )
    _print_metrics("excluindo rota faltante (visão do evaluator atual)", result.excluding_missing_route)
    _print_metrics("rota faltante = -100% (visão desta diagnóstico)", result.including_missing_route_as_minus100)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-key", action="append", dest="run_keys", default=[])
    parser.add_argument("--all", action="store_true", help="usa todas as acquisition_run_key já no DB local")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        print("self-check OK")
        return

    run_keys = list(args.run_keys)
    if args.all:
        run_keys = distinct_run_keys()
    if not run_keys:
        parser.error("informe --run-key (repetível) ou --all")

    results = [compute_baseline_v0(key) for key in run_keys]
    for result in results:
        _print_baseline(result)

    pooled_excluding = [value for result in results for value in result.returns_excluding_missing_route]
    pooled_including = [value for result in results for value in result.returns_including_missing_route]
    print("\n=== POOLED (todas as run_keys acima, sem fatiar por marcador) ===")
    print(f"  vivos em +5min somados: {sum(r.alive_at_5min for r in results)}")
    print(
        f"  3600s -> AVAILABLE={sum(r.available_3600s for r in results)} "
        f"rota_faltante={sum(r.missing_route_3600s for r in results)} "
        f"ainda_pendente={sum(r.pending_3600s for r in results)}"
    )
    _print_metrics("excluindo rota faltante", robust_return_metrics_v47(pooled_excluding))
    _print_metrics("rota faltante = -100%", robust_return_metrics_v47(pooled_including))


def _self_check() -> None:
    def fake_outcome(episode_key: str, horizon: int, status: str) -> RouteResearchForwardOutcome:
        return RouteResearchForwardOutcome(
            outcome_key=f"fake:{episode_key}:{horizon}",
            acquisition_run_key="self-check",
            episode_key=episode_key,
            token_mint="MINT",
            research_decision_as_of=0,
            horizon_seconds=horizon,
            target_at=horizon,
            status=status,
            observed_at=None,
            quote_key=None,
            error_type=None,
            error_message=None,
        )

    outcomes = (
        fake_outcome("E1", 300, "AVAILABLE"),
        fake_outcome("E1", 3600, "AVAILABLE"),
        fake_outcome("E2", 300, "AVAILABLE"),
        fake_outcome("E2", 3600, "UNAVAILABLE"),
        fake_outcome("E3", 300, "AVAILABLE"),
        fake_outcome("E3", 3600, "PROVIDER_ERROR"),
        fake_outcome("E4", 300, "AVAILABLE"),
        fake_outcome("E4", 3600, "PENDING"),
        fake_outcome("E5", 300, "PROVIDER_ERROR"),  # morto antes de +5min: fora da população
        fake_outcome("E5", 3600, "AVAILABLE"),
    )

    result = _compute_from_outcomes(
        "self-check",
        outcomes,
        resolve_return=lambda item: 50.0,
    )

    assert result.alive_at_5min == 4, result.alive_at_5min
    assert result.scheduled_3600s_among_alive == 4, result.scheduled_3600s_among_alive
    assert result.available_3600s == 1, result.available_3600s
    assert result.missing_route_3600s == 2, result.missing_route_3600s
    assert result.pending_3600s == 1, result.pending_3600s
    assert result.excluding_missing_route.n == 1
    assert result.excluding_missing_route.mean_return_pct == 50.0
    assert result.including_missing_route_as_minus100.n == 3
    assert result.including_missing_route_as_minus100.mean_return_pct == -50.0
    assert result.including_missing_route_as_minus100.median_return_pct == -100.0


if __name__ == "__main__":
    main()
