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
