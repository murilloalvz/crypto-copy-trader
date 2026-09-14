"""Human-facing factual explanation of OpportunityEvidenceSurfaceV0.

The explainer deliberately mirrors observed evidence and missingness. It never emits a
trade action, weighted score, confidence percentage or expected return.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.opportunity_evidence_surface_v0 import OpportunityEvidenceSurfaceV0


OPPORTUNITY_EVIDENCE_EXPLAINER_VERSION = "opportunity_evidence_explainer_v0_factual"


@dataclass(frozen=True)
class EvidenceExplanationSectionV0:
    name: str
    state: str
    facts: tuple[str, ...]
    cautions: tuple[str, ...]


@dataclass(frozen=True)
class OpportunityEvidenceExplanationV0:
    method_version: str
    token_mint: str
    as_of: int
    lifecycle_label: str
    sections: tuple[EvidenceExplanationSectionV0, ...]
    quality_flags: tuple[str, ...]
    provenance_count: int


def _range_fact(label: str, item) -> str | None:
    if item.known_source_count <= 0:
        return None
    if item.min_value == item.max_value:
        return f"{label}={item.min_value} ({item.known_source_count} source(s))"
    return (
        f"{label}_range={item.min_value}..{item.max_value} "
        f"({item.known_source_count} source(s))"
    )


def _boolean_fact(label: str, item) -> tuple[str | None, str | None]:
    if item.known_source_count <= 0:
        return None, None
    if item.conflict:
        return None, f"source_conflict:{label}"
    return (
        f"{label}={str(item.consensus_value).lower()} "
        f"({item.known_source_count} source(s))",
        None,
    )


def explain_opportunity_evidence_v0(
    surface: OpportunityEvidenceSurfaceV0,
) -> OpportunityEvidenceExplanationV0:
    dimension_map = {item.name: item for item in surface.dimensions}
    sections: list[EvidenceExplanationSectionV0] = []

    for name in ("market_flow", "wallet_identity", "notional", "price", "execution"):
        item = dimension_map[name]
        cautions: list[str] = []
        if item.state in {"MISSING", "PARTIAL", "PROXY_ONLY"}:
            cautions.append(f"{name}_evidence_{item.state.lower()}")
        sections.append(
            EvidenceExplanationSectionV0(
                name=name,
                state=item.state,
                facts=item.details,
                cautions=tuple(cautions),
            )
        )

    risk = surface.structural_risk
    risk_dimension = dimension_map["structural_risk"]
    risk_facts: list[str] = []
    for label, value in (
        ("holder_count", risk.holder_count),
        ("top10_holder_pct", risk.top10_holder_pct),
        ("largest_holder_pct", risk.largest_holder_pct),
        ("dev_holder_pct", risk.dev_holder_pct),
        ("insider_holder_pct", risk.insider_holder_pct),
        ("sniper_holder_pct", risk.sniper_holder_pct),
        ("bundler_holder_pct", risk.bundler_holder_pct),
        ("liquidity_burned_pct", risk.liquidity_burned_pct),
        ("liquidity_locked_pct", risk.liquidity_locked_pct),
    ):
        fact = _range_fact(label, value)
        if fact is not None:
            risk_facts.append(fact)
    risk_cautions: list[str] = []
    for label, value in (
        ("mint_authority_active", risk.mint_authority_active),
        ("freeze_authority_active", risk.freeze_authority_active),
        ("provider_honeypot_flag", risk.provider_honeypot_flag),
    ):
        fact, caution = _boolean_fact(label, value)
        if fact is not None:
            risk_facts.append(fact)
        if caution is not None:
            risk_cautions.append(caution)
    if risk.creator_wallets:
        risk_facts.append(f"creator_wallets={','.join(risk.creator_wallets)}")
    risk_cautions.extend(
        flag for flag in risk.data_quality_flags if flag not in risk_cautions
    )
    sections.append(
        EvidenceExplanationSectionV0(
            name="structural_risk",
            state=risk_dimension.state,
            facts=tuple(risk_facts),
            cautions=tuple(risk_cautions),
        )
    )

    funding_dimension = dimension_map["direct_funding_links"]
    funding_facts = tuple(
        f"participant={item.participant_wallet};classification={item.evidence_classification};"
        f"known_prelaunch_transfers={item.known_prelaunch_transfer_count}"
        for item in surface.direct_funding_links
    )
    sections.append(
        EvidenceExplanationSectionV0(
            name="direct_funding_links",
            state=funding_dimension.state,
            facts=funding_facts,
            cautions=(
                ("direct_funding_link_is_evidence_not_proof_of_insider_behavior",)
                if funding_dimension.state == "DIRECT_LINK_OBSERVED"
                else ()
            ),
        )
    )

    return OpportunityEvidenceExplanationV0(
        method_version=OPPORTUNITY_EVIDENCE_EXPLAINER_VERSION,
        token_mint=surface.token_mint,
        as_of=surface.as_of,
        lifecycle_label=surface.lifecycle_label,
        sections=tuple(sections),
        quality_flags=surface.data_quality_flags,
        provenance_count=len(surface.provenance_keys),
    )
