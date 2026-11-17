from __future__ import annotations

from dataclasses import dataclass

from src.opportunity_route_research_store import load_route_research_outcomes
from src.route_research_evaluation import RouteResearchHorizonMetrics, _metrics


@dataclass(frozen=True)
class RouteResearchMultiEvaluationV46:
    acquisition_run_keys: tuple[str, ...]
    horizons: tuple[RouteResearchHorizonMetrics, ...]
    lineage_violations: int


def evaluate_route_research_runs_v46(*, acquisition_run_keys: tuple[str, ...]) -> RouteResearchMultiEvaluationV46:
    run_keys = tuple(str(item).strip() for item in acquisition_run_keys if str(item).strip())
    if not run_keys:
        raise ValueError("acquisition_run_keys cannot be empty")
    if len(set(run_keys)) != len(run_keys):
        raise ValueError("acquisition_run_keys must be unique")

    outcomes = []
    for run_key in run_keys:
        outcomes.extend(load_route_research_outcomes(acquisition_run_key=run_key))

    horizons: list[RouteResearchHorizonMetrics] = []
    violations = 0
    for horizon in (300, 900, 3600):
        metrics, local_violations = _metrics(
            horizon,
            [item for item in outcomes if item.horizon_seconds == horizon],
        )
        horizons.append(metrics)
        violations += local_violations

    return RouteResearchMultiEvaluationV46(
        acquisition_run_keys=run_keys,
        horizons=tuple(horizons),
        lineage_violations=violations,
    )
