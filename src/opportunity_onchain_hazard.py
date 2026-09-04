from __future__ import annotations

from dataclasses import dataclass
import time

from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_provider_attempt_store import (
    OpportunityProviderAttempt,
    begin_provider_attempt,
    complete_provider_attempt,
    load_provider_attempt,
)
from src.solana import SolanaClient, SolanaRPCError


ONCHAIN_HAZARD_PROVIDER = "solana_rpc_mint_hazard_v1"
ONCHAIN_HAZARD_PURPOSE = "token_hazard_minimal_v1"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
SUPPORTED_TOKEN_PROGRAMS = {TOKEN_PROGRAM, TOKEN_2022_PROGRAM}


@dataclass(frozen=True)
class OnchainMintHazardEvidence:
    episode_key: str
    token_mint: str
    provider: str
    observed_at: int | None
    context_slot: int | None
    status: str
    token_program: str | None
    decimals: int | None
    supply_raw: str | None
    mint_authority_present: bool | None
    freeze_authority_present: bool | None
    token_2022: bool | None
    extensions_present: tuple[str, ...]
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class OnchainMintHazardCaptureResult:
    attempt: OpportunityProviderAttempt
    evidence: OnchainMintHazardEvidence
    reused_attempt: bool


def _details(evidence: OnchainMintHazardEvidence) -> dict:
    return {
        "token_mint": evidence.token_mint,
        "observed_at": evidence.observed_at,
        "context_slot": evidence.context_slot,
        "token_program": evidence.token_program,
        "decimals": evidence.decimals,
        "supply_raw": evidence.supply_raw,
        "mint_authority_present": evidence.mint_authority_present,
        "freeze_authority_present": evidence.freeze_authority_present,
        "token_2022": evidence.token_2022,
        "extensions_present": list(evidence.extensions_present),
        "data_quality_flags": list(evidence.data_quality_flags),
    }


def evidence_from_attempt(attempt: OpportunityProviderAttempt) -> OnchainMintHazardEvidence:
    details = attempt.details or {}
    return OnchainMintHazardEvidence(
        episode_key=attempt.episode_key,
        token_mint=str(details.get("token_mint") or ""),
        provider=attempt.provider,
        observed_at=(int(details["observed_at"]) if details.get("observed_at") is not None else None),
        context_slot=(int(details["context_slot"]) if details.get("context_slot") is not None else None),
        status=attempt.status,
        token_program=(str(details["token_program"]) if details.get("token_program") else None),
        decimals=(int(details["decimals"]) if details.get("decimals") is not None else None),
        supply_raw=(str(details["supply_raw"]) if details.get("supply_raw") is not None else None),
        mint_authority_present=(details.get("mint_authority_present") if isinstance(details.get("mint_authority_present"), bool) else None),
        freeze_authority_present=(details.get("freeze_authority_present") if isinstance(details.get("freeze_authority_present"), bool) else None),
        token_2022=(details.get("token_2022") if isinstance(details.get("token_2022"), bool) else None),
        extensions_present=tuple(str(item) for item in (details.get("extensions_present") or [])),
        data_quality_flags=tuple(str(item) for item in (details.get("data_quality_flags") or [])),
    )


def _normalize_account_info(
    *,
    episode: MarketOpportunityEpisode,
    result: dict,
    observed_at: int,
) -> OnchainMintHazardEvidence:
    if not isinstance(result, dict):
        raise ValueError("getAccountInfo result is not an object")
    context = result.get("context") or {}
    value = result.get("value")
    if value is None:
        return OnchainMintHazardEvidence(
            episode_key=episode.episode_key,
            token_mint=episode.token_mint,
            provider=ONCHAIN_HAZARD_PROVIDER,
            observed_at=observed_at,
            context_slot=(int(context["slot"]) if context.get("slot") is not None else None),
            status="UNAVAILABLE",
            token_program=None,
            decimals=None,
            supply_raw=None,
            mint_authority_present=None,
            freeze_authority_present=None,
            token_2022=None,
            extensions_present=(),
            data_quality_flags=("mint_account_missing",),
        )
    if not isinstance(value, dict):
        raise ValueError("getAccountInfo value is not an object")

    owner = str(value.get("owner") or "").strip() or None
    flags: list[str] = []
    if owner not in SUPPORTED_TOKEN_PROGRAMS:
        flags.append("unsupported_mint_owner_program")

    data = value.get("data")
    parsed = data.get("parsed") if isinstance(data, dict) else None
    info = parsed.get("info") if isinstance(parsed, dict) else None
    parsed_type = str(parsed.get("type") or "") if isinstance(parsed, dict) else ""
    if not isinstance(info, dict) or parsed_type != "mint":
        raise ValueError("mint account was not returned as jsonParsed mint state")

    def authority_present(name: str) -> bool | None:
        if name not in info:
            flags.append(f"{name}_missing")
            return None
        value = info.get(name)
        return value is not None and str(value).strip() != ""

    extensions: list[str] = []
    raw_extensions = info.get("extensions")
    if raw_extensions is None and isinstance(parsed, dict):
        raw_extensions = parsed.get("extensions")
    if isinstance(raw_extensions, list):
        for item in raw_extensions:
            if isinstance(item, dict):
                name = str(item.get("extension") or item.get("type") or "").strip()
            else:
                name = str(item).strip()
            if name and name not in extensions:
                extensions.append(name)
    if owner == TOKEN_2022_PROGRAM and not extensions:
        flags.append("token_2022_extensions_not_exposed_by_rpc")

    decimals = info.get("decimals")
    supply = info.get("supply")
    if decimals is None:
        flags.append("decimals_missing")
    if supply is None:
        flags.append("supply_missing")

    return OnchainMintHazardEvidence(
        episode_key=episode.episode_key,
        token_mint=episode.token_mint,
        provider=ONCHAIN_HAZARD_PROVIDER,
        observed_at=observed_at,
        context_slot=(int(context["slot"]) if context.get("slot") is not None else None),
        status="AVAILABLE",
        token_program=owner,
        decimals=(int(decimals) if decimals is not None else None),
        supply_raw=(str(supply) if supply is not None else None),
        mint_authority_present=authority_present("mintAuthority"),
        freeze_authority_present=authority_present("freezeAuthority"),
        token_2022=(owner == TOKEN_2022_PROGRAM if owner is not None else None),
        extensions_present=tuple(extensions),
        data_quality_flags=tuple(flags),
    )


class SolanaRPCMintHazardProbe:
    """At-most-once minimal causal token hazard using only Solana RPC mint state.

    This intentionally does not synthesize proprietary concepts such as risk score, rugged,
    snipers, bundlers or insiders. Those remain optional enrichment from separate providers.
    """

    def __init__(self, *, rpc_timeout_seconds: int = 3):
        if rpc_timeout_seconds <= 0:
            raise ValueError("rpc_timeout_seconds must be positive")
        self.rpc_timeout_seconds = int(rpc_timeout_seconds)

    @staticmethod
    def attempt_key(episode: MarketOpportunityEpisode) -> str:
        return (
            f"provider:{ONCHAIN_HAZARD_PROVIDER}:{ONCHAIN_HAZARD_PURPOSE}:"
            f"{episode.acquisition_run_key}:{episode.episode_key}"
        )

    def _existing(self, episode: MarketOpportunityEpisode) -> OnchainMintHazardCaptureResult:
        attempt = load_provider_attempt(attempt_key=self.attempt_key(episode))
        if attempt is None:
            raise RuntimeError("onchain hazard attempt disappeared after idempotent begin")
        return OnchainMintHazardCaptureResult(attempt, evidence_from_attempt(attempt), True)

    def _complete(
        self,
        episode: MarketOpportunityEpisode,
        *,
        started_at: int,
        status: str,
        evidence: OnchainMintHazardEvidence | None = None,
        error: BaseException | None = None,
        details: dict | None = None,
    ) -> OpportunityProviderAttempt:
        observed_floor = evidence.observed_at if evidence is not None else None
        completed_at = max(started_at, int(time.time()), int(observed_floor or started_at))
        return complete_provider_attempt(
            attempt_key=self.attempt_key(episode),
            status=status,
            completed_at=completed_at,
            error_type=(type(error).__name__ if error is not None else None),
            error_message=(str(error) if error is not None else None),
            details=(_details(evidence) if evidence is not None else (details or {})),
        )

    def capture(self, episode: MarketOpportunityEpisode) -> OnchainMintHazardCaptureResult:
        if not episode.episode_key.strip() or not episode.token_mint.strip():
            raise ValueError("episode identity is incomplete")
        started_at = max(int(time.time()), int(episode.first_trigger_observed_at))
        is_new = begin_provider_attempt(
            attempt_key=self.attempt_key(episode),
            acquisition_run_key=episode.acquisition_run_key,
            episode_key=episode.episode_key,
            provider=ONCHAIN_HAZARD_PROVIDER,
            purpose=ONCHAIN_HAZARD_PURPOSE,
            started_at=started_at,
        )
        if not is_new:
            return self._existing(episode)

        client = SolanaClient(timeout=self.rpc_timeout_seconds)
        try:
            result = client.call(
                "getAccountInfo",
                [episode.token_mint, {"encoding": "jsonParsed", "commitment": "confirmed"}],
                max_attempts=1,
            )
        except SolanaRPCError as exc:
            attempt = self._complete(
                episode,
                started_at=started_at,
                status="PROVIDER_ERROR",
                error=exc,
                details={"token_mint": episode.token_mint},
            )
            return OnchainMintHazardCaptureResult(attempt, evidence_from_attempt(attempt), False)

        observed_at = max(started_at, int(time.time()))
        try:
            evidence = _normalize_account_info(
                episode=episode,
                result=result,
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
            return OnchainMintHazardCaptureResult(attempt, evidence_from_attempt(attempt), False)

        attempt = self._complete(
            episode,
            started_at=started_at,
            status=evidence.status,
            evidence=evidence,
        )
        return OnchainMintHazardCaptureResult(attempt, evidence_from_attempt(attempt), False)
