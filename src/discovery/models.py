from dataclasses import dataclass, field


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
    signals: "CandidateSignals | None" = None
    source: str = "birdeye"


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
    signals: "CandidateSignals | None" = None
    source: str = "birdeye"


@dataclass(frozen=True)
class DiscoveryReport:
    source_count: int
    prefiltered_count: int
    enriched_30d_count: int
    fully_evaluated_count: int
    candidates: tuple[CandidateResult, ...]
    rejected_by_reason: dict[str, int]
    data_errors: dict[str, str]
    rejected_count: int = 0
    copyability_evaluated_count: int = 0
    copyability_results: tuple["CopyabilityResult", ...] = ()
    copyability_rejected_by_reason: dict[str, int] = field(default_factory=dict)

    @property
    def passed_count(self) -> int:
        return len(self.candidates)

    @property
    def eliminated_count(self) -> int:
        return self.rejected_count

    @property
    def copyable_candidates(self) -> tuple["CopyabilityResult", ...]:
        return tuple(item for item in self.copyability_results if item.passed)

    @property
    def copyable_count(self) -> int:
        return len(self.copyable_candidates)


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
    buys: int
    sells: int
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
class LiquidMarket:
    """A current Solana token market used only to seed wallet discovery."""

    token: str
    symbol: str | None
    liquidity_usd: float
    volume_usd_24h: float
    pool_address: str | None


@dataclass(frozen=True)
class TokenTraderSeed:
    """A public wallet observed trading one liquid-market token."""

    address: str
    token: str


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


@dataclass(frozen=True)
class CandidateSignals:
    """Derived only from documented source fields and daily wallet history."""

    trading_days_30d: int
    profitable_days_30d: int
    losing_days_30d: int
    median_daily_pnl_usd: float
    top_positive_day_share_pct: float
    realized_drawdown_usd: float
    realized_drawdown_pct: float
    avg_hold_seconds: float | None
    last_trade_age_days: float
    single_token_profit_cap_pct: float
    arbitrage_excluded: bool
    strict_pnl_mode: bool


@dataclass(frozen=True)
class TokenPosition:
    """One documented Solana Tracker wallet position used for marketability checks."""

    token: str
    symbol: str | None
    realized_pnl_usd: float
    invested_usd: float
    roi_pct: float
    trades: int
    average_buy_usd: float | None
    hold_time_seconds: float | None
    last_trade_ms: int | None
    liquidity_usd: float | None
    market_cap_usd: float | None
    primary_market: str | None


@dataclass(frozen=True)
class WalletPositions:
    """Recent token positions returned by the read-only PnL V2 endpoint."""

    address: str
    positions: tuple[TokenPosition, ...]
    total_available: int
    pnl_mode: str


@dataclass(frozen=True)
class CopyabilityMetrics:
    """Observed inputs for the separate, non-financial Copyability Score."""

    sampled_positions: int
    known_liquidity_positions: int
    liquid_positions: int
    sampled_invested_usd: float
    liquid_invested_usd: float
    liquidity_coverage_pct: float
    liquid_position_share_pct: float
    liquid_capital_share_pct: float
    median_liquidity_usd: float
    median_entry_liquidity_ratio_pct: float | None
    trades_per_day_30d: float
    average_hold_seconds: float | None


@dataclass(frozen=True)
class CopyabilityResult:
    """Marketability assessment kept separate from wallet quality."""

    candidate: CandidateResult
    copyability_score: float
    passed: bool
    metrics: CopyabilityMetrics
    reasons: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    score_components: dict[str, float]
