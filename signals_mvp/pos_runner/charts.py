"""Graficos anotados do POS-RUNNER (PNG). matplotlib e OPCIONAL: sem ele, `available()` e False e quem chama segue
sem grafico (o alerta nunca deixa de sair por causa do grafico).

Marca: pico do runner, L_bc, queda, caixa (S e R no periodo da caixa), wicks, rompimento, entrada, stop, alvo,
saidas A/B e power candles (amplitude >= power_atr_mult x ATR20).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .candles import Bar, tf_seconds


def available() -> bool:
    try:
        import matplotlib  # noqa: F401
    except Exception:
        return False
    return True


def _fmt_mc(v: float) -> str:
    if v >= 1e6:
        return f"{v / 1e6:.2f}M"
    if v >= 1e3:
        return f"{v / 1e3:.0f}k"
    return f"{v:.0f}"


def _power_flags(bars: list[Bar], period: int, mult: float) -> list[bool]:
    flags = []
    trs: list[float] = []
    for k, b in enumerate(bars):
        prev = bars[k - 1].close if k else b.open
        trs.append(max(b.high - b.low, abs(b.high - prev), abs(b.low - prev)))
        if k >= period:
            atr = sum(trs[k - period:k]) / period
            flags.append(atr > 0 and (b.high - b.low) >= mult * atr and not b.filled)
        else:
            flags.append(False)
    return flags


def plot_setup(
    path: Path,
    bars: list[Bar],
    tf: str,
    title: str,
    subtitle: str = "",
    l_bc: Optional[float] = None,
    entry_event: Any = None,
    events: Iterable[Any] = (),
    trades: Iterable[Any] = (),
    window: Optional[tuple[int, int]] = None,
    power_period: int = 20,
    power_mult: float = 3.0,
    small: bool = False,
) -> Optional[Path]:
    """Desenha e salva. `window` = (indice inicial, indice final) dos candles mostrados."""
    if not available() or not bars:
        return None
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    step = tf_seconds(tf)
    lo_i, hi_i = window if window else (0, len(bars) - 1)
    lo_i, hi_i = max(0, lo_i), min(len(bars) - 1, hi_i)
    view = bars[lo_i:hi_i + 1]
    power = _power_flags(bars, power_period, power_mult)
    width = 0.7
    fig, (ax, axv) = plt.subplots(
        2, 1, figsize=(8, 4.5) if small else (15, 8), sharex=True, gridspec_kw={"height_ratios": [4, 1]}
    )
    for k, b in enumerate(view):
        i = lo_i + k
        color = "#2e9d5b" if b.close >= b.open else "#d0453a"
        if b.filled:
            color = "#bbbbbb"
        ax.plot([i, i], [b.low, b.high], color=color, lw=0.7, zorder=2)
        body_lo, body_hi = min(b.open, b.close), max(b.open, b.close)
        ax.add_patch(Rectangle((i - width / 2, body_lo), width, max(body_hi - body_lo, body_hi * 1e-4), color=color, zorder=3))
        if power[i]:
            ax.add_patch(Rectangle((i - width / 2 - 0.15, b.low), width + 0.3, b.high - b.low, fill=False, ec="#ff9800", lw=1.0, zorder=4))
        axv.bar(i, b.volume, width=width, color=color)
    ax.set_yscale("log")

    def hline(y: float, x0: int, x1: int, color: str, style: str, label: str, lw: float = 1.2) -> None:
        ax.plot([max(x0, lo_i), min(x1, hi_i)], [y, y], color=color, ls=style, lw=lw, zorder=5)
        ax.text(min(x1, hi_i) + 0.5, y, f" {label} {_fmt_mc(y)}", color=color, fontsize=7 if small else 8, va="center", zorder=6)

    if l_bc:
        hline(l_bc, lo_i, hi_i, "#777777", "--", "L_bc")
    if entry_event is not None:
        d = entry_event.data
        e_idx = entry_event.idx
        hline(d["P_peak"], d["peak_idx"], hi_i, "#1b7f3b", ":", "pico")
        hline(d["tp"], e_idx, hi_i, "#1b7f3b", "-", "alvo")
        hline(d["S"], d["box_start"], e_idx, "#1f5fbf", "-", "S", 1.6)
        hline(d["R"], d["box_start"], e_idx, "#1f5fbf", "-", "R", 1.6)
        hline(d["stop"], e_idx, hi_i, "#c62828", "--", "stop")
        ax.axvspan(d["box_start"] - 0.5, d["box_end"] + 0.5, color="#1f5fbf", alpha=0.06, zorder=1)
        pk = d["peak_idx"]
        if lo_i <= pk <= hi_i:
            ax.annotate("pico", (pk, bars[pk].high), xytext=(0, 12), textcoords="offset points", ha="center", fontsize=8,
                        arrowprops=dict(arrowstyle="->", color="#1b7f3b"), color="#1b7f3b")
        for w in d.get("wicks", []):
            if lo_i <= w <= hi_i:
                ax.annotate("w", (w, bars[w].low), xytext=(0, -14), textcoords="offset points", ha="center", fontsize=8,
                            color="#6a1b9a", arrowprops=dict(arrowstyle="->", color="#6a1b9a"))
        ax.annotate("rompimento", (e_idx, bars[e_idx].close), xytext=(-40, 25), textcoords="offset points", fontsize=8,
                    arrowprops=dict(arrowstyle="->", color="black"))
    marks = {"INVALIDADO": ("x", "#c62828"), "ONDA_INVALIDA": ("X", "#c62828"), "ABSURDO": ("D", "#ff9800"),
             "FASE2": ("v", "#555555"), "WATCHLIST": ("o", "#1f5fbf")}
    n_entry = 0
    for ev in events:
        if ev.kind in marks and lo_i <= ev.idx <= hi_i:
            m, c = marks[ev.kind]
            ax.scatter([ev.idx], [bars[ev.idx].low * 0.9], marker=m, color=c, s=25, zorder=7)
        if ev.kind == "ENTRADA":
            n_entry += 1
            if lo_i <= ev.idx <= hi_i:
                ax.annotate(f"#{n_entry}", (ev.idx, bars[ev.idx].high), xytext=(0, 8), textcoords="offset points",
                            ha="center", fontsize=8, fontweight="bold", color="#000000", zorder=9)
    for tr in trades:
        if tr.entry_ts is None or tr.status == "cancelado":
            continue
        ei = tr.entry_idx
        if lo_i <= ei <= hi_i:
            ax.scatter([ei], [tr.entry_price], marker=">", color="black", s=40, zorder=8)
        for leg in tr.legs:
            if lo_i <= leg.idx <= hi_i:
                ax.scatter([leg.idx], [leg.price], marker="x" if tr.variant == "A" else "+", color="#000000", s=50, zorder=8)
                ax.annotate(f"{tr.variant}:{leg.reason}", (leg.idx, leg.price), xytext=(5, -10 if tr.variant == "A" else 8),
                            textcoords="offset points", fontsize=7)
    ticks = list(range(lo_i, hi_i + 1, max(1, (hi_i - lo_i) // 8)))
    axv.set_xticks(ticks)
    axv.set_xticklabels([datetime.fromtimestamp(bars[t].ts, tz=timezone.utc).strftime("%d/%m %H:%M") for t in ticks], fontsize=7)
    ax.set_title(title + (f"\n{subtitle}" if subtitle else ""), fontsize=9 if small else 11)
    ax.grid(True, which="both", alpha=0.25)
    ax.set_ylabel("MC (USD, log)")
    axv.set_ylabel("vol USD")
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=90 if small else 110)
    plt.close(fig)
    _ = step
    return path
