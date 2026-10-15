"""Linha de base PAREADA: mostra se o padrao agrega algo alem de "comprar token que ja correu".

Para cada setup primario (pool P, tf, entrada na idade a = entrada - graduacao de P, colchete stop -x% / alvo +y%):
sorteia (seed derivada de P e tf) ate K outros runners do MESMO periodo que ja eram runners na idade a (MC >= piso
antes de a) e tem candles para o trade sair; cada um entra no open do 1o candle com idade >= a, com o MESMO
colchete percentual, as mesmas saidas A/B, o mesmo stop de tempo e o mesmo custo. Base do setup = media dos K.
"""

from __future__ import annotations

import json
import random
from typing import Any, Optional

from ..candles import tf_seconds
from ..detector import Event
from ..simulate import simulate
from .pipeline import DEX_OF_LAUNCHPAD, Context, load_bars

K_BASELINE = 5


def runner_by_age(bars: list[Any], grad_ts: int, age_s: float, floor: float, step: int) -> bool:
    lim = grad_ts + age_s
    return any(b.high >= floor for b in bars if b.ts + step <= lim and not b.filled)


def baseline_for_setup(ctx: Context, period: str, pool: str, tf: str, n: int, candidates: list[Any],
                       k: int = K_BASELINE) -> list[dict[str, Any]]:
    trade = ctx.store.db.execute(
        "SELECT info FROM trades WHERE pool=? AND tf=? AND n=? AND variant='A' AND kind='setup'", (pool, tf, n)).fetchone()
    if trade is None:
        return []
    info = json.loads(trade[0])
    if not info.get("entry_ts") or not info.get("entrada") or not info.get("stop") or not info.get("alvo"):
        return []
    me = next(r for r in candidates if r["pool"] == pool)
    age = info["entry_ts"] - me["grad_ts"]
    stop_pct = 1.0 - info["stop"] / info["entrada"]
    tp_pct = info["alvo"] / info["entrada"] - 1.0
    step = tf_seconds(tf)
    rng = random.Random(f"{ctx.plan.seed}:base:{pool}:{tf}:{n}")
    pool_list = [r for r in candidates if r["pool"] != pool]
    rng.shuffle(pool_list)
    sol = ctx.usd("So11111111111111111111111111111111111111112", period)
    sol_at = sol.at if sol else (lambda t: None)
    out = []
    for r in pool_list:
        if len(out) >= k:
            break
        bars = load_bars(ctx, r, tf)
        if not bars or not runner_by_age(bars, r["grad_ts"], age, ctx.params.runner_min_mc, step):
            continue
        target = r["grad_ts"] + age
        j = next((i for i, b in enumerate(bars) if b.ts >= target), None)
        if j is None or j == 0 or j + ctx.params.time_stop_candles >= len(bars):
            continue
        entry = bars[j].open
        ev = Event("ENTRADA", j - 1, bars[j - 1].ts, bars[j].ts, {"stop": entry * (1 - stop_pct), "tp": entry * (1 + tp_pct)})
        st = ctx.store.stage1(r["pool"])
        row = {"pool": r["pool"]}
        for variant in ("A", "B"):
            res = simulate(bars, ev, variant, ctx.params, ctx.costs, DEX_OF_LAUNCHPAD.get(r["launchpad"], "desconhecido"),
                           st[3], sol_at)
            row[variant] = res.net_ret if res.status == "fechado" else None
        out.append(row)
    return out


def run_baselines(ctx: Context, period: str) -> int:
    """Calcula (e grava em `meta`) a base de cada setup primario do periodo. Devolve quantos setups receberam base."""
    runners = [r for r in ctx.store.graduations(period)
               if (st := ctx.store.stage1(r["pool"])) is not None and st[0] == "ok" and st[2] == 1]
    done = 0
    for pool, tf, n, _prim, _ts, _ev in ctx.store.setups(period, primary_only=True):
        key = f"base:{pool}:{tf}:{n}"
        if ctx.store.get(key) is not None:
            done += 1
            continue
        rows = baseline_for_setup(ctx, period, pool, tf, n, runners)
        ctx.store.set(key, json.dumps(rows))
        done += 1
    return done


def baseline_mean(ctx: Context, pool: str, tf: str, n: int, variant: str) -> Optional[float]:
    raw = ctx.store.get(f"base:{pool}:{tf}:{n}")
    if raw is None:
        return None
    vals = [r[variant] for r in json.loads(raw) if r.get(variant) is not None]
    return sum(vals) / len(vals) if vals else None
