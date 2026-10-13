"""Resumo diario (Telegram): por etiqueta e chain, enviados x nao enviados x cortados e resultado liquido.

Mostra enviados e NAO enviados lado a lado de proposito: e essa comparacao que diz se o score
separa bons de ruins (a v0 existe para medir isso, nao para provar edge).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional, Sequence

from .util import fmt_age


def local_day_bounds(now: float) -> tuple[float, float]:
    """[meia-noite local, proxima meia-noite local) do dia de `now`, em epoch."""
    local = datetime.fromtimestamp(now).astimezone()
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def _pct(value: float) -> str:
    return f"{value:+.1f}%".replace(".", ",").replace("-", "−")


def percentile(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[index]


def _stats_line(label: str, rows: Sequence[Any]) -> str:
    finalized = [r for r in rows if r["status"] == "finalizado" and r["resultado_liq"] is not None]
    if not finalized:
        return f"  {label} (fin. 0): sem resultado ainda"
    results = [r["resultado_liq"] for r in finalized]
    hit = sum(1 for r in finalized if r["tp1_antes_sl"] == "sim")
    ambiguous = sum(1 for r in finalized if r["tp1_antes_sl"] == "ambiguo")
    extra = f" ({ambiguous} amb.)" if ambiguous else ""
    return (
        f"  {label} (fin. {len(finalized)}): média {_pct(statistics.fmean(results))} | "
        f"mediana {_pct(statistics.median(results))} | TP1>SL {100.0 * hit / len(finalized):.0f}%{extra}"
    )


def build_summary(storage: Any, ts_from: float, ts_to: float, chain_names: dict[str, str], title_date: str) -> str:
    signals = storage.signals_between(ts_from, ts_to)
    discards = storage.discards_between(ts_from, ts_to)
    cut: dict[tuple[str, str], int] = defaultdict(int)
    for row in discards:
        if row["etiqueta"]:
            cut[(row["chain"], row["etiqueta"])] += 1
    groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in signals:
        groups[(row["chain"], row["etiqueta"])].append(row)
    for key in cut:
        groups.setdefault(key, [])

    lines = [f"\U0001f4ca Resumo {title_date} (hora local)"]
    if not groups:
        lines.append("Nenhum token avaliado no período.")
    for (chain, label) in sorted(groups):
        rows = groups[(chain, label)]
        sent = [r for r in rows if r["enviado"] == 1]
        not_sent = [r for r in rows if r["enviado"] != 1]
        lines.append(f"━ {chain_names.get(chain, chain)} · {label}")
        lines.append(f"  enviados {len(sent)} | não enviados {len(not_sent)} | cortados {cut.get((chain, label), 0)}")
        lines.append(_stats_line("enviados", sent))
        lines.append(_stats_line("não enviados", not_sent))

    latencies = [r["latencia_s"] for r in signals if r["enviado"] == 1 and r["latencia_s"] is not None]
    if latencies:
        lines.append(
            f"Latência evento→alerta (enviados, n={len(latencies)}): "
            f"p50 {fmt_age(percentile(latencies, 0.5))} | p95 {fmt_age(percentile(latencies, 0.95))}"
        )
    versions = sorted({r["versao_config"] for r in signals if r["versao_config"]})
    if versions:
        lines.append("Versões de config no dia: " + ", ".join(versions) + (" (mais de uma: não misture na análise)" if len(versions) > 1 else ""))
    pending = sum(1 for r in signals if r["status"] == "acompanhando")
    if pending:
        lines.append(f"Em acompanhamento: {pending} (resultado ainda não fechou)")
    return "\n".join(lines)
