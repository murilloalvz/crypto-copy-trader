from __future__ import annotations

from dataclasses import dataclass
import math
import time

from src.discovery.solana_tracker import (
    SolanaTrackerClient,
    SolanaTrackerConfigurationError,
    SolanaTrackerError,
)
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_provider_attempt_store import (
    OpportunityProviderAttempt,
    begin_provider_attempt,
    complete_provider_attempt,
    load_provider_attempt,
)


SOLANA_TRACKER_HAZARD_PROVIDER = "solana_tracker_token_info"
SOLANA_TRACKER_HAZARD_PURPOSE = "token_hazard_v1"


@dataclass(frozen=True)
class TokenHazardEvidence:
    episode_key: str
    token_mint: str
    provider: str
    observed_at: int | None
    status: str
    risk_score: float | None
    rugged: bool | None
    jupiter_verified: bool | None
    top10_pct: float | None
    dev_pct: float | None
    snipers_pct: float | None
    bundlers_pct: float | None
    insiders_pct: float | None
    freeze_authority_present: bool | None
    mint_authority_present: bool | None
    risk_factors: tuple[tuple[str, str, float | None], ...]
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class TokenHazardCaptureResult:
    attempt: OpportunityProviderAttempt
    evidence: TokenHazardEvidence
    reused_attempt: bool


def _optional_float(value) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _optional_bool(value) -> bool | None:
    return value if isinstance(value, bool) else None


def _percentage(group) -> float | None:
    if not isinstance(group, dict):
        return None
    return _optional_float(group.get("totalPercentage"))


def _dev_percentage(risk: dict) -> float | None:
    dev = risk.get("dev")
    if isinstance(dev, dict):
        return _optional_float(dev.get("percentage"))
    return _optional_float(dev)


def _authority_presence(pools, field: str) -> tuple[bool | None, bool]:
    if not isinstance(pools, list) or not pools:
        return None, False
    observed: list[str | None] = []
    for pool in pools:
        if not isinstance(pool, dict):
            continue
        security = pool.get("security")
        if not isinstance(security, dict) or field not in security:
            continue
        value = security.get(field)
        observed.append(None if value is None or str(value).strip() == "" else str(value).strip())
    if not observed:
        return None, False
    non_null = {item for item in observed if item is not None}
    # Multiple non-null authorities across pools are still represented conservatively as present,
    # while the caller receives an inconsistency flag for audit.
    return bool(non_null), len(non_null) > 1


def _risk_factors(risk: dict) -> tuple[tuple[str, str, float | None], ...]:
    result: list[tuple[str, str, float | None]] = []
    raw = risk.get("risks")
    if not isinstance(raw, list):
        return ()
    for item in raw[:50]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        level = str(item.get("level") or "").strip()
        if not name and not level:
            continue
        result.append((name or "unknown", level or "unknown", _optional_float(item.get("score"))))
    return tuple(result)


def _normalize_payload(
    *,
    episode: MarketOpportunityEpisode,
    payload: dict,
    observed_at: int,
    status: str = "AVAILABLE",
) -> TokenHazardEvidence:
    token = payload.get("token")
    returned_mint = str(token.get("mint") or "").strip() if isinstance(token, dict) else ""
    if returned_mint and returned_mint != episode.token_mint:
        raise ValueError("Solana Tracker token response mint does not match episode token")

    risk = payload.get("risk")
    if not isinstance(risk, dict):
        return TokenHazardEvidence(
            episode_key=episode.episode_key,
            token_mint=episode.token_mint,
            provider=SOLANA_TRACKER_HAZARD_PROVIDER,
            observed_at=observed_at,
            status="UNAVAILABLE",
            risk_score=None,
            rugged=None,
            jupiter_verified=None,
            top10_pct=None,
            dev_pct=None,
            snipers_pct=None,
            bundlers_pct=None,
            insiders_pct=None,
            freeze_authority_present=None,
            mint_authority_present=None,
            risk_factors=(),
            data_quality_flags=("risk_object_missing",),
        )

    freeze_present, freeze_inconsistent = _authority_presence(payload.get("pools"), "freezeAuthority")
    mint_present, mint_inconsistent = _authority_presence(payload.get("pools"), "mintAuthority")
    quality: list[str] = []
    if risk.get("score") is None:
        quality.append("risk_score_missing")
    if "rugged" not in risk:
        quality.append("rugged_status_missing")
    if _percentage(risk.get("snipers")) is None:
        quality.append("snipers_percentage_missing")
    if _percentage(risk.get("bundlers")) is None:
        quality.append("bundlers_percentage_missing")
    if _percentage(risk.get("insiders")) is None:
        quality.append("insiders_percentage_missing")
    if freeze_present is None:
        quality.append("freeze_authority_missing")
    if mint_present is None:
        quality.append("mint_authority_missing")
    if freeze_inconsistent:
        quality.append("freeze_authority_inconsistent_across_pools")
    if mint_inconsistent:
        quality.append("mint_authority_inconsistent_across_pools")

    return TokenHazardEvidence(
        episode_key=episode.episode_key,
        token_mint=episode.token_mint,
        provider=SOLANA_TRACKER_HAZARD_PROVIDER,
        observed_at=observed_at,
        status=status,
        risk_score=_optional_float(risk.get("score")),
        rugged=_optional_bool(risk.get("rugged")),
        jupiter_verified=_optional_bool(risk.get("jupiterVerified")),
        top10_pct=_optional_float(risk.get("top10")),
        dev_pct=_dev_percentage(risk),
        snipers_pct=_percentage(risk.get("snipers")),
        bundlers_pct=_percentage(risk.get("bundlers")),
        insiders_pct=_percentage(risk.get("insiders")),
        freeze_authority_present=freeze_present,
        mint_authority_present=mint_present,
        risk_factors=_risk_factors(risk),
        data_quality_flags=tuple(quality),
    )


def _details(evidence: TokenHazardEvidence) -> dict:
    return {
        "token_mint": evidence.token_mint,
        "observed_at": evidence.observed_at,
        "risk_score": evidence.risk_score,
        "rugged": evidence.rugged,
        "jupiter_verified": evidence.jupiter_verified,
        "top10_pct": evidence.top10_pct,
        "dev_pct": evidence.dev_pct,
        "snipers_pct": evidence.snipers_pct,
        "bundlers_pct": evidence.bundlers_pct,
        "insiders_pct": evidence.insiders_pct,
        "freeze_authority_present": evidence.freeze_authority_present,
        "mint_authority_present": evidence.mint_authority_present,
        "risk_factors": [
            {"name": name, "level": level, "score": score}
            for name, level, score in evidence.risk_factors
        ],
        "data_quality_flags": list(evidence.data_quality_flags),
    }


def evidence_from_attempt(attempt: OpportunityProviderAttempt) -> TokenHazardEvidence:
    details = attempt.details or {}
    factors = []
    for item in details.get("risk_factors") or []:
        if isinstance(item, dict):
            factors.append(
                (
                    str(item.get("name") or "unknown"),
                    str(item.get("level") or "unknown"),
                    _optional_float(item.get("score")),
                )
            )
    return TokenHazardEvidence(
        episode_key=attempt.episode_key,
        token_mint=str(details.get("token_mint") or ""),
        provider=attempt.provider,
        observed_at=(int(details["observed_at"]) if details.get("observed_at") is not None else None),
        status=attempt.status,
        risk_score=_optional_float(details.get("risk_score")),
        rugged=_optional_bool(details.get("rugged")),
        jupiter_verified=_optional_bool(details.get("jupiter_verified")),
        top10_pct=_optional_float(details.get("top10_pct")),
        dev_pct=_optional_float(details.get("dev_pct")),
        snipers_pct=_optional_float(details.get("snipers_pct")),
        bundlers_pct=_optional_float(details.get("bundlers_pct")),
        insiders_pct=_optional_float(details.get("insiders_pct")),
        freeze_authority_present=_optional_bool(details.get("freeze_authority_present")),
        mint_authority_present=_optional_bool(details.get("mint_authority_present")),
        risk_factors=tuple(factors),
        data_quality_flags=tuple(str(item) for item in (details.get("data_quality_flags") or [])),
    )


class SolanaTrackerTokenHazardProbe:
    """At-most-once causal hazard capture for one already-admitted opportunity episode.

    STARTED is persisted before provider I/O. Provider absence/failure remains explicit and no
    risk threshold is used to select or reject episodes in this module.
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: int = 8,
        max_attempts: int = 1,
    ):
        if timeout_seconds <= 0 or max_attempts <= 0:
            raise ValueError("provider timeout and max_attempts must be positive")
        self.api_key = api_key.strip()
        self.timeout_seconds = int(timeout_seconds)
        self.max_attempts = int(max_attempts)

    @staticmethod
    def attempt_key(episode: MarketOpportunityEpisode) -> str:
        return (
            f"provider:{SOLANA_TRACKER_HAZARD_PROVIDER}:{SOLANA_TRACKER_HAZARD_PURPOSE}:"
            f"{episode.acquisition_run_key}:{episode.episode_key}"
        )

    def _existing(self, episode: MarketOpportunityEpisode) -> TokenHazardCaptureResult:
        attempt = load_provider_attempt(attempt_key=self.attempt_key(episode))
        if attempt is None:
            raise RuntimeError("token hazard provider attempt disappeared after idempotent begin")
        return TokenHazardCaptureResult(
            attempt=attempt,
            evidence=evidence_from_attempt(attempt),
            reused_attempt=True,
        )

    def _complete(
        self,
        episode: MarketOpportunityEpisode,
        *,
        started_at: int,
        status: str,
        evidence: TokenHazardEvidence | None = None,
        error: BaseException | None = None,
        details: dict | None = None,
    ) -> OpportunityProviderAttempt:
        observed_floor = evidence.observed_at if evidence is not None else None
        completed_at = max(
            started_at,
            int(time.time()),
            int(observed_floor) if observed_floor is not None else started_at,
        )
        payload_details = _details(evidence) if evidence is not None else (details or {})
        return complete_provider_attempt(
            attempt_key=self.attempt_key(episode),
            status=status,
            completed_at=completed_at,
            error_type=(type(error).__name__ if error is not None else None),
            error_message=(str(error) if error is not None else None),
            details=payload_details,
        )

    def capture(self, episode: MarketOpportunityEpisode) -> TokenHazardCaptureResult:
        if not episode.episode_key.strip() or not episode.token_mint.strip():
            raise ValueError("episode identity is incomplete")
        started_at = max(int(time.time()), int(episode.first_trigger_observed_at))
        is_new = begin_provider_attempt(
            attempt_key=self.attempt_key(episode),
            acquisition_run_key=episode.acquisition_run_key,
            episode_key=episode.episode_key,
            provider=SOLANA_TRACKER_HAZARD_PROVIDER,
            purpose=SOLANA_TRACKER_HAZARD_PURPOSE,
            started_at=started_at,
        )
        if not is_new:
            return self._existing(episode)

        if not self.api_key:
            attempt = self._complete(
                episode,
                started_at=started_at,
                status="CONFIG_MISSING",
                details={"missing": ["SOLANA_TRACKER_API_KEY"], "token_mint": episode.token_mint},
            )
            return TokenHazardCaptureResult(
                attempt=attempt,
                evidence=evidence_from_attempt(attempt),
                reused_attempt=False,
            )

        client = SolanaTrackerClient(
            api_key=self.api_key,
            timeout=self.timeout_seconds,
            max_attempts=self.max_attempts,
            request_interval_seconds=0,
        )
        try:
            # Reuse the repository's authenticated/retrying read-only transport. This endpoint is
            # documented by Solana Tracker as GET /tokens/{mint}.
            payload = client._request(f"/tokens/{episode.token_mint}", {})
        except SolanaTrackerConfigurationError as exc:
            attempt = self._complete(
                episode,
                started_at=started_at,
                status="CONFIG_MISSING",
                error=exc,
                details={"token_mint": episode.token_mint},
            )
            return TokenHazardCaptureResult(attempt, evidence_from_attempt(attempt), False)
        except SolanaTrackerError as exc:
            attempt = self._complete(
                episode,
                started_at=started_at,
                status="PROVIDER_ERROR",
                error=exc,
                details={"token_mint": episode.token_mint},
            )
            return TokenHazardCaptureResult(attempt, evidence_from_attempt(attempt), False)

        observed_at = max(started_at, int(time.time()))
        try:
            evidence = _normalize_payload(
                episode=episode,
                payload=payload,
                observed_at=observed_at,
            )
        except (ValueError, TypeError, KeyError) as exc:
            attempt = self._complete(
                episode,
                started_at=started_at,
                status="NORMALIZATION_ERROR",
                error=exc,
                details={"token_mint": episode.token_mint, "observed_at": observed_at},
            )
            return TokenHazardCaptureResult(attempt, evidence_from_attempt(attempt), False)

        attempt = self._complete(
            episode,
            started_at=started_at,
            status=evidence.status,
            evidence=evidence,
        )
        return TokenHazardCaptureResult(
            attempt=attempt,
            evidence=evidence_from_attempt(attempt),
            reused_attempt=False,
        )
