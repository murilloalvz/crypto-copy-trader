"""PEDIDO 2026-11-05 (autorizado): calcula e persiste R no horizonte fixo (72h/7d, ver `pos_runner/
horizonte_fixo.py` e docs/pos-runner-v1/EMENDA_2026-11-05_HORIZONTE_FIXO_PROPOSTA.md) para os sinais
AO VIVO de V1/V2/V3 -- sinal E controles pareados (`pr_baseline`). SOMENTE LEITURA em tudo, EXCETO a
tabela nova `pr_horizonte_fixo` (nunca toca pr1_signals/pr2_signals/pr3_signals/pr_baseline/pr_trajetoria/
detector/simulate/parametros). Cobertura retro_lote1/replay_v3 (persistida em `pr_horizonte_fixo`) fica
para uma proxima rodada -- esta ja resolve a parte que decide H1/futilidade/controles (item do pedido
2026-11-05), que e so sobre sinais ao vivo (unicos com `pr_baseline`).

Uso (na VM, a partir da raiz do repo):
    python -m signals_mvp.scripts.horizonte_fixo --db signals_mvp/dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from pathlib import Path
from typing import Any, Optional

from ..config import make_paths
from ..pos_runner.candles import Bar
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import EventV1
from ..pos_runner.evidencia import evento_controle
from ..pos_runner.horizonte_fixo import HORIZONTES_S, calcular_r_horizonte, garantir_emenda_registrada
from ..pos_runner.params_v1 import load_params_v1
from ..pos_runner.params_v2 import load_params_v2
from ..pos_runner.params_v3 import load_params_v3
from ..storage import Storage

_PARAMS = {"v1": load_params_v1, "v2": load_params_v2, "v3": load_params_v3}
_SIGNALS = {"v1": "pr1_signals", "v2": "pr2_signals", "v3": "pr3_signals"}


def _bars_do_pool(storage: Storage, pool: str, tf: str) -> list[Bar]:
    return [Bar(*row) for row in storage.pr_bars(pool, tf)]


def _r_controle_medio(
    storage: Storage, versao: str, signal_id: int, sinal: Any, bars: list[Bar], params: Any,
    costs: CostModel, dex: str, l_bc: Optional[float], horizonte_s: float, now: float,
) -> Optional[float]:
    """Reaplica, SO para medir o horizonte (nunca escreve em `pr_baseline`), os MESMOS controles
    pareados ja sorteados por `live.py: _atualizar_baseline` (`controles_json`, so leitura)."""
    baseline = storage.pr_baseline_get(versao, signal_id)
    if baseline is None:
        return None
    entry_price_sinal = sinal["entry_price"]
    if not entry_price_sinal or sinal["stop"] is None or sinal["topo"] is None or sinal["s_suporte"] is None:
        return None
    risco_pct_sinal = 100.0 * (1.0 - sinal["stop"] / entry_price_sinal)
    topo_mult = sinal["topo"] / entry_price_sinal
    s_mult = sinal["s_suporte"] / entry_price_sinal
    valores: list[float] = []
    for c in json.loads(baseline["controles_json"] or "[]"):
        ev = evento_controle(bars, c["idx"], risco_pct_sinal, topo_mult, s_mult)
        if ev is None:
            continue
        r = calcular_r_horizonte(bars, ev, params, costs, dex, l_bc, t_entrada=bars[c["idx"]].ts,
                                 horizonte_s=horizonte_s, now=now)
        if r.r_mult is not None:
            valores.append(r.r_mult)
    return (sum(valores) / len(valores)) if valores else None


def calcular_e_persistir_ao_vivo(storage: Storage, versao: str, now: Optional[float] = None) -> dict[str, int]:
    """Devolve contagem por status (pendente/resolvido_regra/marcado/sem_dado), somada sobre os 2
    horizontes -- so pra relatorio, nunca decide nada."""
    now = time.time() if now is None else now
    params = _PARAMS[versao]()
    costs = CostModel()
    contagem: dict[str, int] = {}
    bars_cache: dict[str, list[Bar]] = {}
    for sinal in getattr(storage, _SIGNALS[versao])():
        if sinal["evento"] != "ENTRADA":
            continue
        if sinal["stop"] is None or sinal["topo"] is None or sinal["entry_price"] is None:
            continue
        traj = storage.pr_trajetoria_get(versao, sinal["id"])
        if traj is None or traj["t_entrada"] is None:
            continue
        tf = sinal["tf"] or params.timeframes[0]
        bars = bars_cache.setdefault(f"{sinal['pool']}|{tf}", _bars_do_pool(storage, sinal["pool"], tf))
        j0 = None
        for idx, bar in enumerate(bars):
            if bar.ts == traj["t_entrada"]:
                j0 = idx
                break
        if j0 is None or j0 <= 0:
            continue
        pool_row = storage.pr_pool(sinal["pool"])
        l_bc = pool_row["l_bc"] if pool_row is not None else None
        dex = sinal["dex"] or "desconhecido"
        ev = EventV1(kind="ENTRADA", idx=j0 - 1, ts=bars[j0 - 1].ts, decision_ts=bars[j0 - 1].ts,
                     data={"stop": sinal["stop"], "TOPO": sinal["topo"], "S": sinal["s_suporte"]})
        for horizonte, horizonte_s in HORIZONTES_S.items():
            r = calcular_r_horizonte(bars, ev, params, costs, dex, l_bc, t_entrada=traj["t_entrada"],
                                     horizonte_s=horizonte_s, now=now)
            contagem[r.status] = contagem.get(r.status, 0) + 1
            r_controle_medio = None
            dif_pareada = None
            if r.r_mult is not None:
                r_controle_medio = _r_controle_medio(storage, versao, sinal["id"], sinal, bars, params,
                                                     costs, dex, l_bc, horizonte_s, now)
                if r_controle_medio is not None:
                    dif_pareada = r.r_mult - r_controle_medio
            storage.pr_horizonte_fixo_upsert(
                versao, "ao_vivo", str(sinal["id"]), horizonte, now, r.status, r_mult=r.r_mult,
                candle_marca_ts=r.candle_marca_ts, mint=sinal["mint"], symbol=sinal["symbol"],
                t_entrada=traj["t_entrada"], r_controle_medio=r_controle_medio, dif_pareada=dif_pareada,
            )
    return contagem


def relatorio(storage: Storage, now: Optional[float] = None) -> str:
    now = time.time() if now is None else now
    out = ["# Horizonte fixo (72h/7d) -- emenda 2026-11-05 (autorizada)", "",
          "SO sinais ao vivo (V1/V2/V3) -- retro_lote1/replay_v3 ainda nao persistidos aqui.", ""]
    for versao in ("v1", "v2", "v3"):
        abertos = len(getattr(storage, _SIGNALS[versao])(status="aberto"))
        fechados = len(getattr(storage, _SIGNALS[versao])(status="fechado"))
        out.append(f"## {versao.upper()}: abertos={abertos} | fechados={fechados}")
        for horizonte in HORIZONTES_S:
            rows = storage.pr_horizonte_fixo_all(versao=versao, origem="ao_vivo", horizonte=horizonte)
            por_status: dict[str, int] = {}
            for row in rows:
                por_status[row["status"]] = por_status.get(row["status"], 0) + 1
            out.append(f"  horizonte {horizonte}: " +
                      (", ".join(f"{k}={v}" for k, v in sorted(por_status.items())) or "(nenhum calculado ainda)"))
        out.append("")
    return "\n".join(out)


def executar(db_path: Path) -> str:
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        garantir_emenda_registrada(storage)
        for versao in ("v1", "v2", "v3"):
            calcular_e_persistir_ao_vivo(storage, versao)
        return relatorio(storage)
    finally:
        storage.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Calcula/persiste R no horizonte fixo (72h/7d) para sinais ao vivo V1/V2/V3 (PAPER/so leitura).")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    print(executar(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
