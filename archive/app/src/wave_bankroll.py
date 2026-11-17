import heapq
import json
import statistics
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


@dataclass(frozen=True)
class WaveTradeObservation:
    signal_id: int
    detected_at: int
    close_at: int
    observed_at: int | None
    token_mint: str
    symbol: str
    wave_score: float
    return_pct: float
    entry_market_price_usd: float
    entry_execution_price_usd: float
    exit_market_price_usd: float
    exit_execution_price_usd: float
    slippage_bps: int
    liquidity_usd: float | None


@dataclass(frozen=True)
class ConcurrentTradeResult:
    signal_id: int
    detected_at: int
    close_at: int
    symbol: str
    wave_score: float
    return_pct: float
    executed: bool
    stake_usd: float
    pnl_usd: float
    skipped_reason: str | None
    entry_to_liquidity_pct: float | None


@dataclass(frozen=True)
class ConcurrentBankrollPoint:
    timestamp: int
    event: str
    equity_usd: float
    cash_usd: float
    locked_usd: float
    open_positions: int
    exposure_pct: float
    drawdown_usd: float
    drawdown_pct: float


@dataclass(frozen=True)
class ConcurrentBankrollSimulation:
    scenario_name: str
    starting_balance_usd: float
    position_pct: float
    max_exposure_pct: float
    candidate_trade_count: int
    executed_trade_count: int
    skipped_trade_count: int
    wins: int
    win_rate_pct: float
    final_balance_usd: float
    total_profit_usd: float
    total_return_pct: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    max_losing_streak: int
    max_concurrent_positions: int
    max_exposure_usd: float
    max_exposure_reached_pct: float
    average_entry_usd: float
    max_entry_usd: float
    max_entry_to_liquidity_pct: float | None
    missing_liquidity_count: int
    slippage_bps_values: tuple[int, ...]
    trades: tuple[ConcurrentTradeResult, ...]
    evolution: tuple[ConcurrentBankrollPoint, ...]


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


def _snapshot_liquidity(snapshot_json: str) -> float | None:
    try:
        value = json.loads(snapshot_json)["token"].get("liquidity_usd")
        value = float(value)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if value > 0 else None


def completed_wave_observations(
    strategy_version: str,
    horizon_minutes: int,
) -> tuple[WaveTradeObservation, ...]:
    observations = rows(
        """SELECT s.id AS signal_id, s.detected_at, c.target_at AS close_at,
        c.observed_at, s.token_mint,
        COALESCE(s.symbol, s.name, s.token_mint) AS symbol, s.wave_score,
        c.return_pct, s.entry_market_price_usd, s.entry_execution_price_usd,
        c.market_price_usd AS exit_market_price_usd,
        c.execution_price_usd AS exit_execution_price_usd, s.slippage_bps,
        s.snapshot_json
        FROM wave_signal_checks c
        JOIN wave_signals s ON s.id=c.signal_id
        WHERE s.strategy_version=? AND c.horizon_minutes=?
        AND c.status='completed'
        ORDER BY s.detected_at, s.wave_score DESC, s.id""",
        (strategy_version, horizon_minutes),
    )
    return tuple(
        WaveTradeObservation(
            signal_id=int(item["signal_id"]),
            detected_at=int(item["detected_at"]),
            close_at=int(item["close_at"]),
            observed_at=(
                int(item["observed_at"])
                if item.get("observed_at") is not None
                else None
            ),
            token_mint=str(item["token_mint"]),
            symbol=str(item["symbol"]),
            wave_score=float(item["wave_score"]),
            return_pct=float(item["return_pct"]),
            entry_market_price_usd=float(item["entry_market_price_usd"]),
            entry_execution_price_usd=float(item["entry_execution_price_usd"]),
            exit_market_price_usd=float(item["exit_market_price_usd"]),
            exit_execution_price_usd=float(item["exit_execution_price_usd"]),
            slippage_bps=int(item["slippage_bps"]),
            liquidity_usd=_snapshot_liquidity(str(item["snapshot_json"])),
        )
        for item in observations
    )


@dataclass(frozen=True)
class _OpenPosition:
    observation: WaveTradeObservation
    stake_usd: float
    entry_to_liquidity_pct: float | None


def simulate_concurrent_bankroll(
    observations: tuple[WaveTradeObservation, ...] | list[WaveTradeObservation],
    *,
    scenario_name: str,
    starting_balance_usd: float,
    position_pct: float,
    max_exposure_pct: float,
) -> ConcurrentBankrollSimulation:
    if starting_balance_usd <= 0:
        raise ValueError("A banca inicial deve ser positiva.")
    if position_pct <= 0 or position_pct > 100:
        raise ValueError("O tamanho por posição deve estar entre 0% e 100%.")
    if max_exposure_pct <= 0 or max_exposure_pct > 100:
        raise ValueError("A exposição máxima deve estar entre 0% e 100%.")
    if position_pct > max_exposure_pct:
        raise ValueError("O tamanho por posição não pode exceder a exposição máxima.")

    ordered = sorted(
        observations,
        key=lambda item: (item.detected_at, -item.wave_score, item.signal_id),
    )
    entry_groups: dict[int, list[WaveTradeObservation]] = {}
    seen_signal_ids: set[int] = set()
    for observation in ordered:
        if observation.signal_id in seen_signal_ids:
            raise ValueError("Cada sinal deve aparecer apenas uma vez no backtest.")
        seen_signal_ids.add(observation.signal_id)
        if observation.close_at < observation.detected_at:
            raise ValueError("O fechamento não pode ocorrer antes da entrada.")
        if observation.return_pct < -100:
            raise ValueError("Retorno inferior a -100% não é executável em uma posição spot.")
        entry_groups.setdefault(observation.detected_at, []).append(observation)

    cash = float(starting_balance_usd)
    locked = 0.0
    peak = float(starting_balance_usd)
    max_drawdown_usd = max_drawdown_pct = 0.0
    max_exposure_usd = max_exposure_reached_pct = 0.0
    max_concurrent_positions = 0
    losing_streak = max_losing_streak = 0
    open_heap: list[tuple[int, int, _OpenPosition]] = []
    trade_results: dict[int, ConcurrentTradeResult] = {}
    evolution: list[ConcurrentBankrollPoint] = []
    executed_positions: list[_OpenPosition] = []
    epsilon = 1e-9

    def record_point(timestamp: int, event: str) -> None:
        nonlocal peak, max_drawdown_usd, max_drawdown_pct
        equity = cash + locked
        peak = max(peak, equity)
        drawdown_usd = peak - equity
        drawdown_pct = drawdown_usd / peak * 100 if peak > 0 else 0.0
        max_drawdown_usd = max(max_drawdown_usd, drawdown_usd)
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
        evolution.append(
            ConcurrentBankrollPoint(
                timestamp=timestamp,
                event=event,
                equity_usd=equity,
                cash_usd=cash,
                locked_usd=locked,
                open_positions=len(open_heap),
                exposure_pct=locked / equity * 100 if equity > 0 else 0.0,
                drawdown_usd=drawdown_usd,
                drawdown_pct=drawdown_pct,
            )
        )

    def close_due(until: int | None = None) -> None:
        nonlocal cash, locked, losing_streak, max_losing_streak
        while open_heap and (until is None or open_heap[0][0] <= until):
            close_at = open_heap[0][0]
            closing = []
            while open_heap and open_heap[0][0] == close_at:
                _timestamp, _signal_id, position = heapq.heappop(open_heap)
                closing.append(position)
            for position in sorted(
                closing,
                key=lambda item: (
                    -item.observation.wave_score,
                    item.observation.signal_id,
                ),
            ):
                pnl = position.stake_usd * position.observation.return_pct / 100
                locked -= position.stake_usd
                cash += position.stake_usd + pnl
                previous = trade_results[position.observation.signal_id]
                trade_results[position.observation.signal_id] = ConcurrentTradeResult(
                    signal_id=previous.signal_id,
                    detected_at=previous.detected_at,
                    close_at=previous.close_at,
                    symbol=previous.symbol,
                    wave_score=previous.wave_score,
                    return_pct=previous.return_pct,
                    executed=True,
                    stake_usd=previous.stake_usd,
                    pnl_usd=pnl,
                    skipped_reason=None,
                    entry_to_liquidity_pct=previous.entry_to_liquidity_pct,
                )
                if position.observation.return_pct < 0:
                    losing_streak += 1
                    max_losing_streak = max(max_losing_streak, losing_streak)
                else:
                    losing_streak = 0
            if abs(locked) < epsilon:
                locked = 0.0
            record_point(close_at, "CLOSE")

    record_point(ordered[0].detected_at if ordered else 0, "START")
    for detected_at, candidates in sorted(entry_groups.items()):
        close_due(detected_at)
        equity = cash + locked
        target_stake = equity * position_pct / 100
        exposure_limit = equity * max_exposure_pct / 100
        for observation in candidates:
            available_capacity = max(
                0.0,
                min(cash, exposure_limit - locked),
            )
            stake = min(target_stake, available_capacity)
            if stake <= epsilon:
                trade_results[observation.signal_id] = ConcurrentTradeResult(
                    signal_id=observation.signal_id,
                    detected_at=observation.detected_at,
                    close_at=observation.close_at,
                    symbol=observation.symbol,
                    wave_score=observation.wave_score,
                    return_pct=observation.return_pct,
                    executed=False,
                    stake_usd=0.0,
                    pnl_usd=0.0,
                    skipped_reason="capital_exposure_limit",
                    entry_to_liquidity_pct=None,
                )
                continue
            liquidity_ratio = (
                stake / observation.liquidity_usd * 100
                if observation.liquidity_usd
                else None
            )
            position = _OpenPosition(observation, stake, liquidity_ratio)
            cash -= stake
            locked += stake
            heapq.heappush(
                open_heap,
                (observation.close_at, observation.signal_id, position),
            )
            executed_positions.append(position)
            trade_results[observation.signal_id] = ConcurrentTradeResult(
                signal_id=observation.signal_id,
                detected_at=observation.detected_at,
                close_at=observation.close_at,
                symbol=observation.symbol,
                wave_score=observation.wave_score,
                return_pct=observation.return_pct,
                executed=True,
                stake_usd=stake,
                pnl_usd=0.0,
                skipped_reason=None,
                entry_to_liquidity_pct=liquidity_ratio,
            )
        current_equity = cash + locked
        exposure_pct = locked / current_equity * 100 if current_equity > 0 else 0.0
        max_exposure_usd = max(max_exposure_usd, locked)
        max_exposure_reached_pct = max(max_exposure_reached_pct, exposure_pct)
        max_concurrent_positions = max(max_concurrent_positions, len(open_heap))
        record_point(detected_at, "OPEN")

    close_due()
    final_balance = cash + locked
    completed_results = tuple(
        trade_results[item.signal_id]
        for item in ordered
    )
    executed = [item for item in completed_results if item.executed]
    stakes = [item.stake_usd for item in executed]
    liquidity_ratios = [
        item.entry_to_liquidity_pct
        for item in executed
        if item.entry_to_liquidity_pct is not None
    ]
    wins = sum(item.return_pct > 0 for item in executed)
    total_profit = final_balance - starting_balance_usd
    return ConcurrentBankrollSimulation(
        scenario_name=scenario_name,
        starting_balance_usd=starting_balance_usd,
        position_pct=position_pct,
        max_exposure_pct=max_exposure_pct,
        candidate_trade_count=len(ordered),
        executed_trade_count=len(executed),
        skipped_trade_count=len(ordered) - len(executed),
        wins=wins,
        win_rate_pct=wins / len(executed) * 100 if executed else 0.0,
        final_balance_usd=final_balance,
        total_profit_usd=total_profit,
        total_return_pct=total_profit / starting_balance_usd * 100,
        max_drawdown_usd=max_drawdown_usd,
        max_drawdown_pct=max_drawdown_pct,
        max_losing_streak=max_losing_streak,
        max_concurrent_positions=max_concurrent_positions,
        max_exposure_usd=max_exposure_usd,
        max_exposure_reached_pct=max_exposure_reached_pct,
        average_entry_usd=statistics.fmean(stakes) if stakes else 0.0,
        max_entry_usd=max(stakes, default=0.0),
        max_entry_to_liquidity_pct=max(liquidity_ratios, default=None),
        missing_liquidity_count=sum(
            item.entry_to_liquidity_pct is None for item in executed
        ),
        slippage_bps_values=tuple(
            sorted({position.observation.slippage_bps for position in executed_positions})
        ),
        trades=completed_results,
        evolution=tuple(evolution),
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
