from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median

from src.causal_quote_store import load_causal_quotes
from src.opportunity_route_research_store import (
    RouteResearchForwardOutcome,
    load_route_research_decision,
    load_route_research_outcomes,
)


@dataclass(frozen=True)
class RouteResearchHorizonMetrics:
    horizon_seconds: int
    scheduled: int
    available: int
    pending: int
    unavailable_or_error: int
    coverage_pct: float
    positive_share_pct: float | None
    mean_return_pct: float | None
    median_return_pct: float | None
    profit_factor: float | None
    best_return_pct: float | None
    worst_return_pct: float | None
    mean_without_best_pct: float | None
    largest_winner_share_of_gross_profit_pct: float | None
    classification: str


@dataclass(frozen=True)
class RouteResearchEvaluation:
    acquisition_run_key: str
    horizons: tuple[RouteResearchHorizonMetrics, ...]
    lineage_violations: int


def _quote(key: str):
    rows = load_causal_quotes(quote_keys=(key,))
    return rows[0] if len(rows) == 1 else None


def _return_for_available(outcome: RouteResearchForwardOutcome) -> float:
    if outcome.status != "AVAILABLE" or not outcome.quote_key:
        raise ValueError("return requires AVAILABLE route research outcome")
    decision = load_route_research_decision(
        acquisition_run_key=outcome.acquisition_run_key,
        episode_key=outcome.episode_key,
    )
    if decision is None:
        raise ValueError("route research decision missing")
    if decision.research_decision_as_of != outcome.research_decision_as_of:
        raise ValueError("route research decision/outcome clock mismatch")
    entry = _quote(decision.entry_quote_key)
    exit_quote = _quote(outcome.quote_key)
    if entry is None or exit_quote is None:
        raise ValueError("route research quote artifact missing")
    if (
        entry.token_mint != outcome.token_mint
        or exit_quote.token_mint != outcome.token_mint
        or entry.side != "buy"
        or exit_quote.side != "sell"
        or entry.executable
        or exit_quote.executable
        or entry.observed_at > outcome.research_decision_as_of
        or outcome.observed_at is None
        or exit_quote.observed_at != outcome.observed_at
        or exit_quote.observed_at < outcome.target_at
    ):
        raise ValueError("route research quote lineage violation")
    if entry.price_usd <= 0 or exit_quote.price_usd <= 0:
        raise ValueError("route research quote price must be positive")
    value = 100.0 * (exit_quote.price_usd / entry.price_usd - 1.0)
    if not math.isfinite(value):
        raise ValueError("route research return is non-finite")
    return value


def _metrics(horizon: int, rows: list[RouteResearchForwardOutcome]) -> tuple[RouteResearchHorizonMetrics, int]:
    available_rows = [item for item in rows if item.status == "AVAILABLE"]
    returns: list[float] = []
    violations = 0
    for item in available_rows:
        try:
            returns.append(_return_for_available(item))
        except ValueError:
            violations += 1

    scheduled = len(rows)
    available = len(returns)
    pending = sum(1 for item in rows if item.status == "PENDING")
    error_count = scheduled - len(available_rows) - pending
    coverage = 100.0 * available / scheduled if scheduled else 0.0

    positive_share = None
    mean_value = None
    median_value = None
    profit_factor = None
    best = None
    worst = None
    mean_without_best = None
    largest_winner_share = None
    if returns:
        positive_share = 100.0 * sum(1 for value in returns if value > 0) / len(returns)
        mean_value = sum(returns) / len(returns)
        median_value = median(returns)
        best = max(returns)
        worst = min(returns)
        positives = [value for value in returns if value > 0]
        negatives = [value for value in returns if value < 0]
        gross_profit = sum(positives)
        gross_loss = -sum(negatives)
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = math.inf
        if len(returns) > 1:
            trimmed = list(returns)
            trimmed.remove(best)
            mean_without_best = sum(trimmed) / len(trimmed)
        if positives and gross_profit > 0:
            largest_winner_share = 100.0 * max(positives) / gross_profit

    if scheduled == 0:
        classification = "INCONCLUSIVE_NO_SCHEDULE"
    elif violations:
        classification = "FAIL_LINEAGE_VIOLATION"
    elif pending:
        classification = "INCONCLUSIVE_PENDING"
    elif available < 30:
        classification = "INCONCLUSIVE_SAMPLE_LT_30"
    else:
        classification = "DESCRIPTIVE_SAMPLE_READY_FOR_ANALYSIS"

    return (
        RouteResearchHorizonMetrics(
            horizon_seconds=horizon,
            scheduled=scheduled,
            available=available,
            pending=pending,
            unavailable_or_error=error_count,
            coverage_pct=coverage,
            positive_share_pct=positive_share,
            mean_return_pct=mean_value,
            median_return_pct=median_value,
            profit_factor=profit_factor,
            best_return_pct=best,
            worst_return_pct=worst,
            mean_without_best_pct=mean_without_best,
            largest_winner_share_of_gross_profit_pct=largest_winner_share,
            classification=classification,
        ),
        violations,
    )


def evaluate_route_research_run(*, acquisition_run_key: str) -> RouteResearchEvaluation:
    run_key = str(acquisition_run_key).strip()
    if not run_key:
        raise ValueError("acquisition_run_key cannot be empty")
    outcomes = load_route_research_outcomes(acquisition_run_key=run_key)
    horizons: list[RouteResearchHorizonMetrics] = []
    violations = 0
    for horizon in (300, 900, 3600):
        metrics, local_violations = _metrics(
            horizon,
            [item for item in outcomes if item.horizon_seconds == horizon],
        )
        horizons.append(metrics)
        violations += local_violations
    return RouteResearchEvaluation(
        acquisition_run_key=run_key,
        horizons=tuple(horizons),
        lineage_violations=violations,
    )
