from dataclasses import dataclass


@dataclass(frozen=True)
class LeaderboardWallet:
    """Cheap first-stage metrics returned by Birdeye's trader leaderboard."""

    address: str
    pnl_usd: float
    volume_usd: float
    trade_count: int


@dataclass(frozen=True)
class WalletPeriodMetrics:
    """Wallet PnL summary for one explicit analysis window."""

    period: str
    unique_tokens: int
    total_buy: int
    total_sell: int
    total_trade: int
    total_win: int
    total_loss: int
    win_rate_pct: float
    total_invested_usd: float
    total_sold_usd: float
    current_value_usd: float | None
    realized_pnl_usd: float
    roi_pct: float
    unrealized_pnl_usd: float
    total_pnl_usd: float
    avg_profit_per_trade_usd: float

    @property
    def realized_outcomes(self) -> int:
        return self.total_win + self.total_loss


@dataclass(frozen=True)
class CandidateInput:
    """Fully enriched wallet ready for deterministic filters and ranking."""

    address: str
    source_rank: int
    leaderboard: LeaderboardWallet
    metrics_30d: WalletPeriodMetrics
    metrics_7d: WalletPeriodMetrics
    metrics_90d: WalletPeriodMetrics | None


@dataclass(frozen=True)
class CandidateResult:
    """A discovery result; this is not a recommendation to copy the wallet."""

    address: str
    candidate_score: float
    metrics_30d: WalletPeriodMetrics
    metrics_7d: WalletPeriodMetrics
    metrics_90d: WalletPeriodMetrics | None
    reasons: tuple[str, ...]
    penalties: tuple[str, ...]
    score_components: dict[str, float]


@dataclass(frozen=True)
class DiscoveryReport:
    source_count: int
    prefiltered_count: int
    enriched_30d_count: int
    fully_evaluated_count: int
    candidates: tuple[CandidateResult, ...]
    rejected_by_reason: dict[str, int]
    data_errors: dict[str, str]

    @property
    def passed_count(self) -> int:
        return len(self.candidates)

    @property
    def eliminated_count(self) -> int:
        return self.source_count - self.passed_count


@dataclass(frozen=True)
class TraderSnapshot:
    """Documented PnL V2 leaderboard fields from Solana Tracker."""

    address: str
    realized_pnl_usd: float
    volume_usd: float
    trading_days: int
    profitable_days: int
    losing_days: int
    max_single_day_pnl_usd: float
    roi_pct: float
    invested_usd: float
    proceeds_usd: float
    trades: int
    tokens_traded: int
    profitable_tokens: int
    losing_tokens: int
    closed_tokens: int
    win_rate_pct: float
    first_trade_ms: int | None
    last_trade_ms: int | None
    pnl_mode: str


@dataclass(frozen=True)
class DailyWalletActivity:
    date: str
    realized_pnl_usd: float
    buys: int
    sells: int
    invested_usd: float
    volume_usd: float
    avg_hold_seconds: float | None

    @property
    def trades(self) -> int:
        return self.buys + self.sells


@dataclass(frozen=True)
class WalletHistory:
    address: str
    days: tuple[DailyWalletActivity, ...]
