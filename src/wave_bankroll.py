from dataclasses import dataclass

from src.database import rows


@dataclass(frozen=True)
class WaveTradeReturn:
    detected_at: int
    symbol: str
    return_pct: float


@dataclass(frozen=True)
class BankrollPoint:
    trade_number: int
    detected_at: int
    symbol: str
    return_pct: float
    stake_usd: float
    pnl_usd: float
    balance_usd: float
    drawdown_usd: float
    drawdown_pct: float


@dataclass(frozen=True)
class BankrollSimulation:
    starting_balance_usd: float
    allocation_pct: float
    final_balance_usd: float
    total_profit_usd: float
    total_return_pct: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    max_losing_streak: int
    points: tuple[BankrollPoint, ...]


def completed_wave_returns(
    strategy_version: str,
    horizon_minutes: int,
) -> tuple[WaveTradeReturn, ...]:
    observations = rows(
        """SELECT s.detected_at, COALESCE(s.symbol, s.name, s.token_mint) AS symbol,
        c.return_pct
        FROM wave_signal_checks c
        JOIN wave_signals s ON s.id=c.signal_id
        WHERE s.strategy_version=? AND c.horizon_minutes=?
        AND c.status='completed'
        ORDER BY s.detected_at, c.id""",
        (strategy_version, horizon_minutes),
    )
    return tuple(
        WaveTradeReturn(
            detected_at=int(item["detected_at"]),
            symbol=str(item["symbol"]),
            return_pct=float(item["return_pct"]),
        )
        for item in observations
    )


def simulate_bankroll(
    observations: tuple[WaveTradeReturn, ...] | list[WaveTradeReturn],
    *,
    starting_balance_usd: float,
    allocation_pct: float,
) -> BankrollSimulation:
    if starting_balance_usd <= 0:
        raise ValueError("A banca inicial deve ser positiva.")
    if allocation_pct <= 0 or allocation_pct > 100:
        raise ValueError("A alocação deve estar entre 0% e 100%.")

    balance = peak = float(starting_balance_usd)
    max_drawdown_usd = max_drawdown_pct = 0.0
    losing_streak = max_losing_streak = 0
    points = []
    allocation_fraction = allocation_pct / 100

    for trade_number, observation in enumerate(observations, start=1):
        stake = balance * allocation_fraction
        pnl = stake * observation.return_pct / 100
        balance += pnl
        peak = max(peak, balance)
        drawdown_usd = peak - balance
        drawdown_pct = drawdown_usd / peak * 100 if peak > 0 else 0.0
        max_drawdown_usd = max(max_drawdown_usd, drawdown_usd)
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

        if observation.return_pct < 0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
        else:
            losing_streak = 0

        points.append(
            BankrollPoint(
                trade_number=trade_number,
                detected_at=observation.detected_at,
                symbol=observation.symbol,
                return_pct=observation.return_pct,
                stake_usd=stake,
                pnl_usd=pnl,
                balance_usd=balance,
                drawdown_usd=drawdown_usd,
                drawdown_pct=drawdown_pct,
            )
        )

    total_profit = balance - starting_balance_usd
    return BankrollSimulation(
        starting_balance_usd=starting_balance_usd,
        allocation_pct=allocation_pct,
        final_balance_usd=balance,
        total_profit_usd=total_profit,
        total_return_pct=total_profit / starting_balance_usd * 100,
        max_drawdown_usd=max_drawdown_usd,
        max_drawdown_pct=max_drawdown_pct,
        max_losing_streak=max_losing_streak,
        points=tuple(points),
    )
