"""Score-free evidence surface for human review and downstream research.

The surface composes existing Market-First facts, provider-neutral structural token
risk and optional direct funding-link evidence. It reports evidence availability and
conflicts only; it does not assign weights, confidence, TAKE/SKIP actions or expected
returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.direct_funding_link_v61 import DirectFundingLinkEvidenceV61
from src.market_intelligence_baseline import MarketIntelligenceBaselineV0
from src.token_structural_risk_v0 import TokenStructuralRiskFactsV0


OPPORTUNITY_EVIDENCE_SURFACE_VERSION = "opportunity_evidence_surface_v0_score_free"


@dataclass(frozen=True)
class EvidenceDimensionV0:
    name: str
    state: str
    details: tuple[str, ...]


@dataclass(frozen=True)
class OpportunityEvidenceSurfaceV0:
    method_version: str
    token_mint: str
    as_of: int
    lifecycle_label: str
    market: MarketIntelligenceBaselineV0
    structural_risk: TokenStructuralRiskFactsV0
    direct_funding_links: tuple[DirectFundingLinkEvidenceV61, ...]
    dimensions: tuple[EvidenceDimensionV0, ...]
    provenance_keys: tuple[str, ...]
    data_quality_flags: tuple[str, ...]


def _coverage_state(values: list[float | None], *, no_activity: bool) -> str:
    if no_activity:
        return "NOT_APPLICABLE_NO_OBSERVED_ACTIVITY"
    known = [float(value) for value in values if value is not None]
    if not known or max(known) <= 0.0:
        return "MISSING"
    if all(value >= 100.0 for value in known) and len(known) == len(values):
        return "COMPLETE"
    return "PARTIAL"


def _market_dimensions(market: MarketIntelligenceBaselineV0) -> list[EvidenceDimensionV0]:
    windows = list(market.windows)
    active = [window for window in windows if int(window.event_count) > 0]
    if not windows:
        flow_state = "MISSING"
    elif not active:
        flow_state = "NO_OBSERVED_ACTIVITY"
    else:
        flow_state = "OBSERVED"

    dimensions = [
        EvidenceDimensionV0(
            name="market_flow",
            state=flow_state,
            details=tuple(
                f"{int(window.window_seconds)}s_events={int(window.event_count)}"
                for window in windows
            ),
        )
    ]

    no_activity = not active
    for name, attribute in (
        ("wallet_identity", "wallet_identity_coverage_pct"),
        ("notional", "notional_coverage_pct"),
        ("price", "price_coverage_pct"),
    ):
        values = [getattr(window, attribute) for window in active]
        dimensions.append(
            EvidenceDimensionV0(
                name=name,
                state=_coverage_state(values, no_activity=no_activity),
                details=tuple(
                    f"{int(window.window_seconds)}s={getattr(window, attribute)}"
                    for window in active
                ),
            )
        )

    execution = market.execution
    if int(execution.quote_count) <= 0:
        execution_state = "MISSING"
    elif int(execution.executable_quote_count) > 0:
        execution_state = "EXECUTABLE_OBSERVED"
    else:
        execution_state = "PROXY_ONLY"
    dimensions.append(
        EvidenceDimensionV0(
            name="execution",
            state=execution_state,
            details=(
                f"quote_count={int(execution.quote_count)}",
                f"executable_quote_count={int(execution.executable_quote_count)}",
            ),
        )
    )
    return dimensions


def _structural_dimension(risk: TokenStructuralRiskFactsV0) -> EvidenceDimensionV0:
    conflicts = sorted(
        flag.split(":", 1)[1]
        for flag in risk.data_quality_flags
        if flag.startswith("source_conflict:")
    )
    if risk.source_count <= 0:
        state = "MISSING"
    elif conflicts:
        state = "CONFLICT"
    else:
        state = "OBSERVED"
    details = [f"source_count={risk.source_count}"]
    details.extend(f"conflict={name}" for name in conflicts)
    return EvidenceDimensionV0(
        name="structural_risk",
        state=state,
        details=tuple(details),
    )


def _funding_dimension(
    links: tuple[DirectFundingLinkEvidenceV61, ...],
) -> EvidenceDimensionV0:
    if not links:
        return EvidenceDimensionV0(
            name="direct_funding_links",
            state="NOT_EVALUATED",
            details=(),
        )
    observed = [item for item in links if item.known_prelaunch_transfer_count > 0]
    state = "DIRECT_LINK_OBSERVED" if observed else "EVALUATED_NO_DIRECT_LINK"
    return EvidenceDimensionV0(
        name="direct_funding_links",
        state=state,
        details=tuple(
            f"{item.participant_wallet}:{item.evidence_classification}"
            for item in links
        ),
    )


def build_opportunity_evidence_surface_v0(
    *,
    market: MarketIntelligenceBaselineV0,
    structural_risk: TokenStructuralRiskFactsV0,
    direct_funding_links: Iterable[DirectFundingLinkEvidenceV61] = (),
) -> OpportunityEvidenceSurfaceV0:
    """Compose one T0 evidence surface with strict token/as-of alignment."""

    if market.token_mint != structural_risk.token_mint:
        raise ValueError("market and structural_risk token_mint must match")
    if int(market.as_of) != int(structural_risk.as_of):
        raise ValueError("market and structural_risk as_of must match exactly")

    links = tuple(direct_funding_links)
    for item in links:
        if item.token_address != market.token_mint:
            raise ValueError("direct funding token_address must match surface token")
        if int(item.as_of) != int(market.as_of):
            raise ValueError("direct funding as_of must match surface as_of exactly")

    dimensions = tuple(
        [
            *_market_dimensions(market),
            _structural_dimension(structural_risk),
            _funding_dimension(links),
        ]
    )

    quality = set(market.data_quality_flags)
    quality.update(structural_risk.data_quality_flags)
    for item in links:
        quality.update(item.data_quality_flags)

    provenance = list(market.provenance_keys)
    provenance.extend(structural_risk.provenance_keys)
    for item in links:
        provenance.append(item.reference_key)
        provenance.extend(item.direct_link_transaction_keys)

    return OpportunityEvidenceSurfaceV0(
        method_version=OPPORTUNITY_EVIDENCE_SURFACE_VERSION,
        token_mint=market.token_mint,
        as_of=int(market.as_of),
        lifecycle_label=market.lifecycle_label,
        market=market,
        structural_risk=structural_risk,
        direct_funding_links=links,
        dimensions=dimensions,
        provenance_keys=tuple(dict.fromkeys(provenance)),
        data_quality_flags=tuple(sorted(quality)),
    )
