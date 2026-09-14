"""Pure adapter from Solana Tracker token-info payloads to structural-risk facts.

No network request is performed here. Only response fields explicitly documented on
Solana Tracker's token-information endpoint are mapped. Missing provider fields remain
``None``; notably, omitted ``risk.bundlers`` is not interpreted as zero.
"""

from __future__ import annotations

from typing import Any

from src.token_structural_risk_v0 import StructuralRiskObservationV0


SOLANA_TRACKER_STRUCTURAL_RISK_ADAPTER_VERSION = (
    "solana_tracker_structural_risk_adapter_v0"
)
SOLANA_TRACKER_SOURCE = "solanatracker_token_info"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def adapt_solana_tracker_token_info_v0(
    payload: dict[str, Any],
    *,
    token_mint: str,
    observed_at: int,
    evidence_key: str,
) -> StructuralRiskObservationV0:
    """Normalize one already-fetched Solana Tracker token-info response."""

    if not isinstance(payload, dict):
        raise TypeError("payload must be a dict")

    token = _dict(payload.get("token"))
    payload_mint = token.get("mint")
    if isinstance(payload_mint, str) and payload_mint.strip() and payload_mint != token_mint:
        raise ValueError("Solana Tracker payload token mint does not match requested token")

    creation = _dict(token.get("creation"))
    creator = creation.get("creator")
    creator_wallet = creator if isinstance(creator, str) and creator.strip() else None

    risk = _dict(payload.get("risk"))
    dev = _dict(risk.get("dev"))
    snipers = _dict(risk.get("snipers"))
    insiders = _dict(risk.get("insiders"))
    bundlers_value = risk.get("bundlers")
    bundlers = _dict(bundlers_value) if bundlers_value is not None else {}

    return StructuralRiskObservationV0(
        token_mint=token_mint,
        observed_at=observed_at,
        evidence_key=evidence_key,
        source=SOLANA_TRACKER_SOURCE,
        holder_count=_integer(payload.get("holders")),
        top10_holder_pct=_number(risk.get("top10")),
        dev_holder_pct=_number(dev.get("percentage")),
        insider_holder_pct=_number(insiders.get("totalPercentage")),
        sniper_holder_pct=_number(snipers.get("totalPercentage")),
        bundler_holder_pct=_number(bundlers.get("totalPercentage")),
        creator_wallet=creator_wallet,
    )
