import math

import pandas as pd

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

