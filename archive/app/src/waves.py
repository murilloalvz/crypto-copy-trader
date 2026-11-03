from collections import defaultdict
from dataclasses import dataclass

from src.discovery.models import WalletTier


@dataclass(frozen=True)
class WalletTradeSignal:
    """One normalized public-wallet trade event; it never represents an order."""

    wallet: str
    token: str
    occurred_at_ms: int
    side: str
    tier: WalletTier
    candidate_score: float
    copyability_score: float
    amount_usd: float | None = None


@dataclass(frozen=True)
class ConvergencePolicy:
    """Minimum independent-wallet agreement before creating a wave candidate."""

    window_seconds: int = 300
    min_unique_wallets: int = 2
    min_signal_weight: float = 1.5
    approved_wallet_weight: float = 1.0
    observed_wallet_weight: float = 0.5


@dataclass(frozen=True)
class WaveCandidate:
    """Wallet-convergence candidate; token risk checks are still required."""

    token: str
    wallet_addresses: tuple[str, ...]
    unique_wallets: int
    approved_wallets: int
    observed_wallets: int
    signal_weight: float
    first_seen_ms: int
    last_seen_ms: int


def _wallet_weight(tier: WalletTier, policy: ConvergencePolicy) -> float:
    if tier == WalletTier.APPROVED:
        return policy.approved_wallet_weight
    if tier == WalletTier.OBSERVE:
        return policy.observed_wallet_weight
    return 0.0


def detect_wallet_convergence(
    events: list[WalletTradeSignal] | tuple[WalletTradeSignal, ...],
    *,
    now_ms: int,
    policy: ConvergencePolicy | None = None,
) -> tuple[WaveCandidate, ...]:
    """Find tokens bought by enough independent monitored wallets in one window.

    This is deliberately not a Wave Score. Liquidity, holder concentration, token
    authorities, price acceleration and route impact must be checked downstream.
    """
    policy = policy or ConvergencePolicy()
    if policy.window_seconds <= 0:
        raise ValueError("window_seconds precisa ser positivo")
    if policy.min_unique_wallets < 2:
        raise ValueError("min_unique_wallets precisa ser pelo menos 2")

    cutoff_ms = now_ms - policy.window_seconds * 1_000
    latest_by_token_wallet: dict[tuple[str, str], WalletTradeSignal] = {}
    for event in events:
        if event.side.lower() != "buy":
            continue
        if event.tier == WalletTier.REJECTED:
            continue
        if not event.wallet or not event.token:
            continue
        if not cutoff_ms <= event.occurred_at_ms <= now_ms:
            continue
        key = (event.token, event.wallet)
        previous = latest_by_token_wallet.get(key)
        if previous is None or event.occurred_at_ms > previous.occurred_at_ms:
            latest_by_token_wallet[key] = event

    grouped: dict[str, list[WalletTradeSignal]] = defaultdict(list)
    for event in latest_by_token_wallet.values():
        grouped[event.token].append(event)

    candidates = []
    for token, token_events in grouped.items():
        unique_wallets = len(token_events)
        signal_weight = sum(_wallet_weight(item.tier, policy) for item in token_events)
        if unique_wallets < policy.min_unique_wallets:
            continue
        if signal_weight < policy.min_signal_weight:
            continue
        candidates.append(
            WaveCandidate(
                token=token,
                wallet_addresses=tuple(sorted(item.wallet for item in token_events)),
                unique_wallets=unique_wallets,
                approved_wallets=sum(
                    item.tier == WalletTier.APPROVED for item in token_events
                ),
                observed_wallets=sum(
                    item.tier == WalletTier.OBSERVE for item in token_events
                ),
                signal_weight=round(signal_weight, 2),
                first_seen_ms=min(item.occurred_at_ms for item in token_events),
                last_seen_ms=max(item.occurred_at_ms for item in token_events),
            )
        )

    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                -item.signal_weight,
                -item.unique_wallets,
                -item.last_seen_ms,
                item.token,
            ),
        )
    )
