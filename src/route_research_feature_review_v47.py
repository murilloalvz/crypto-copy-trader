from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from statistics import median
from typing import Any

from src.causal_quote_store import load_causal_quotes
from src.market_opportunity_episode_store import get_market_opportunity_episode
from src.opportunity_episode_enrichment import build_episode_enrichment_bundle
from src.opportunity_onchain_hazard import (
    ONCHAIN_HAZARD_PROVIDER,
    ONCHAIN_HAZARD_PURPOSE,
    evidence_from_attempt,
)
from src.opportunity_provider_attempt_store import load_provider_attempt
from src.opportunity_route_research_store import (
    ROUTE_RESEARCH_HORIZONS_SECONDS,
    load_route_research_decision,
    load_route_research_outcomes,
)
from src.route_research_evaluation import _return_for_available


V47_MIN_SPLIT_GROUP_SUPPORT = 5


@dataclass(frozen=True)
class FeatureDefinitionV47:
    name: str
    family: str
    kind: str  # numeric | boolean | categorical


FEATURE_DEFINITIONS_V47 = (
    FeatureDefinitionV47("episode_trigger_kind", "episode", "categorical"),
    FeatureDefinitionV47("episode_trigger_direction", "episode", "categorical"),
    FeatureDefinitionV47("decision_delay_seconds", "episode", "numeric"),
    FeatureDefinitionV47("flow30_event_count", "flow", "numeric"),
    FeatureDefinitionV47("flow30_buy_share_pct", "flow", "numeric"),
    FeatureDefinitionV47("flow30_wallet_identity_coverage_pct", "flow", "numeric"),
    FeatureDefinitionV47("flow30_notional_imbalance_pct", "flow", "numeric"),
    FeatureDefinitionV47("flow30_return_pct", "flow", "numeric"),
    FeatureDefinitionV47("flow60_event_count", "flow", "numeric"),
    FeatureDefinitionV47("flow300_event_count", "flow", "numeric"),
    FeatureDefinitionV47("wallet_participant_count", "wallet", "numeric"),
    FeatureDefinitionV47("wallet_repeated_event_share_pct", "wallet", "numeric"),
    FeatureDefinitionV47("hazard_mint_authority_present", "hazard", "boolean"),
    FeatureDefinitionV47("hazard_freeze_authority_present", "hazard", "boolean"),
    FeatureDefinitionV47("hazard_token_2022", "hazard", "boolean"),
    FeatureDefinitionV47("hazard_extensions_count", "hazard", "numeric"),
    FeatureDefinitionV47("entry_price_impact_pct_points", "entry_surface", "numeric"),
    FeatureDefinitionV47("entry_liquidity_usd", "entry_surface", "numeric"),
)


@dataclass(frozen=True)
class CausalFeatureRowV47:
    acquisition_run_key: str
    cohort: str
    episode_key: str
    token_mint: str
    episode_t0: int
    research_decision_as_of: int
    features: dict[str, Any]
    feature_observed_at: dict[str, int]
    labels: dict[int, float | None]
    outcome_statuses: dict[int, str]


@dataclass(frozen=True)
class FeatureDatasetV47:
    rows: tuple[CausalFeatureRowV47, ...]
    lineage_violations: int
    missing_decisions: int
    missing_episodes: int
    missing_hazard_attempts: int
    missing_entry_quotes: int
    official_decision_mutations: int


@dataclass(frozen=True)
class ReturnMetricsV47:
    n: int
    positive_share_pct: float | None
    mean_return_pct: float | None
    median_return_pct: float | None
    profit_factor: float | None


@dataclass(frozen=True)
class GroupingV47:
    feature_name: str
    descriptor: str
    assignments: dict[tuple[str, str], str]
    ordered_groups: tuple[str, ...]


@dataclass(frozen=True)
class FeatureEffectV47:
    feature_name: str
    family: str
    horizon_seconds: int
    comparison: str | None
    delta_median_a: float | None
    delta_median_b: float | None
    delta_median_all: float | None
    support_a: tuple[int, int] | None
    support_b: tuple[int, int] | None
    classification: str


def _flow_window(bundle, seconds: int):
    return next((item for item in bundle.core.flow_windows if item.window_seconds == seconds), None)


def _buy_share(window) -> float | None:
    if window is None or window.event_count <= 0:
        return None
    return 100.0 * window.buy_count / window.event_count


def _feature_values(*, episode, decision, bundle, entry_quote) -> tuple[dict[str, Any], dict[str, int]]:
    cutoff = decision.research_decision_as_of
    flow30 = _flow_window(bundle, 30)
    flow60 = _flow_window(bundle, 60)
    flow300 = _flow_window(bundle, 300)
    values: dict[str, Any] = {
        "episode_trigger_kind": episode.first_trigger_kind,
        "episode_trigger_direction": episode.first_trigger_direction,
        "decision_delay_seconds": cutoff - episode.first_trigger_observed_at,
        "flow30_event_count": flow30.event_count if flow30 else None,
        "flow30_buy_share_pct": _buy_share(flow30),
        "flow30_wallet_identity_coverage_pct": (
            flow30.wallet_identity_coverage_pct if flow30 else None
        ),
        "flow30_notional_imbalance_pct": flow30.notional_imbalance_pct if flow30 else None,
        "flow30_return_pct": flow30.return_pct if flow30 else None,
        "flow60_event_count": flow60.event_count if flow60 else None,
        "flow300_event_count": flow300.event_count if flow300 else None,
        "wallet_participant_count": bundle.wallet_intelligence.participant_wallet_count,
        "wallet_repeated_event_share_pct": (
            bundle.wallet_intelligence.repeated_participant_event_share_pct
        ),
        "hazard_mint_authority_present": bundle.risk.mint_authority_present,
        "hazard_freeze_authority_present": bundle.risk.freeze_authority_present,
        "hazard_token_2022": bundle.risk.token_2022,
        "hazard_extensions_count": len(bundle.risk.extensions_present),
        "entry_price_impact_pct_points": entry_quote.provider_price_impact_pct_points,
        "entry_liquidity_usd": entry_quote.liquidity_usd,
    }
    clocks: dict[str, int] = {}
    for definition in FEATURE_DEFINITIONS_V47:
        if definition.family == "episode":
            clocks[definition.name] = (
                episode.first_trigger_observed_at
                if definition.name != "decision_delay_seconds"
                else cutoff
            )
        elif definition.family in {"flow", "wallet"}:
            clocks[definition.name] = cutoff
        elif definition.family == "hazard":
            clocks[definition.name] = int(bundle.risk.observed_at or cutoff)
        elif definition.family == "entry_surface":
            clocks[definition.name] = entry_quote.observed_at
        else:
            clocks[definition.name] = cutoff
    return values, clocks


def validate_feature_clocks_v47(row: CausalFeatureRowV47) -> None:
    for name, observed_at in row.feature_observed_at.items():
        if observed_at > row.research_decision_as_of:
            raise ValueError(
                f"feature {name} observed after research_decision_as_of: "
                f"{observed_at}>{row.research_decision_as_of}"
            )


def _cohort_label(run_key: str) -> str:
    if run_key.endswith("-A"):
        return "A"
    if run_key.endswith("-B"):
        return "B"
    return run_key


def build_feature_dataset_v47(*, acquisition_run_keys: tuple[str, ...]) -> FeatureDatasetV47:
    run_keys = tuple(str(item).strip() for item in acquisition_run_keys if str(item).strip())
    if not run_keys or len(set(run_keys)) != len(run_keys):
        raise ValueError("acquisition_run_keys must be non-empty and unique")

    rows: list[CausalFeatureRowV47] = []
    counters = defaultdict(int)
    for run_key in run_keys:
        outcomes = load_route_research_outcomes(acquisition_run_key=run_key)
        by_episode: dict[str, list] = defaultdict(list)
        for outcome in outcomes:
            by_episode[outcome.episode_key].append(outcome)

        for episode_key, episode_outcomes in sorted(by_episode.items()):
            decision = load_route_research_decision(
                acquisition_run_key=run_key,
                episode_key=episode_key,
            )
            if decision is None:
                counters["missing_decisions"] += 1
                continue
            episode = get_market_opportunity_episode(episode_key)
            if episode is None:
                counters["missing_episodes"] += 1
                continue
            if episode.decision_as_of is not None:
                counters["official_decision_mutations"] += 1
                continue
            if (
                decision.token_mint != episode.token_mint
                or decision.episode_t0 != episode.first_trigger_observed_at
                or decision.research_decision_as_of < episode.first_trigger_observed_at
            ):
                counters["lineage_violations"] += 1
                continue

            hazard_attempt = load_provider_attempt(attempt_key=decision.hazard_attempt_key)
            if hazard_attempt is None:
                counters["missing_hazard_attempts"] += 1
                continue
            if (
                hazard_attempt.provider != ONCHAIN_HAZARD_PROVIDER
                or hazard_attempt.purpose != ONCHAIN_HAZARD_PURPOSE
                or hazard_attempt.status != "AVAILABLE"
                or hazard_attempt.completed_at is None
                or hazard_attempt.completed_at > decision.research_decision_as_of
            ):
                counters["lineage_violations"] += 1
                continue
            hazard_evidence = evidence_from_attempt(hazard_attempt)
            if (
                hazard_evidence.token_mint != episode.token_mint
                or (
                    hazard_evidence.observed_at is not None
                    and hazard_evidence.observed_at > decision.research_decision_as_of
                )
            ):
                counters["lineage_violations"] += 1
                continue

            entry_quotes = load_causal_quotes(quote_keys=(decision.entry_quote_key,))
            if len(entry_quotes) != 1:
                counters["missing_entry_quotes"] += 1
                continue
            entry_quote = entry_quotes[0]
            if (
                entry_quote.token_mint != episode.token_mint
                or entry_quote.side != "buy"
                or entry_quote.executable
                or entry_quote.observed_at > decision.research_decision_as_of
            ):
                counters["lineage_violations"] += 1
                continue

            bundle = build_episode_enrichment_bundle(
                episode=episode,
                as_of=decision.research_decision_as_of,
                quotes=(entry_quote,),
                hazard_evidence=hazard_evidence,
            )
            features, clocks = _feature_values(
                episode=episode,
                decision=decision,
                bundle=bundle,
                entry_quote=entry_quote,
            )
            labels: dict[int, float | None] = {}
            statuses: dict[int, str] = {}
            indexed = {item.horizon_seconds: item for item in episode_outcomes}
            if set(indexed) != set(ROUTE_RESEARCH_HORIZONS_SECONDS):
                counters["lineage_violations"] += 1
                continue
            label_failed = False
            for horizon in ROUTE_RESEARCH_HORIZONS_SECONDS:
                outcome = indexed[horizon]
                statuses[horizon] = outcome.status
                if outcome.research_decision_as_of != decision.research_decision_as_of:
                    counters["lineage_violations"] += 1
                    label_failed = True
                    break
                if outcome.status == "AVAILABLE":
                    try:
                        labels[horizon] = _return_for_available(outcome)
                    except ValueError:
                        counters["lineage_violations"] += 1
                        label_failed = True
                        break
                else:
                    labels[horizon] = None
            if label_failed:
                continue

            row = CausalFeatureRowV47(
                acquisition_run_key=run_key,
                cohort=_cohort_label(run_key),
                episode_key=episode_key,
                token_mint=episode.token_mint,
                episode_t0=episode.first_trigger_observed_at,
                research_decision_as_of=decision.research_decision_as_of,
                features=features,
                feature_observed_at=clocks,
                labels=labels,
                outcome_statuses=statuses,
            )
            try:
                validate_feature_clocks_v47(row)
            except ValueError:
                counters["lineage_violations"] += 1
                continue
            rows.append(row)

    return FeatureDatasetV47(
        rows=tuple(rows),
        lineage_violations=counters["lineage_violations"],
        missing_decisions=counters["missing_decisions"],
        missing_episodes=counters["missing_episodes"],
        missing_hazard_attempts=counters["missing_hazard_attempts"],
        missing_entry_quotes=counters["missing_entry_quotes"],
        official_decision_mutations=counters["official_decision_mutations"],
    )


def return_metrics_v47(values: list[float]) -> ReturnMetricsV47:
    if not values:
        return ReturnMetricsV47(0, None, None, None, None)
    positives = [item for item in values if item > 0]
    negatives = [item for item in values if item < 0]
    gross_profit = sum(positives)
    gross_loss = -sum(negatives)
    pf = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else None)
    return ReturnMetricsV47(
        n=len(values),
        positive_share_pct=100.0 * len(positives) / len(values),
        mean_return_pct=sum(values) / len(values),
        median_return_pct=float(median(values)),
        profit_factor=pf,
    )


def numeric_grouping_v47(*, rows: tuple[CausalFeatureRowV47, ...], feature_name: str) -> GroupingV47:
    values = sorted(
        {
            float(row.features[feature_name])
            for row in rows
            if isinstance(row.features.get(feature_name), (int, float))
            and not isinstance(row.features.get(feature_name), bool)
            and math.isfinite(float(row.features[feature_name]))
        }
    )
    assignments: dict[tuple[str, str], str] = {}
    if not values:
        return GroupingV47(feature_name, "NO_NONMISSING_VALUES", assignments, ())
    if len(values) == 1:
        only = values[0]
        for row in rows:
            if row.features.get(feature_name) is not None:
                assignments[(row.acquisition_run_key, row.episode_key)] = "ONLY"
        return GroupingV47(feature_name, f"single_value={only:g}", assignments, ("ONLY",))
    if len(values) == 2:
        low, high = values
        for row in rows:
            value = row.features.get(feature_name)
            if value is None:
                continue
            assignments[(row.acquisition_run_key, row.episode_key)] = (
                "LOW" if float(value) <= low else "HIGH"
            )
        return GroupingV47(
            feature_name,
            f"value_only_binary low={low:g} high={high:g}",
            assignments,
            ("LOW", "HIGH"),
        )

    low_cut = values[(len(values) - 1) // 3]
    high_cut = values[(2 * (len(values) - 1)) // 3]
    if low_cut >= high_cut:
        high_cut = next(item for item in values if item > low_cut)
    for row in rows:
        value = row.features.get(feature_name)
        if value is None:
            continue
        numeric = float(value)
        if not math.isfinite(numeric):
            continue
        group = "LOW" if numeric <= low_cut else ("MID" if numeric <= high_cut else "HIGH")
        assignments[(row.acquisition_run_key, row.episode_key)] = group
    return GroupingV47(
        feature_name,
        f"value_only_tertiles low_cut<={low_cut:g} mid_cut<={high_cut:g}",
        assignments,
        ("LOW", "MID", "HIGH"),
    )


def categorical_grouping_v47(*, rows: tuple[CausalFeatureRowV47, ...], feature_name: str) -> GroupingV47:
    assignments: dict[tuple[str, str], str] = {}
    groups: set[str] = set()
    for row in rows:
        value = row.features.get(feature_name)
        if value is None:
            continue
        if isinstance(value, bool):
            group = "TRUE" if value else "FALSE"
        else:
            group = str(value)
        groups.add(group)
        assignments[(row.acquisition_run_key, row.episode_key)] = group
    ordered = tuple(sorted(groups, key=lambda item: (item == "TRUE", item)))
    return GroupingV47(feature_name, "exact_categories", assignments, ordered)


def grouping_for_feature_v47(
    *, rows: tuple[CausalFeatureRowV47, ...], definition: FeatureDefinitionV47
) -> GroupingV47:
    if definition.kind == "numeric":
        return numeric_grouping_v47(rows=rows, feature_name=definition.name)
    return categorical_grouping_v47(rows=rows, feature_name=definition.name)


def _scope_rows(rows: tuple[CausalFeatureRowV47, ...], scope: str) -> list[CausalFeatureRowV47]:
    return list(rows) if scope == "ALL" else [row for row in rows if row.cohort == scope]


def group_metrics_v47(
    *,
    rows: tuple[CausalFeatureRowV47, ...],
    grouping: GroupingV47,
    horizon_seconds: int,
    scope: str,
) -> dict[str, ReturnMetricsV47]:
    result: dict[str, ReturnMetricsV47] = {}
    for group in grouping.ordered_groups:
        values: list[float] = []
        for row in _scope_rows(rows, scope):
            key = (row.acquisition_run_key, row.episode_key)
            if grouping.assignments.get(key) != group:
                continue
            label = row.labels.get(horizon_seconds)
            if label is not None:
                values.append(float(label))
        result[group] = return_metrics_v47(values)
    return result


def effect_for_feature_v47(
    *,
    rows: tuple[CausalFeatureRowV47, ...],
    definition: FeatureDefinitionV47,
    grouping: GroupingV47,
    horizon_seconds: int,
    min_group_support: int = V47_MIN_SPLIT_GROUP_SUPPORT,
) -> FeatureEffectV47:
    if len(grouping.ordered_groups) < 2:
        return FeatureEffectV47(
            definition.name,
            definition.family,
            horizon_seconds,
            None,
            None,
            None,
            None,
            None,
            None,
            "NO_COMPARABLE_GROUPS",
        )

    if definition.kind == "numeric" and "LOW" in grouping.ordered_groups and "HIGH" in grouping.ordered_groups:
        first, second = "LOW", "HIGH"
    elif len(grouping.ordered_groups) == 2:
        first, second = grouping.ordered_groups
    else:
        return FeatureEffectV47(
            definition.name,
            definition.family,
            horizon_seconds,
            None,
            None,
            None,
            None,
            None,
            None,
            "MULTICATEGORY_DESCRIPTIVE_ONLY",
        )

    deltas: dict[str, float | None] = {}
    support: dict[str, tuple[int, int] | None] = {}
    for scope in ("A", "B", "ALL"):
        metrics = group_metrics_v47(
            rows=rows,
            grouping=grouping,
            horizon_seconds=horizon_seconds,
            scope=scope,
        )
        left = metrics.get(first)
        right = metrics.get(second)
        support[scope] = (
            (left.n, right.n) if left is not None and right is not None else None
        )
        if (
            left is None
            or right is None
            or left.median_return_pct is None
            or right.median_return_pct is None
        ):
            deltas[scope] = None
        else:
            deltas[scope] = right.median_return_pct - left.median_return_pct

    support_ok = all(
        support[scope] is not None
        and support[scope][0] >= min_group_support
        and support[scope][1] >= min_group_support
        for scope in ("A", "B")
    )
    a = deltas["A"]
    b = deltas["B"]
    all_delta = deltas["ALL"]
    if not support_ok:
        classification = "INSUFFICIENT_SPLIT_SUPPORT"
    elif a is None or b is None or all_delta is None:
        classification = "INCOMPLETE_LABEL_SUPPORT"
    elif a == 0 or b == 0 or all_delta == 0:
        classification = "NO_DIRECTIONAL_SEPARATION"
    elif (a > 0) == (b > 0) == (all_delta > 0):
        classification = "SAME_DIRECTION_DESCRIPTIVE_ONLY"
    else:
        classification = "UNSTABLE_ACROSS_SUBCOHORTS"

    return FeatureEffectV47(
        feature_name=definition.name,
        family=definition.family,
        horizon_seconds=horizon_seconds,
        comparison=f"{second}-{first}",
        delta_median_a=a,
        delta_median_b=b,
        delta_median_all=all_delta,
        support_a=support["A"],
        support_b=support["B"],
        classification=classification,
    )


def feature_coverage_v47(
    *, rows: tuple[CausalFeatureRowV47, ...], feature_name: str, scope: str
) -> tuple[int, int, float]:
    scoped = _scope_rows(rows, scope)
    known = sum(1 for row in scoped if row.features.get(feature_name) is not None)
    total = len(scoped)
    return known, total, (100.0 * known / total if total else 0.0)
