from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from statistics import median

from src.discovery.models import (
    CandidateInput,
    CandidateSignals,
    DiscoveryReport,
    LeaderboardWallet,
    TraderSnapshot,
    WalletHistory,
    WalletPeriodMetrics,
)
from src.discovery.ranking import (
    CandidatePolicy,
    filter_candidate_signals,
    filter_recent,
    filter_tracker_snapshot,
    rank_candidates,
)
from src.discovery.solana_tracker import SolanaTrackerClient, SolanaTrackerError

ProgressCallback = Callable[[str, int, int, str], None]


def _window(history: WalletHistory, end_date: date, days: int) -> list:
    start = end_date - timedelta(days=days - 1)
    selected = []
    for item in history.days:
        try:
            item_date = date.fromisoformat(item.date)
        except ValueError:
            continue
        if start <= item_date <= end_date:
            selected.append(item)
    return selected


def _history_metrics(history: WalletHistory, end_date: date, days: int) -> WalletPeriodMetrics:
    activities = _window(history, end_date, days)
    buys = sum(item.buys for item in activities)
    sells = sum(item.sells for item in activities)
    trades = buys + sells
    invested = sum(item.invested_usd for item in activities)
    volume = sum(item.volume_usd for item in activities)
    pnl = sum(item.realized_pnl_usd for item in activities)
    wins = sum(item.realized_pnl_usd > 0 for item in activities if item.trades)
    losses = sum(item.realized_pnl_usd < 0 for item in activities if item.trades)
    outcomes = wins + losses
    return WalletPeriodMetrics(
        period=f"{days}d",
        unique_tokens=0,
        total_buy=buys,
        total_sell=sells,
        total_trade=trades,
        total_win=wins,
        total_loss=losses,
        win_rate_pct=100 * wins / outcomes if outcomes else 0,
        total_invested_usd=invested,
        total_sold_usd=volume - invested,
        current_value_usd=None,
        realized_pnl_usd=pnl,
        roi_pct=100 * pnl / invested if invested > 0 else 0,
        unrealized_pnl_usd=0,
        total_pnl_usd=pnl,
        avg_profit_per_trade_usd=pnl / trades if trades else 0,
    )


def _snapshot_metrics(snapshot: TraderSnapshot) -> WalletPeriodMetrics:
    return WalletPeriodMetrics(
        period="30d",
        unique_tokens=snapshot.tokens_traded,
        total_buy=snapshot.buys,
        total_sell=snapshot.sells,
        total_trade=snapshot.trades,
        total_win=snapshot.profitable_tokens,
        total_loss=snapshot.losing_tokens,
        win_rate_pct=snapshot.win_rate_pct,
        total_invested_usd=snapshot.invested_usd,
        total_sold_usd=snapshot.proceeds_usd,
        current_value_usd=None,
        realized_pnl_usd=snapshot.realized_pnl_usd,
        roi_pct=snapshot.roi_pct,
        unrealized_pnl_usd=0,
        total_pnl_usd=snapshot.realized_pnl_usd,
        avg_profit_per_trade_usd=(
            snapshot.realized_pnl_usd / snapshot.trades if snapshot.trades else 0
        ),
    )


def _risk_signals(
    snapshot: TraderSnapshot,
    history: WalletHistory,
    end_date: date,
    now_ms: int,
) -> CandidateSignals:
    activities = [item for item in _window(history, end_date, 30) if item.trades]
    daily_pnl = [item.realized_pnl_usd for item in activities]
    positive_total = sum(max(value, 0) for value in daily_pnl)
    top_positive_share = (
        100 * max((value for value in daily_pnl if value > 0), default=0) / positive_total
        if positive_total > 0
        else 0
    )
    curve = peak = max_drawdown = 0.0
    for value in daily_pnl:
        curve += value
        peak = max(peak, curve)
        max_drawdown = max(max_drawdown, peak - curve)
    drawdown_pct = (
        100 * max_drawdown / snapshot.invested_usd if snapshot.invested_usd > 0 else 0
    )
    hold_samples = [
        (item.avg_hold_seconds, item.trades)
        for item in activities
        if item.avg_hold_seconds is not None and item.trades > 0
    ]
    hold_weight = sum(weight for _, weight in hold_samples)
    avg_hold_seconds = (
        sum(value * weight for value, weight in hold_samples) / hold_weight
        if hold_weight
        else None
    )
    return CandidateSignals(
        trading_days_30d=snapshot.trading_days,
        profitable_days_30d=snapshot.profitable_days,
        losing_days_30d=snapshot.losing_days,
        median_daily_pnl_usd=median(daily_pnl) if daily_pnl else 0,
        top_positive_day_share_pct=top_positive_share,
        realized_drawdown_usd=max_drawdown,
        realized_drawdown_pct=drawdown_pct,
        avg_hold_seconds=avg_hold_seconds,
        last_trade_age_days=(
            max(0, now_ms - snapshot.last_trade_ms) / 86_400_000
            if snapshot.last_trade_ms is not None
            else float("inf")
        ),
        single_token_profit_cap_pct=50,
        arbitrage_excluded=True,
        strict_pnl_mode=snapshot.pnl_mode == "strict",
    )


class SolanaTrackerDiscoveryService:
    """Primary discovery funnel. It never writes to the tracker database."""

    def __init__(
        self,
        client: SolanaTrackerClient | None = None,
        policy: CandidatePolicy | None = None,
        progress: ProgressCallback | None = None,
        now: datetime | None = None,
    ):
        self.client = client or SolanaTrackerClient()
        self.policy = policy or CandidatePolicy()
        self.progress = progress
        self.now = now or datetime.now(timezone.utc)

    def _notify(self, stage: str, current: int, total: int, address: str) -> None:
        if self.progress:
            self.progress(stage, current, total, address)

    def _source_wallets(self, source_limit: int) -> list[TraderSnapshot]:
        """Mix performance, consistency and lower-frequency leaderboard views."""
        views = (
            ("realized", "desc"),
            ("roi", "desc"),
            ("win_percentage", "desc"),
            ("days", "desc"),
            ("trades", "asc"),
        )
        pools = [
            self.client.top_traders(
                source_limit,
                sort_by=sort_by,
                direction=direction,
                days=30,
                min_trades=self.policy.min_trades_30d,
                min_win_rate=self.policy.min_win_rate_pct,
                min_roi=0,
                min_closed_tokens=self.policy.min_realized_outcomes,
                max_single_token_pct=self.policy.max_single_token_profit_pct,
                min_invested_usd=self.policy.min_invested_usd_30d,
                min_trading_days=self.policy.min_trading_days_30d,
            )
            for sort_by, direction in views
        ]
        selected = []
        seen = set()
        index = 0
        while len(selected) < source_limit and any(index < len(pool) for pool in pools):
            for pool in pools:
                if index >= len(pool):
                    continue
                snapshot = pool[index]
                if snapshot.address not in seen:
                    seen.add(snapshot.address)
                    selected.append(snapshot)
                    if len(selected) == source_limit:
                        break
            index += 1
        return selected

    def discover(self, source_limit: int = 250) -> DiscoveryReport:
        snapshots = self._source_wallets(source_limit)
        now_ms = int(self.now.timestamp() * 1000)
        rejected = Counter()
        rejected_addresses: set[str] = set()
        prefiltered = []
        for rank, snapshot in enumerate(snapshots, start=1):
            reasons = filter_tracker_snapshot(
                snapshot, self.policy, now_ms=now_ms
            )
            if reasons:
                rejected.update(reasons)
                rejected_addresses.add(snapshot.address)
            else:
                prefiltered.append((rank, snapshot))

        inputs = []
        data_errors: dict[str, str] = {}
        evaluated_histories = 0
        for current, (rank, snapshot) in enumerate(prefiltered, start=1):
            self._notify("history", current, len(prefiltered), snapshot.address)
            try:
                history = self.client.wallet_history(snapshot.address, "90d")
            except SolanaTrackerError as exc:
                data_errors[snapshot.address] = str(exc)
                continue
            evaluated_histories += 1
            metrics_7d = _history_metrics(history, self.now.date(), 7)
            recent_reasons = filter_recent(metrics_7d, self.policy)
            if recent_reasons:
                rejected.update(recent_reasons)
                rejected_addresses.add(snapshot.address)
                continue
            signals = _risk_signals(snapshot, history, self.now.date(), now_ms)
            signal_reasons = filter_candidate_signals(
                signals.avg_hold_seconds, self.policy
            )
            if signal_reasons:
                rejected.update(signal_reasons)
                rejected_addresses.add(snapshot.address)
                continue
            inputs.append(
                CandidateInput(
                    address=snapshot.address,
                    source_rank=rank,
                    leaderboard=LeaderboardWallet(
                        address=snapshot.address,
                        pnl_usd=snapshot.realized_pnl_usd,
                        volume_usd=snapshot.volume_usd,
                        trade_count=snapshot.trades,
                    ),
                    metrics_30d=_snapshot_metrics(snapshot),
                    metrics_7d=metrics_7d,
                    metrics_90d=_history_metrics(history, self.now.date(), 90),
                    signals=signals,
                )
            )

        ranked = rank_candidates(inputs)
        return DiscoveryReport(
            source_count=len(snapshots),
            prefiltered_count=len(prefiltered),
            enriched_30d_count=len(inputs),
            fully_evaluated_count=evaluated_histories,
            candidates=tuple(ranked),
            rejected_by_reason=dict(sorted(rejected.items())),
            data_errors=data_errors,
            rejected_count=len(rejected_addresses),
        )
