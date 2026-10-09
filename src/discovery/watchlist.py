from dataclasses import dataclass

from src.discovery.models import CopyabilityResult, WalletTier, WatchlistEntry


@dataclass(frozen=True)
class WatchlistPolicy:
    """Conservative rules for monitoring wallets that cannot be copied alone."""

    min_candidate_score: float = 75.0
    min_copyability_score: float = 55.0


OBSERVATION_ONLY_BARRIERS = frozenset(
    {
        "liquid_position_share_low",
        "liquid_capital_share_low",
        "copyability_score_below_minimum",
    }
)


def classify_wallet(
    result: CopyabilityResult,
    policy: WatchlistPolicy | None = None,
) -> WatchlistEntry:
    """Classify a wallet without turning observation into copy authorization."""
    policy = policy or WatchlistPolicy()
    candidate = result.candidate
    barriers = set(result.rejection_reasons)

    if result.passed:
        return WatchlistEntry(
            copyability=result,
            tier=WalletTier.APPROVED,
            reasons=("passou por todas as barreiras de copyability",),
        )

    quality_ok = candidate.candidate_score >= policy.min_candidate_score
    execution_signal_ok = result.copyability_score >= policy.min_copyability_score
    observation_only = bool(barriers) and barriers <= OBSERVATION_ONLY_BARRIERS
    if quality_ok and execution_signal_ok and observation_only:
        return WatchlistEntry(
            copyability=result,
            tier=WalletTier.OBSERVE,
            reasons=(
                "qualidade suficiente para contribuir com sinais coletivos",
                "não pode autorizar cópia individual por barreiras de liquidez",
            ),
        )

    return WatchlistEntry(
        copyability=result,
        tier=WalletTier.REJECTED,
        reasons=("não atingiu os requisitos mínimos da watchlist",),
    )


def build_watchlist(
    results: tuple[CopyabilityResult, ...] | list[CopyabilityResult],
    policy: WatchlistPolicy | None = None,
) -> tuple[WatchlistEntry, ...]:
    entries = [classify_wallet(item, policy) for item in results]
    priority = {
        WalletTier.APPROVED: 0,
        WalletTier.OBSERVE: 1,
        WalletTier.REJECTED: 2,
    }
    return tuple(
        sorted(
            entries,
            key=lambda item: (
                priority[item.tier],
                -item.copyability.copyability_score,
                -item.copyability.candidate.candidate_score,
                item.address,
            ),
        )
    )
