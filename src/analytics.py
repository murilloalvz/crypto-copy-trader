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
        realized_pnl_usd FROM paper_trades WHERE wallet_address=?
        ORDER BY COALESCE(source_block_time, 0), id""",
        (address,),
    )
    closed = [trade for trade in trades if trade["status"] == "closed"]
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
    return {
        "realized_pnl_usd": realized_pnl,
        "return_pct": realized_pnl / settings.starting_balance_usd * 100,
        "win_rate_pct": len(wins) / len(closed) * 100 if closed else 0.0,
        "max_drawdown_pct": abs(max_drawdown),
        "closed_trades": len(closed),
        "open_trades": sum(trade["status"] == "open" for trade in trades),
        "price_failures": sum(trade["status"] == "price_unavailable" for trade in trades),
        "filtered_trades": sum(trade["status"] == "filtered_non_swap" for trade in trades),
        "curve": curve,
    }
