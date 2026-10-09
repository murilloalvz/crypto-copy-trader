from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from src.discovery.models import TraderSnapshot


@dataclass(frozen=True)
class WalletResearchPolicy:
    """Broad research gates. These do not authorize copy trading."""

    min_realized_pnl_usd: float = 0.0
    min_roi_pct: float = 0.0
    min_invested_usd: float = 500.0
    min_win_rate_pct: float = 40.0
    min_closed_tokens: int = 5
    min_tokens_traded: int = 3
    min_trading_days: int = 3
    max_inactive_days: float = 7.0
    require_strict_pnl: bool = True


@dataclass(frozen=True)
class WalletResearchEntry:
    snapshot: TraderSnapshot
    frequency_bucket: str
    last_trade_age_days: float | None
    flags: tuple[str, ...]


@dataclass(frozen=True)
class WalletResearchUniverse:
    source_count: int
    eligible_count: int
    rejected_by_reason: dict[str, int]
    frequency_counts: dict[str, int]
    shortlist: tuple[WalletResearchEntry, ...]


RESEARCH_REJECTION_LABELS = {
    "pnl_non_positive": "PnL realizado 30d não positivo",
    "roi_non_positive": "ROI realizado 30d não positivo",
    "invested_below_minimum": "menos de US$ 500 investidos em 30d",
    "win_rate_below_research_floor": "win rate abaixo de 40%",
    "too_few_closed_tokens": "menos de 5 tokens fechados",
    "too_few_tokens": "menos de 3 tokens negociados",
    "too_few_trading_days": "menos de 3 dias ativos em 30d",
    "last_trade_unavailable": "data do último trade indisponível",
    "last_trade_too_old": "último trade há mais de 7 dias",
    "pnl_mode_not_strict": "PnL da fonte não está em modo estrito",
}


FREQUENCY_LABELS = {
    "moderate": "20–300 trades/30d",
    "active": "301–1000 trades/30d",
    "high_frequency": "1001–3000 trades/30d",
    "ultra_high_frequency": ">3000 trades/30d",
}


def frequency_bucket(trades: int) -> str:
    if trades <= 300:
        return "moderate"
    if trades <= 1_000:
        return "active"
    if trades <= 3_000:
        return "high_frequency"
    return "ultra_high_frequency"


def _last_trade_age_days(snapshot: TraderSnapshot, now_ms: int) -> float | None:
    if snapshot.last_trade_ms is None:
        return None
    return max(0, now_ms - snapshot.last_trade_ms) / 86_400_000


def research_rejection_reasons(
    snapshot: TraderSnapshot,
    *,
    now_ms: int,
    policy: WalletResearchPolicy | None = None,
) -> tuple[str, ...]:
    policy = policy or WalletResearchPolicy()
    reasons = []
    if snapshot.realized_pnl_usd <= policy.min_realized_pnl_usd:
        reasons.append("pnl_non_positive")
    if snapshot.roi_pct <= policy.min_roi_pct:
        reasons.append("roi_non_positive")
    if snapshot.invested_usd < policy.min_invested_usd:
        reasons.append("invested_below_minimum")
    if snapshot.win_rate_pct < policy.min_win_rate_pct:
        reasons.append("win_rate_below_research_floor")
    if snapshot.closed_tokens < policy.min_closed_tokens:
        reasons.append("too_few_closed_tokens")
    if snapshot.tokens_traded < policy.min_tokens_traded:
        reasons.append("too_few_tokens")
    if snapshot.trading_days < policy.min_trading_days:
        reasons.append("too_few_trading_days")
    age = _last_trade_age_days(snapshot, now_ms)
    if age is None:
        reasons.append("last_trade_unavailable")
    elif age > policy.max_inactive_days:
        reasons.append("last_trade_too_old")
    if policy.require_strict_pnl and snapshot.pnl_mode != "strict":
        reasons.append("pnl_mode_not_strict")
    return tuple(reasons)


def _research_flags(snapshot: TraderSnapshot) -> tuple[str, ...]:
    flags = []
    bucket = frequency_bucket(snapshot.trades)
    if bucket in {"high_frequency", "ultra_high_frequency"}:
        flags.append("high_frequency_not_directly_copyable")
    if snapshot.realized_pnl_usd > 0:
        day_share = 100 * max(snapshot.max_single_day_pnl_usd, 0) / snapshot.realized_pnl_usd
        if day_share > 40:
            flags.append("pnl_concentrated_in_best_day_proxy")
    return tuple(flags)


def _priority_key(entry: WalletResearchEntry) -> tuple:
    snapshot = entry.snapshot
    return (
        -snapshot.win_rate_pct,
        -snapshot.roi_pct,
        -snapshot.realized_pnl_usd,
        snapshot.address,
    )


def select_research_universe(
    snapshots: list[TraderSnapshot] | tuple[TraderSnapshot, ...],
    *,
    shortlist_limit: int = 12,
    now: datetime | None = None,
    policy: WalletResearchPolicy | None = None,
) -> WalletResearchUniverse:
    """Create a diverse strategy-research shortlist without copyability filtering.

    High-frequency wallets are intentionally retained as research archetypes. The
    shortlist is round-robin across frequency buckets so one execution style does
    not dominate the analysis simply because it is common on the leaderboard.
    """

    if not 1 <= shortlist_limit <= 100:
        raise ValueError("shortlist_limit precisa ficar entre 1 e 100")
    policy = policy or WalletResearchPolicy()
    now = now or datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    rejected = Counter()
    buckets: dict[str, list[WalletResearchEntry]] = {
        "moderate": [],
        "active": [],
        "high_frequency": [],
        "ultra_high_frequency": [],
    }
    seen = set()
    eligible = 0
    for snapshot in snapshots:
        if snapshot.address in seen:
            continue
        seen.add(snapshot.address)
        reasons = research_rejection_reasons(snapshot, now_ms=now_ms, policy=policy)
        if reasons:
            rejected.update(reasons)
            continue
        eligible += 1
        bucket = frequency_bucket(snapshot.trades)
        buckets[bucket].append(
            WalletResearchEntry(
                snapshot=snapshot,
                frequency_bucket=bucket,
                last_trade_age_days=_last_trade_age_days(snapshot, now_ms),
                flags=_research_flags(snapshot),
            )
        )

    for entries in buckets.values():
        entries.sort(key=_priority_key)

    shortlist: list[WalletResearchEntry] = []
    order = ("moderate", "active", "high_frequency", "ultra_high_frequency")
    index = 0
    while len(shortlist) < shortlist_limit:
        added = False
        for bucket in order:
            entries = buckets[bucket]
            if index < len(entries):
                shortlist.append(entries[index])
                added = True
                if len(shortlist) == shortlist_limit:
                    break
        if not added:
            break
        index += 1

    return WalletResearchUniverse(
        source_count=len(seen),
        eligible_count=eligible,
        rejected_by_reason=dict(sorted(rejected.items())),
        frequency_counts={key: len(value) for key, value in buckets.items()},
        shortlist=tuple(shortlist),
    )
