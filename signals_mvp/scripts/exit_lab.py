"""PEDIDO 2026-11-03 (Passo 0e, item 3). SOMENTE LEITURA, zero chamada de rede: compara, para os
sinais LIMPOS (mesma exclusao de `analise.condicional`: `contaminado_candle` fora; risco<3% fora do R)
de V1/V2/V3 e para a coorte retrospectiva admitida apos o congelamento do lote 1 (onde o historico ja
esta em `pr_bars`, nunca buscado de novo), 4 saidas alternativas DEFINIDAS AGORA, sem otimizacao
nenhuma -- nunca escolhe a "melhor", nunca altera `pr1_signals`/`pr2_signals`/`pr3_signals`/
`pr_trajetoria`/`pr_baseline`/`pr_retro_resultados`/H1 ou qualquer desfecho confirmatorio.

ESTE SCRIPT E EXPLORATORIO: N pequeno, nenhuma selecao do melhor resultado, nenhuma consequencia
sobre deteccao/entrada/saida/tamanho real (medicao ao lado, igual a todo o resto do pipeline).

As 4 saidas, aplicadas a partir do MESMO candle de entrada (`bars[j0].open`, `j0` = indice do candle
cujo `ts` bate com `pr_trajetoria.t_entrada`) sobre a MESMA serie de `pr_bars` ja em cache:

  (A) a atual -- reexecuta `simulate_v1` com o MESMO `stop`/`TOPO`/`S` gravados no sinal (equivalencia
      byte a byte com o resultado oficial, EXCETO o custo: aqui sol_usd_at e sempre None, mesmo
      fallback conservador que `avaliar_candidatos_retro.py` ja usa -- pode divergir em custo fino do
      `result_net` oficial; serve so para comparar as 4 saidas entre si, nunca substitui o oficial).
  (B) stop no breakeven (preco de entrada) depois que a MAXIMA alcancada desde a entrada sobe >= 1x a
      altura da caixa (R - S) acima da entrada -- so entao o stop sobe, nunca antes (causal).
  (C) sai 100% no 1o FECHAMENTO de candle abaixo do teto da caixa (R) apos a entrada -- decidido no
      fechamento, executado no open do candle seguinte (mesma convencao de TP1/EXIT FULL do V1); o
      stop original ainda tem prioridade intracandle, nunca sobrescrito silenciosamente.
  (D) 30% no 1o toque do topo anterior (TOPO=P_peak, SEM exigir exaustao -- variante deliberadamente
      mais simples que o TP1 oficial, decidida no fechamento desse candle/executada no open do
      seguinte, mesma mecanica) + trailing nos 70% restantes: o stop sobe (nunca desce) para logo
      abaixo de cada "fundo de mini-caixa" (minima local -- `bars[k].low` menor que a vizinha anterior
      E as 2 seguintes, so CONHECIDA 2 candles depois, nunca lookahead) com a MESMA folga
      `stop_below_wick_pct` que a zona oficial ja usa.

Em todas: R-multiplo = `net_ret / risk_frac`, com `risk_frac = (entry - stop_ORIGINAL) / entry` -- O
MESMO risco gravado no sinal oficial, igual para as 4 variantes (nunca redefinido pela saida
alternativa), para R ficar comparavel entre elas. risco<3% exclui o R das 4 (mesma regra de
`RISCO_IRREALISTA_MIN_PCT`), mas o retorno em % continua sempre mostrado.

Coorte retrospectiva: SO o subconjunto "admitido_apos_congelamento" do lote 1 ja congelado
(`pr_retro_candidatos`) -- e o UNICO com candles em `pr_bars` sem precisar de rede (ver docstring de
`avaliar_candidatos_retro.py: _bars_truncados_de_pr_bars`). Reexecuta `DetectorV1` com `ParamsV1`/
`ParamsV2`/`ParamsV3` (PEDIDO 2026-11-03, continuacao -- pendente 5: V3 entrou no MESMO loop, MESMOS
candles truncados, so troca o conjunto de parametros, nunca uma regra nova) sobre esses candles
truncados para reobter os eventos ENTRADA (determinismo: mesma entrada, mesmo candle -> mesmo evento
que `avaliar_candidatos_retro.py`/`avaliar_v3_retro.py` ja persistem/reportam, nunca recalculado com
regra diferente). Candidatos NAO admitidos (sem `pr_bars` cacheado) ficam fora -- mesma limitacao
documentada do Passo 0e para a coorte retro, nunca escondida.

PEDIDO 2026-11-03 (continuacao -- pendente 5, complemento): tambem cobre o REPLAY completo de
`ParamsV3` sobre pools admitidos hoje (`avaliar_v3_retro.py: parte_a_pools_admitidos`, Parte A --
reusa o evento bruto exposto la, `eventos_raw`, nunca duplica o replay) e agrega TUDO (v1/v2/v3 ao
vivo, coorte retro, replay V3) por TOKEN (`resumo_por_token`) -- media de %/R por variante, nunca uma
selecao do melhor.

Uso (na VM):
    python -m signals_mvp.scripts.exit_lab --db dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import dataclasses
import sqlite3
import statistics
from pathlib import Path
from typing import Any, Optional

from ..analise.condicional import RISCO_IRREALISTA_MIN_PCT, _contaminado_candle, _risco_irrealista
from ..config import make_paths
from ..pos_runner.candles import Bar, tf_seconds
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import DetectorV1
from ..pos_runner.params_v1 import ParamsV1, load_params_v1
from ..pos_runner.params_v2 import load_params_v2
from ..pos_runner.params_v3 import load_params_v3
from ..pos_runner.simulate_v1 import simulate_v1
from ..storage import Storage
from .avaliar_v3_retro import _conectar_ro, parte_a_pools_admitidos

AVISO = "exploratorio, nao escolhe saida; N pequeno; sem selecao do melhor"
VARIANTES = ("A_atual", "B_breakeven_1x_caixa", "C_fechamento_1h_sob_teto", "D_30pct_topo_trailing")


@dataclasses.dataclass
class _SyntheticEvent:
    idx: int
    data: dict[str, Any]


@dataclasses.dataclass
class ExitResult:
    status: str                  # fechado | em_aberto
    net_ret: Optional[float] = None
    reason: str = ""
    bars_held: Optional[int] = None


def _leg_cost(costs: CostModel, dex: str, price: float, l_bc: Optional[float]) -> float:
    return costs.leg_pct(dex, price, l_bc, None)


def _net_de_legs(legs: list[tuple[float, float, float]], entry: float, entry_cost_pct: float) -> float:
    c_in = entry_cost_pct / 100.0
    net = sum(frac * (price / entry) * (1.0 - c_in) * (1.0 - cost_pct / 100.0) for frac, price, cost_pct in legs)
    return net - 1.0


def _variante_a(bars: list[Bar], j0: int, stop: float, topo: float, s: float, params: ParamsV1,
                costs: CostModel, dex: str, l_bc: Optional[float]) -> ExitResult:
    if j0 <= 0:
        return ExitResult("em_aberto", reason="sem_candle_anterior")
    ev = _SyntheticEvent(j0 - 1, {"stop": stop, "TOPO": topo, "S": s})
    res = simulate_v1(bars, ev, params, costs, dex, l_bc, lambda _t: None)
    return ExitResult(res.status, res.net_ret, res.reason, res.bars_held)


def _variante_b(bars: list[Bar], j0: int, entry: float, stop0: float, s: Optional[float],
                r: Optional[float], costs: CostModel, dex: str, l_bc: Optional[float]) -> ExitResult:
    entry_cost_pct = _leg_cost(costs, dex, entry, l_bc)
    altura = (r - s) if (r is not None and s is not None) else None
    stop = stop0
    moved = False
    max_high = entry
    j = j0
    while j < len(bars):
        bar = bars[j]
        if bar.low <= stop:
            price = min(bar.open, stop)
            net = _net_de_legs([(1.0, price, _leg_cost(costs, dex, price, l_bc))], entry, entry_cost_pct)
            return ExitResult("fechado", net, "stop" if not moved else "stop_breakeven", j - j0 + 1)
        max_high = max(max_high, bar.high)
        if altura is not None and not moved and max_high - entry >= altura:
            stop, moved = entry, True
        j += 1
    return ExitResult("em_aberto")


def _variante_c(bars: list[Bar], j0: int, entry: float, stop: float, r: Optional[float],
                costs: CostModel, dex: str, l_bc: Optional[float]) -> ExitResult:
    entry_cost_pct = _leg_cost(costs, dex, entry, l_bc)
    j = j0
    while j < len(bars):
        bar = bars[j]
        if bar.low <= stop:
            price = min(bar.open, stop)
            net = _net_de_legs([(1.0, price, _leg_cost(costs, dex, price, l_bc))], entry, entry_cost_pct)
            return ExitResult("fechado", net, "stop", j - j0 + 1)
        if r is not None and bar.close < r:
            if j + 1 >= len(bars):
                return ExitResult("em_aberto", reason="pendente_fechamento_sob_teto")
            price = bars[j + 1].open
            net = _net_de_legs([(1.0, price, _leg_cost(costs, dex, price, l_bc))], entry, entry_cost_pct)
            return ExitResult("fechado", net, "fechamento_1h_abaixo_do_teto", j + 1 - j0 + 1)
        j += 1
    return ExitResult("em_aberto")


def _variante_d(bars: list[Bar], j0: int, entry: float, stop0: float, topo: Optional[float],
                params: ParamsV1, costs: CostModel, dex: str, l_bc: Optional[float]) -> ExitResult:
    entry_cost_pct = _leg_cost(costs, dex, entry, l_bc)
    legs: list[tuple[float, float, float]] = []
    remaining = 1.0
    trail_stop = stop0
    tocou_topo = False
    pending_tp_idx: Optional[int] = None
    j = j0
    while j < len(bars) and remaining > 1e-9:
        bar = bars[j]
        if pending_tp_idx is not None:
            price = bar.open
            legs.append((0.30, price, _leg_cost(costs, dex, price, l_bc)))
            remaining -= 0.30
            pending_tp_idx = None
        if bar.low <= trail_stop:
            price = min(bar.open, trail_stop)
            legs.append((remaining, price, _leg_cost(costs, dex, price, l_bc)))
            motivo = "trailing_mini_caixa" if tocou_topo else "stop"
            net = _net_de_legs(legs, entry, entry_cost_pct)
            return ExitResult("fechado", net, motivo, j - j0 + 1)
        if not tocou_topo and topo is not None and bar.high >= topo:
            if j + 1 >= len(bars):
                break
            pending_tp_idx = j
            tocou_topo = True
        k = j - 2   # candidato a fundo de mini-caixa, confirmado so agora (bars[k+1], bars[k+2]=bar ja fecharam)
        if k >= j0 + 1 and bars[k].low < bars[k - 1].low and bars[k].low < bars[k + 1].low and bars[k].low < bar.low:
            trail_stop = max(trail_stop, bars[k].low * (1.0 - params.stop_below_wick_pct))
        j += 1
    return ExitResult("em_aberto")


def simular_sinal(bars: list[Bar], j0: int, entry: float, stop: float, topo: Optional[float],
                  s: Optional[float], r: Optional[float], params: ParamsV1, costs: CostModel,
                  dex: str, l_bc: Optional[float]) -> dict[str, ExitResult]:
    return {
        "A_atual": _variante_a(bars, j0, stop, topo, s, params, costs, dex, l_bc),
        "B_breakeven_1x_caixa": _variante_b(bars, j0, entry, stop, s, r, costs, dex, l_bc),
        "C_fechamento_1h_sob_teto": _variante_c(bars, j0, entry, stop, r, costs, dex, l_bc),
        "D_30pct_topo_trailing": _variante_d(bars, j0, entry, stop, topo, params, costs, dex, l_bc),
    }


def _bar_idx_por_ts(bars: list[Bar], ts: Optional[float]) -> Optional[int]:
    if ts is None:
        return None
    for idx, bar in enumerate(bars):
        if bar.ts == ts:
            return idx
    return None


def _signals_de(storage: Storage, versao: str) -> list[Any]:
    return {"v1": storage.pr1_signals, "v2": storage.pr2_signals, "v3": storage.pr3_signals}[versao]()


def _params_de(versao: str) -> ParamsV1:
    return {"v1": load_params_v1, "v2": load_params_v2, "v3": load_params_v3}[versao]()


def linhas_v1v2v3(storage: Storage, versao: str) -> tuple[list[dict[str, Any]], int, int]:
    """Devolve (linhas, n_sem_trajetoria_ou_box, n_sem_bar_de_entrada) -- nunca silencioso."""
    params = _params_de(versao)
    costs = CostModel()
    linhas: list[dict[str, Any]] = []
    sem_dado_box = 0
    sem_bar_entrada = 0
    bars_cache: dict[str, list[Bar]] = {}
    for s in _signals_de(storage, versao):
        if s["evento"] != "ENTRADA" or s["status"] != "fechado":
            continue
        if _contaminado_candle(s) or _risco_irrealista(s):
            continue
        if s["stop"] is None or s["topo"] is None or s["entry_price"] is None:
            sem_dado_box += 1
            continue
        traj = storage.pr_trajetoria_get(versao, s["id"])
        if traj is None or traj["t_entrada"] is None:
            sem_dado_box += 1
            continue
        tf = s["tf"] or params.timeframes[0]
        bars = bars_cache.setdefault(f"{s['pool']}|{tf}", [Bar(*row) for row in storage.pr_bars(s["pool"], tf)])
        j0 = _bar_idx_por_ts(bars, traj["t_entrada"])
        if j0 is None:
            sem_bar_entrada += 1
            continue
        pool_row = storage.pr_pool(s["pool"])
        l_bc = pool_row["l_bc"] if pool_row is not None else None
        dex = s["dex"] or "desconhecido"
        resultado = simular_sinal(bars, j0, s["entry_price"], s["stop"], s["topo"], s["s_suporte"],
                                  s["r_resistencia"], params, costs, dex, l_bc)
        risco_pct = traj["risco_pct"]
        risk_frac = (s["entry_price"] - s["stop"]) / s["entry_price"] if s["entry_price"] else None
        linha = {"token": s["symbol"] or (s["mint"] or "")[:8], "versao": versao, "origem": "v1v2v3",
                "risco_pct": risco_pct}
        for nome, r_res in resultado.items():
            pct = (r_res.net_ret * 100.0) if r_res.net_ret is not None else None
            r_mult = (r_res.net_ret / risk_frac) if (r_res.net_ret is not None and risk_frac
                                                     and risco_pct is not None
                                                     and risco_pct >= RISCO_IRREALISTA_MIN_PCT) else None
            linha[nome] = {"status": r_res.status, "pct": pct, "r": r_mult, "motivo": r_res.reason}
        linhas.append(linha)
    return linhas, sem_dado_box, sem_bar_entrada


def _bars_truncados(con: sqlite3.Connection, pool: str, tf: str, step: int, added_ts: float) -> list[Bar]:
    rows = con.execute(
        "SELECT ts, o, h, l, c, v, filled FROM pr_bars WHERE pool=? AND tf=? ORDER BY ts", (pool, tf)
    ).fetchall()
    return [Bar(r[0], r[1], r[2], r[3], r[4], r[5], bool(r[6])) for r in rows if r[0] + step < added_ts]


def linhas_retro_admitido(db_path: Path) -> tuple[list[dict[str, Any]], int]:
    """SO o subconjunto do lote 1 (`pr_retro_candidatos`, ja congelado) marcado `added_ts` em
    `pr_pools` (ganhou vaga de verdade depois do congelamento) -- unico com `pr_bars` cacheado sem
    rede. Reexecuta `DetectorV1`/`ParamsV1`/`ParamsV2` (mesmos parametros congelados) sobre os MESMOS
    candles truncados que `avaliar_candidatos_retro.py` ja usou -- determinismo, nunca uma regra nova."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "pr_retro_candidatos" not in tabelas:
            return [], 0
        candidatos = con.execute("SELECT pool, symbol, launchpad FROM pr_retro_candidatos").fetchall()
        costs = CostModel()
        linhas: list[dict[str, Any]] = []
        n_fora_do_alcance = 0
        for row in candidatos:
            pool_row = con.execute("SELECT added_ts, l_bc, launchpad FROM pr_pools WHERE pool=?", (row["pool"],)).fetchone()
            if pool_row is None or pool_row["added_ts"] is None or pool_row["l_bc"] is None:
                n_fora_do_alcance += 1
                continue
            # PEDIDO 2026-11-03 (continuacao -- pendente 5): V3 entra no MESMO loop da coorte --
            # mesmos candles truncados, so troca o conjunto de parametros (nunca uma regra nova).
            for versao, params in (("v1", load_params_v1()), ("v2", load_params_v2()), ("v3", load_params_v3())):
                tf = params.timeframes[0]
                step = tf_seconds(tf)
                bars = _bars_truncados(con, row["pool"], tf, step, pool_row["added_ts"])
                if not bars:
                    continue
                det = DetectorV1(params, tf, pool_row["l_bc"], None, None)
                dex = pool_row["launchpad"] or row["launchpad"] or "desconhecido"
                for bar in bars:
                    for ev in det.update(bar):
                        if ev.kind != "ENTRADA":
                            continue
                        j0 = ev.idx + 1
                        if j0 >= len(bars):
                            continue
                        entry = bars[j0].open
                        stop, topo, s_val, r_val = ev.data["stop"], ev.data["TOPO"], ev.data["S"], ev.data["R"]
                        risco_pct = ev.data.get("risco_pct")
                        risk_frac = (entry - stop) / entry if entry else None
                        resultado = simular_sinal(bars, j0, entry, stop, topo, s_val, r_val, params, costs, dex,
                                                  pool_row["l_bc"])
                        linha = {"token": row["symbol"] or row["pool"][:8], "versao": versao, "origem": "retro",
                                "risco_pct": risco_pct}
                        for nome, r_res in resultado.items():
                            pct = (r_res.net_ret * 100.0) if r_res.net_ret is not None else None
                            r_mult = (r_res.net_ret / risk_frac) if (r_res.net_ret is not None and risk_frac
                                                                     and risco_pct is not None
                                                                     and risco_pct >= RISCO_IRREALISTA_MIN_PCT) else None
                            linha[nome] = {"status": r_res.status, "pct": pct, "r": r_mult, "motivo": r_res.reason}
                        linhas.append(linha)
        return linhas, n_fora_do_alcance
    finally:
        con.close()


def linhas_v3_replay_pools_admitidos(db_path: Path) -> list[dict[str, Any]]:
    """PEDIDO 2026-11-03 (continuacao -- pendente 5): sinais do REPLAY completo de `ParamsV3` sobre
    pools admitidos hoje (`avaliar_v3_retro.py: parte_a_pools_admitidos`, Parte A) -- reusa o MESMO
    evento bruto (`eventos_raw`, campo aditivo de `parte_a_pools_admitidos`) em vez de reexecutar o
    detector de novo (nunca duplica o replay)."""
    con = _conectar_ro(db_path)
    try:
        params_v3 = load_params_v3()
        linhas_pool = parte_a_pools_admitidos(con, params_v3)
    finally:
        con.close()
    costs = CostModel()
    linhas: list[dict[str, Any]] = []
    for lp in linhas_pool:
        for bars, ev, dex, l_bc in lp["eventos_raw"]:
            j0 = ev.idx + 1
            if j0 >= len(bars):
                continue
            entry = bars[j0].open
            stop, topo, s_val, r_val = ev.data["stop"], ev.data["TOPO"], ev.data["S"], ev.data["R"]
            risco_pct = ev.data.get("risco_pct")
            risk_frac = (entry - stop) / entry if entry else None
            resultado = simular_sinal(bars, j0, entry, stop, topo, s_val, r_val, params_v3, costs, dex, l_bc)
            linha = {"token": lp["symbol"], "versao": "v3", "origem": "v3_replay", "risco_pct": risco_pct}
            for nome, r_res in resultado.items():
                pct = (r_res.net_ret * 100.0) if r_res.net_ret is not None else None
                r_mult = (r_res.net_ret / risk_frac) if (r_res.net_ret is not None and risk_frac
                                                         and risco_pct is not None
                                                         and risco_pct >= RISCO_IRREALISTA_MIN_PCT) else None
                linha[nome] = {"status": r_res.status, "pct": pct, "r": r_mult, "motivo": r_res.reason}
            linhas.append(linha)
    return linhas


def _media(valores: list[float]) -> Optional[float]:
    return statistics.fmean(valores) if valores else None


def resumo_por_token(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PEDIDO 2026-11-03 (continuacao -- pendente 5): agrega TODAS as origens (v1/v2/v3 ao vivo,
    retro lote1, replay V3) por token -- media de %/R por variante."""
    por_token: dict[str, list[dict[str, Any]]] = {}
    for l in linhas:
        por_token.setdefault(l["token"], []).append(l)
    out: list[dict[str, Any]] = []
    for token, ls in sorted(por_token.items()):
        linha: dict[str, Any] = {"token": token, "n": len(ls)}
        for nome in VARIANTES:
            pcts = [l[nome]["pct"] for l in ls if l[nome]["pct"] is not None]
            rs = [l[nome]["r"] for l in ls if l[nome]["r"] is not None]
            linha[nome] = {"pct_medio": _media(pcts), "r_medio": _media(rs), "n": len(pcts)}
        out.append(linha)
    return out


def formatar(linhas: list[dict[str, Any]], sem_dado_box: dict[str, int], sem_bar_entrada: dict[str, int],
            n_fora_do_alcance_retro: int) -> str:
    out = [f"# exit_lab -- 4 saidas alternativas ({AVISO})", "",
          "Variantes: A=atual | B=breakeven apos 1x altura da caixa | C=1o fechamento 1h sob o teto | "
          "D=30% no topo + trailing no fundo da mini-caixa.", ""]
    for versao in ("v1", "v2", "v3"):
        linhas_v = [l for l in linhas if l["versao"] == versao]
        out.append(f"## {versao.upper()} (n={len(linhas_v)}, "
                  f"sem trajetoria/box: {sem_dado_box.get(versao, 0)}, sem candle de entrada: {sem_bar_entrada.get(versao, 0)})")
        for nome in VARIANTES:
            pcts = [l[nome]["pct"] for l in linhas_v if l[nome]["pct"] is not None]
            rs = [l[nome]["r"] for l in linhas_v if l[nome]["r"] is not None]
            out.append(f"  {nome}: media %={_media(pcts):+.1f}% (n={len(pcts)})" if pcts else f"  {nome}: s/d" +
                      (f" | media R={_media(rs):+.2f} (n={len(rs)})" if rs else " | R: s/d"))
        out.append("")
    retro = [l for l in linhas if l["origem"] == "retro"]
    out.append(f"## Coorte retrospectiva (lote 1, so admitidos apos congelamento; n={len(retro)}, "
              f"fora do alcance/sem dado: {n_fora_do_alcance_retro})")
    for nome in VARIANTES:
        pcts = [l[nome]["pct"] for l in retro if l[nome]["pct"] is not None]
        rs = [l[nome]["r"] for l in retro if l[nome]["r"] is not None]
        out.append(f"  {nome}: media %={_media(pcts):+.1f}% (n={len(pcts)})" if pcts else f"  {nome}: s/d")
    out.append("")
    v3_replay = [l for l in linhas if l["origem"] == "v3_replay"]
    out.append(f"## V3 replay (pools admitidos hoje, historico completo; n={len(v3_replay)})")
    for nome in VARIANTES:
        pcts = [l[nome]["pct"] for l in v3_replay if l[nome]["pct"] is not None]
        rs = [l[nome]["r"] for l in v3_replay if l[nome]["r"] is not None]
        out.append(f"  {nome}: media %={_media(pcts):+.1f}% (n={len(pcts)})" if pcts else f"  {nome}: s/d")
    out.append("")
    resumo_tokens = resumo_por_token(linhas)
    out.append(f"## Por token ({len(resumo_tokens)} distinto(s), todas as origens)")
    out.append("")
    if resumo_tokens:
        out.append("| token | n | " + " | ".join(f"{n} (%/R médios)" for n in VARIANTES) + " |")
        out.append("|---|---|" + "---|" * len(VARIANTES))
        for rt in resumo_tokens:
            celulas = []
            for nome in VARIANTES:
                v = rt[nome]
                pct = f"{v['pct_medio']:+.1f}%" if v["pct_medio"] is not None else "s/d"
                r = f"{v['r_medio']:+.2f}R" if v["r_medio"] is not None else "-"
                celulas.append(f"{pct}/{r} (n={v['n']})")
            out.append(f"| {rt['token']} | {rt['n']} | " + " | ".join(celulas) + " |")
    else:
        out.append("nenhum sinal.")
    out.append("")
    out.append("Por sinal:")
    out.append("")
    out.append("| token | versão | origem | risco% | " + " | ".join(f"{n} (%/R/motivo)" for n in VARIANTES) + " |")
    out.append("|---|---|---|---|" + "---|" * len(VARIANTES))
    for l in linhas:
        risco = f"{l['risco_pct']:.1f}" if l["risco_pct"] is not None else "s/d"
        celulas = []
        for nome in VARIANTES:
            r = l[nome]
            pct = f"{r['pct']:+.1f}%" if r["pct"] is not None else "s/d"
            rr = f"{r['r']:+.2f}R" if r["r"] is not None else "-"
            celulas.append(f"{pct}/{rr}/{r['motivo'] or r['status']}")
        out.append(f"| {l['token']} | {l['versao']} | {l['origem']} | {risco} | " + " | ".join(celulas) + " |")
    out.append("")
    out.append(f"({AVISO})")
    return "\n".join(out)


def executar(db_path: Path) -> str:
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        linhas: list[dict[str, Any]] = []
        sem_dado_box: dict[str, int] = {}
        sem_bar_entrada: dict[str, int] = {}
        for versao in ("v1", "v2", "v3"):
            l, sb, se = linhas_v1v2v3(storage, versao)
            linhas.extend(l)
            sem_dado_box[versao], sem_bar_entrada[versao] = sb, se
        retro, n_fora = linhas_retro_admitido(db_path)
        linhas.extend(retro)
        linhas.extend(linhas_v3_replay_pools_admitidos(db_path))
        return formatar(linhas, sem_dado_box, sem_bar_entrada, n_fora)
    finally:
        storage.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="exit_lab: 4 saidas alternativas exploratorias (leitura).")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    print(executar(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
