from __future__ import annotations

from dataclasses import dataclass
import math

from src.causal_quote_store import load_causal_quotes
from src.market_opportunity_episode_store import get_market_opportunity_episode
from src.opportunity_episode_enrichment import build_episode_enrichment_bundle
from src.opportunity_onchain_hazard import evidence_from_attempt
from src.opportunity_provider_attempt_store import load_provider_attempt
from src.opportunity_route_research_store import load_route_research_decision
from src.route_research_feature_review_v47 import (
    CausalFeatureRowV47,
    FeatureDatasetV47,
    FeatureDefinitionV47,
    build_feature_dataset_v47,
    validate_feature_clocks_v47,
)


V55_PRIMARY_DISCOVERY_HORIZON_SECONDS = 900
V55_MIN_FEATURE_COVERAGE_PCT_PER_SUBCOHORT = 80.0
V55_MIN_ROWS_PER_SUBCOHORT = 30

# Closed, predeclared feature set. These are simple causal transforms of the existing
# score-free 10/30/60/300s opportunity snapshot. No labels are used to construct a feature.
FEATURE_DEFINITIONS_V55 = (
    FeatureDefinitionV47("flow10_event_count", "intensity", "numeric"),
    FeatureDefinitionV47("flow10_vs_60_event_rate_ratio", "acceleration", "numeric"),
    FeatureDefinitionV47("flow30_vs_300_event_rate_ratio", "acceleration", "numeric"),
    FeatureDefinitionV47("flow10_buy_share_pct", "direction", "numeric"),
    FeatureDefinitionV47("flow60_buy_share_pct", "direction", "numeric"),
    FeatureDefinitionV47("flow10_unique_buy_wallet_count", "diversity", "numeric"),
    FeatureDefinitionV47("flow30_unique_buy_wallet_count", "diversity", "numeric"),
    FeatureDefinitionV47("flow60_unique_buy_wallet_count", "diversity", "numeric"),
    FeatureDefinitionV47("flow30_wallet_direction_balance", "diversity", "numeric"),
    FeatureDefinitionV47("flow60_wallet_direction_balance", "diversity", "numeric"),
    FeatureDefinitionV47("flow30_repeated_wallet_event_share_pct", "repetition", "numeric"),
    FeatureDefinitionV47("flow60_repeated_wallet_event_share_pct", "repetition", "numeric"),
)


@dataclass(frozen=True)
class EarlyOpportunityDatasetV55:
    rows: tuple[CausalFeatureRowV47, ...]
    base: FeatureDatasetV47
    augmentation_failures: int
    feature_clock_violations: int


def _flow_window(bundle, seconds: int):
    return next((item for item in bundle.core.flow_windows if item.window_seconds == seconds), None)


def _buy_share(window) -> float | None:
    if window is None or window.event_count <= 0:
        return None
    return 100.0 * window.buy_count / window.event_count


def _rate_ratio(short_window, long_window) -> float | None:
    if short_window is None or long_window is None or long_window.event_count <= 0:
        return None
    short_rate = short_window.event_count / float(short_window.window_seconds)
    long_rate = long_window.event_count / float(long_window.window_seconds)
    if long_rate <= 0:
        return None
    value = short_rate / long_rate
    return value if math.isfinite(value) else None


def _wallet_direction_balance(window) -> int | None:
    if window is None:
        return None
    return window.unique_buy_wallet_count - window.unique_sell_wallet_count


def derived_features_from_bundle_v55(bundle) -> dict[str, float | int | None]:
    """Build the closed v55 feature set from one causal enrichment bundle only."""

    flow10 = _flow_window(bundle, 10)
    flow30 = _flow_window(bundle, 30)
    flow60 = _flow_window(bundle, 60)
    flow300 = _flow_window(bundle, 300)
    return {
        "flow10_event_count": flow10.event_count if flow10 else None,
        "flow10_vs_60_event_rate_ratio": _rate_ratio(flow10, flow60),
        "flow30_vs_300_event_rate_ratio": _rate_ratio(flow30, flow300),
        "flow10_buy_share_pct": _buy_share(flow10),
        "flow60_buy_share_pct": _buy_share(flow60),
        "flow10_unique_buy_wallet_count": flow10.unique_buy_wallet_count if flow10 else None,
        "flow30_unique_buy_wallet_count": flow30.unique_buy_wallet_count if flow30 else None,
        "flow60_unique_buy_wallet_count": flow60.unique_buy_wallet_count if flow60 else None,
        "flow30_wallet_direction_balance": _wallet_direction_balance(flow30),
        "flow60_wallet_direction_balance": _wallet_direction_balance(flow60),
        "flow30_repeated_wallet_event_share_pct": (
            flow30.repeated_wallet_event_share_pct if flow30 else None
        ),
        "flow60_repeated_wallet_event_share_pct": (
            flow60.repeated_wallet_event_share_pct if flow60 else None
        ),
    }


def build_early_opportunity_dataset_v55(
    *, acquisition_run_keys: tuple[str, ...]
) -> EarlyOpportunityDatasetV55:
    """Augment the validated v47 causal rows with predeclared early-opportunity dynamics.

    The v47 builder remains the lineage authority. v55 then reconstructs only evidence already
    observable by each row's research_decision_as_of and adds deterministic transforms of the
    existing score-free snapshot. Labels are copied unchanged and never participate in feature
    construction.
    """

    base = build_feature_dataset_v47(acquisition_run_keys=acquisition_run_keys)
    augmented: list[CausalFeatureRowV47] = []
    augmentation_failures = 0
    feature_clock_violations = 0

    for row in base.rows:
        decision = load_route_research_decision(
            acquisition_run_key=row.acquisition_run_key,
            episode_key=row.episode_key,
        )
        episode = get_market_opportunity_episode(row.episode_key)
        if decision is None or episode is None:
            augmentation_failures += 1
            continue

        hazard_attempt = load_provider_attempt(attempt_key=decision.hazard_attempt_key)
        quotes = load_causal_quotes(quote_keys=(decision.entry_quote_key,))
        if hazard_attempt is None or len(quotes) != 1:
            augmentation_failures += 1
            continue
        try:
            hazard_evidence = evidence_from_attempt(hazard_attempt)
            bundle = build_episode_enrichment_bundle(
                episode=episode,
                as_of=decision.research_decision_as_of,
                quotes=(quotes[0],),
                hazard_evidence=hazard_evidence,
            )
            derived = derived_features_from_bundle_v55(bundle)
        except (TypeError, ValueError):
            augmentation_failures += 1
            continue

        features = dict(row.features)
        features.update(derived)
        clocks = dict(row.feature_observed_at)
        for definition in FEATURE_DEFINITIONS_V55:
            clocks[definition.name] = decision.research_decision_as_of

        augmented_row = CausalFeatureRowV47(
            acquisition_run_key=row.acquisition_run_key,
            cohort=row.cohort,
            episode_key=row.episode_key,
            token_mint=row.token_mint,
            episode_t0=row.episode_t0,
            research_decision_as_of=row.research_decision_as_of,
            features=features,
            feature_observed_at=clocks,
            labels=dict(row.labels),
            outcome_statuses=dict(row.outcome_statuses),
        )
        try:
            validate_feature_clocks_v47(augmented_row)
        except ValueError:
            feature_clock_violations += 1
            continue
        augmented.append(augmented_row)

    return EarlyOpportunityDatasetV55(
        rows=tuple(augmented),
        base=base,
        augmentation_failures=augmentation_failures,
        feature_clock_violations=feature_clock_violations,
    )


def feature_coverage_by_scope_v55(
    *, rows: tuple[CausalFeatureRowV47, ...], feature_name: str, scope: str
) -> tuple[int, int, float]:
    scoped = rows if scope == "ALL" else tuple(row for row in rows if row.cohort == scope)
    total = len(scoped)
    known = sum(1 for row in scoped if row.features.get(feature_name) is not None)
    pct = 100.0 * known / total if total else 0.0
    return known, total, pct


def candidate_coverage_ok_v55(
    *, rows: tuple[CausalFeatureRowV47, ...], feature_name: str
) -> bool:
    for scope in ("A", "B"):
        _known, _total, pct = feature_coverage_by_scope_v55(
            rows=rows,
            feature_name=feature_name,
            scope=scope,
        )
        if pct < V55_MIN_FEATURE_COVERAGE_PCT_PER_SUBCOHORT:
            return False
    return True
