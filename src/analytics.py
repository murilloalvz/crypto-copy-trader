import math

import pandas as pd

from src.config import settings
from src.database import rows

MIN_CLOSED_TRADES_FOR_SCORE = 5


def _bounded(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(value, maximum))


def calculate_wallet_score(swaps: int, frequency: float, performance: dict) -> dict:
    closed = int(performance["closed_trades"])
    if closed < MIN_CLOSED_TRADES_FOR_SCORE:
        return {
            "score": None,
            "score_status": "insufficient_data",
            "score_reason": (
                f"{closed}/{MIN_CLOSED_TRADES_FOR_SCORE} trades fechados para liberar o score"
            ),
            "score_components": {},
        }

    components = {
        "retorno": _bounded(performance["return_pct"] / 20) * 30,
        "win_rate": _bounded(performance["win_rate_pct"] / 70) * 25,
        "risco": _bounded(1 - performance["max_drawdown_pct"] / 30) * 20,
        "amostra": _bounded(closed / 30) * 15,
        "atividade": _bounded(swaps / 30) * 5,
        "frequencia": _bounded(math.log1p(frequency) / math.log(6)) * 5,
    }
    return {
        "score": round(sum(components.values()), 1),
        "score_status": "ready",
        "score_reason": f"Calculado com {closed} trades fechados",
        "score_components": {key: round(value, 1) for key, value in components.items()},
    }


def wallet_metrics(address: str) -> dict:
    data = rows(
        """SELECT * FROM transactions WHERE wallet_address=? AND status='success'
        ORDER BY block_time""",
        (address,),
    )
    performance = paper_performance(address)
    if not data:
        return {
            "transactions": 0,
            "swaps": 0,
            "active_days": 0,
            "frequency": 0.0,
            **calculate_wallet_score(0, 0.0, performance),
        }
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["block_time"], unit="s", utc=True).dt.date
    swaps = df[(df["kind"] == "swap") & df["dex"].notna()]
    active_days = swaps["date"].nunique() if not swaps.empty else 0
    frequency = len(swaps) / active_days if active_days else 0.0
    return {
        "transactions": len(df),
        "swaps": len(swaps),
        "active_days": active_days,
        "frequency": frequency,
        **calculate_wallet_score(len(swaps), frequency, performance),
    }


def paper_performance(address: str) -> dict:
    trades = rows(
        """SELECT id, source_block_time, side, status, simulated_usd,
        market_price_usd, realized_pnl_usd, price_error_code
        FROM paper_trades WHERE wallet_address=?
        ORDER BY COALESCE(source_block_time, 0), id""",
        (address,),
    )
    active = [trade for trade in trades if trade["status"] != "filtered_non_swap"]
    closed = [trade for trade in active if trade["status"] == "closed"]
    wins = [trade for trade in closed if (trade["realized_pnl_usd"] or 0) > 0]
    realized_pnl = sum((trade["realized_pnl_usd"] or 0) for trade in closed)
    equity = settings.starting_balance_usd
    peak = equity
    max_drawdown = 0.0
    curve = []
    for trade in closed:
        equity += trade["realized_pnl_usd"] or 0
        peak = max(peak, equity)
        drawdown = (equity - peak) / peak * 100 if peak else 0
        max_drawdown = min(max_drawdown, drawdown)
        curve.append(
            {
                "timestamp": trade["source_block_time"],
                "equity_usd": equity,
                "drawdown_pct": drawdown,
            }
        )
    market_skip_statuses = {"skipped_illiquid", "skipped_low_volume"}
    permanent_price_statuses = {
        "price_no_pool",
        "price_no_historical_candle",
        "price_distant_historical_candle",
        "price_permanent_error",
        "price_retry_exhausted",
    }
    temporary_price_statuses = {"price_unavailable", "price_retryable"}
    total_signals = len(active)
    priced_signals = sum(trade["market_price_usd"] is not None for trade in active)
    market_skips = sum(trade["status"] in market_skip_statuses for trade in active)
    eligible_signals = total_signals - market_skips
    error_breakdown = {}
    for trade in active:
        if trade["status"] not in permanent_price_statuses | temporary_price_statuses:
            continue
        code = trade.get("price_error_code") or "legacy_unclassified"
        error_breakdown[code] = error_breakdown.get(code, 0) + 1
    return {
        "realized_pnl_usd": realized_pnl,
        "return_pct": realized_pnl / settings.starting_balance_usd * 100,
        "win_rate_pct": len(wins) / len(closed) * 100 if closed else 0.0,
        "max_drawdown_pct": abs(max_drawdown),
        "closed_trades": len(closed),
        "open_trades": sum(trade["status"] == "open" for trade in trades),
        "total_signals": total_signals,
        "priced_signals": priced_signals,
        "eligible_signals": eligible_signals,
        "price_coverage_pct": (
            100 * priced_signals / total_signals if total_signals else 0.0
        ),
        "eligible_price_coverage_pct": (
            100 * priced_signals / eligible_signals if eligible_signals else 0.0
        ),
        "temporary_price_failures": sum(
            trade["status"] in temporary_price_statuses for trade in active
        ),
        "permanent_price_failures": sum(
            trade["status"] in permanent_price_statuses for trade in active
        ),
        "price_failures": sum(
            trade["status"] in permanent_price_statuses | temporary_price_statuses
            for trade in active
        ),
        "price_error_breakdown": error_breakdown,
        "liquidity_skips": market_skips,
        "filtered_trades": sum(trade["status"] == "filtered_non_swap" for trade in trades),
        "curve": curve,
    }
