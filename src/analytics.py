import math

import pandas as pd

from src.config import settings
from src.database import rows


def wallet_metrics(address: str) -> dict:
    data = rows(
        "SELECT * FROM transactions WHERE wallet_address=? AND status='success' ORDER BY block_time",
        (address,),
    )
    if not data:
        return {"transactions": 0, "swaps": 0, "active_days": 0, "frequency": 0.0, "score": 0.0}
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["block_time"], unit="s", utc=True).dt.date
    swaps = df[df["kind"] == "swap"]
    active_days = max(df["date"].nunique(), 1)
    frequency = len(swaps) / active_days
    activity_score = min(len(swaps) / 30, 1) * 35
    diversity_score = min(swaps["token_mint"].nunique() / 10, 1) * 20 if not swaps.empty else 0
    success_score = min(len(df) / 50, 1) * 25
    regularity_score = min(math.log1p(frequency) / math.log(6), 1) * 20
    return {
        "transactions": len(df),
        "swaps": len(swaps),
        "active_days": active_days,
        "frequency": frequency,
        "score": round(activity_score + diversity_score + success_score + regularity_score, 1),
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
        "curve": curve,
    }
