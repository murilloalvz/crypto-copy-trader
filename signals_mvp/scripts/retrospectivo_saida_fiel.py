"""PEDIDO 2026-11-06 (autorizado, rodada 12, Parte 2): retrospectivo NAO CONDICIONADO da saida fiel
(pre-registrada em `docs/pos-runner-v3/PREREGISTRO_SAIDA_FIEL_2026-11-06.md`, hash congelado por
`garantir_saida_fiel_registrada`) sobre os sinais V3 JA EXISTENTES -- `ao_vivo`/`retro_lote1`/
`replay_v3`, SEPARADOS, nunca somados. SOMENTE LEITURA no banco do bot (zero chamada de rede, zero
escrita em `pr3_signals`/alertas/trajetoria -- so em `meta`, via `garantir_saida_fiel_registrada`).
PAPER/READ-ONLY. Detector/simulate/ParamsV3/H1/criterio de sinal NUNCA alterados.

Horizontes 72h/7d (`horizonte_fixo.HORIZONTES_S`, MESMA definicao do resto do projeto). Sinais
'pendente' (horizonte ainda nao decorrido) ficam de fora de qualquer media, reportados so como
contagem -- NUNCA perda, NUNCA descartados; idem 'sem_dado' (entrada cancelada, fora do stop/TOPO).
Estatisticas (media/mediana/sem-top3/IC90% bootstrap por token, 10k reamostras, semente fixa -- MESMOS
defaults de `analise.condicional`/`varredura_v3._resumir_pareamento`, nunca duplicados) sao calculadas
sobre TODOS os sinais com horizonte VENCIDO (resolvido OU marcado pela saida fiel -- com ou sem TP1,
nunca so o subconjunto que realizou TP1), reportadas lado a lado com a saida ATUAL (A,
`horizonte_fixo.calcular_r_horizonte`, a MESMA definicao oficial ja usada em todo o resto do projeto).
A fracao que realiza TP1 e reportada SEPARADAMENTE (nunca usada pra filtrar a amostra principal).

ATRIBUICAO (pedido explicito): a MESMA saida fiel e aplicada aos 10 controles pareados do MESMO token
(`evidencia.sortear_controles`, MESMA mecanica da H1, via `varredura_v3._controles_indices`) e as
entradas aleatorias do comparador (K=20, `varredura_v3._aleatorios_indices`) -- MESMA fase/elegibilidade
e MESMA distancia de stop do sinal real (`varredura_v3._evento_controle_sinal`) -- pra separar o efeito
da ENTRADA (sinal real vs controles/aleatorio, MESMA saida fiel) do efeito da SAIDA (saida fiel vs
saida atual A, MESMO sinal real).

Reusa `SinalVarredura`/`carregar_universo_admitido`/`carregar_retro_lote1`/`_controles_indices`/
`_aleatorios_indices`/`_evento_controle_sinal`/`Pareamento`/`_resumir_pareamento`/`_formatar_pareamento`
de `varredura_v3.py` sem duplicar logica -- so o loader `ao_vivo` e novo aqui (MESMO padrao de leitura
de `auditoria_fidelidade_v3.carregar_ao_vivo`: `pr3_signals`/`pr_trajetoria`/`pr_bars`/`pr_pools`, mas
monta um `SinalVarredura` via `vv3._montar_sinal` reusado em vez de um `SinalAuditoria`, pra poder
reusar os controles/aleatorio sem um adaptador -- eles exigem `created_ts`/`pool`/`tf`/`origem` de
`SinalVarredura`, que `SinalAuditoria` nao guarda).

Uso (na VM, a partir da raiz do repo -- replay completo, RAM/CPU fracos):
    nice -n 19 tmux new-session -d -s retrospectivo_saida_fiel \
        'python -m signals_mvp.scripts.retrospectivo_saida_fiel --db signals_mvp/dados/estado.sqlite \
         2>&1 | tee retrospectivo_saida_fiel.log'
"""

from __future__ import annotations

import argparse
import dataclasses
import time
from pathlib import Path
from typing import Any, Optional

from ..config import make_paths
from ..pos_runner.candles import Bar
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import EventV1
from ..pos_runner.horizonte_fixo import HORIZONTES_S, calcular_r_horizonte
from ..pos_runner.params_v3 import load_params_v3
from ..pos_runner.saida_fiel import ResultadoSaidaFiel, calcular_r_saida_fiel, garantir_saida_fiel_registrada
from ..storage import Storage
from . import varredura_v3 as vv3
from .avaliar_v3_retro import _created_ts

AVISO = ("EXPLORATORIO -- motivado por achados ja vistos (rodada 11, B3b); retrospectivo NAO "
        "CONDICIONADO sobre dados DENTRO DA AMOSTRA, nunca confirmatorio, nunca entra no N=30 nem na "
        "H1 (docs/research-hypothesis-registry-v1-2026-10-04.md continua sendo a unica autoridade pra "
        "isso). ao_vivo/retro_lote1/replay_v3 SEPARADOS, nunca somados. Resultado em paper, TETO de "
        "execucao -- vies de sobrevivencia (so pools que o GeckoTerminal ainda alcanca).")

RAM_MINIMA_MB_PADRAO = vv3.RAM_MINIMA_MB_PADRAO


# ---------------------------------------------------------------------------
# loader `ao_vivo` (novo aqui -- os outros 2 sao 100% reuso de varredura_v3.py)
# ---------------------------------------------------------------------------


def carregar_ao_vivo(db_path: Path) -> list[vv3.SinalVarredura]:
    """MESMO padrao de leitura de `auditoria_fidelidade_v3.carregar_ao_vivo` (pr3_signals/
    pr_trajetoria/pr_bars/pr_pools), mas monta um `SinalVarredura` (via `vv3._montar_sinal`) em vez de
    um `SinalAuditoria` -- precisa de `created_ts`/`pool`/`tf`/`origem` pra reusar
    `_controles_indices`/`_aleatorios_indices` sem adaptador."""
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        params = load_params_v3()
        out: list[vv3.SinalVarredura] = []
        bars_cache: dict[str, list[Bar]] = {}
        for sinal in storage.pr3_signals():
            if sinal["evento"] != "ENTRADA":
                continue
            if sinal["stop"] is None or sinal["topo"] is None or sinal["entry_price"] is None:
                continue
            traj = storage.pr_trajetoria_get("v3", sinal["id"])
            if traj is None or traj["t_entrada"] is None:
                continue
            tf = sinal["tf"] or params.timeframes[0]
            bars = bars_cache.setdefault(f"{sinal['pool']}|{tf}",
                                        [Bar(*row) for row in storage.pr_bars(sinal["pool"], tf)])
            j0 = None
            for idx, bar in enumerate(bars):
                if bar.ts == traj["t_entrada"]:
                    j0 = idx
                    break
            if j0 is None or j0 <= 0:
                continue
            gatilho_idx = j0 - 1
            pool_row = storage.pr_pool(sinal["pool"])
            l_bc = pool_row["l_bc"] if pool_row is not None else None
            dex = sinal["dex"] or "desconhecido"
            created_ts = _created_ts(pool_row["info"]) if pool_row is not None else None
            supply = pool_row["supply"] if pool_row is not None else None
            ev = EventV1(kind="ENTRADA", idx=gatilho_idx, ts=bars[gatilho_idx].ts,
                        decision_ts=bars[gatilho_idx].ts,
                        data={"stop": sinal["stop"], "TOPO": sinal["topo"], "S": sinal["s_suporte"]})
            # RODADA 17 (achado A2 da auditoria 2026-11-10): mint real, nunca "" -- `sinal["mint"]"
            # (pr3_signals.mint, ja o mint real gravado ao vivo) estava disponivel mas nunca passado.
            s = vv3._montar_sinal(bars, ev, dex, l_bc, "ao_vivo", sinal["symbol"] or (sinal["mint"] or "")[:8],
                                  sinal["mint"] or sinal["pool"], sinal["pool"], tf, created_ts, supply)
            if s is not None:
                out.append(s)
        return sorted(out, key=lambda s: s.t_entrada)
    finally:
        storage.close()


# ---------------------------------------------------------------------------
# agregacao: saida fiel vs saida atual (A), por horizonte, + atribuicao (controles/aleatorio)
# ---------------------------------------------------------------------------


def _saida_fiel(s: vv3.SinalVarredura, ev: EventV1, t_entrada: float, horizonte_s: float, now: float,
                params: Any, costs: CostModel) -> ResultadoSaidaFiel:
    return calcular_r_saida_fiel(s.bars, ev, params, costs, s.dex, s.l_bc, t_entrada=t_entrada,
                                 horizonte_s=horizonte_s, now=now)


@dataclasses.dataclass
class ResumoHorizonte:
    horizonte: str
    n_pendente: int
    n_sem_dado: int
    n_vencido: int             # resolvido OU marcado pela saida fiel -- TODOS, com ou sem TP1
    n_tp1: int
    fracao_tp1_pct: Optional[float]
    saida_fiel: vv3.Pareamento             # sobre TODOS os n_vencido (nunca so os com TP1)
    saida_atual_a: vv3.Pareamento          # MESMO conjunto de sinais, saida OFICIAL (A)
    controles_saida_fiel: vv3.Pareamento   # 10 controles pareados/token, MESMA saida fiel
    aleatorio_saida_fiel: vv3.Pareamento   # K=20 entradas aleatorias/sinal, MESMA saida fiel


def agregar_horizonte(sinais: list[vv3.SinalVarredura], horizonte: str, now: float, params: Any,
                      costs: CostModel) -> ResumoHorizonte:
    horizonte_s = HORIZONTES_S[horizonte]
    n_pendente = n_sem_dado = n_vencido = n_tp1 = 0
    valores_fiel: dict[str, list[float]] = {}
    valores_a: dict[str, list[float]] = {}
    valores_controles: dict[str, list[float]] = {}
    valores_aleatorio: dict[str, list[float]] = {}
    for s in sinais:
        r_fiel = _saida_fiel(s, s.ev, s.t_entrada, horizonte_s, now, params, costs)
        if r_fiel.status == "pendente":
            n_pendente += 1
            continue
        if r_fiel.status == "sem_dado":
            n_sem_dado += 1
            continue
        # resolvido OU marcado pela saida fiel -- TODOS entram aqui, com ou sem TP1 (pedido explicito:
        # "sobre TODOS os sinais com horizonte vencido", nunca so o subconjunto n_tp1).
        n_vencido += 1
        if r_fiel.tp1_realizado:
            n_tp1 += 1
        if r_fiel.r_mult is not None:
            valores_fiel.setdefault(s.token, []).append(r_fiel.r_mult)
        r_a = calcular_r_horizonte(s.bars, s.ev, params, costs, s.dex, s.l_bc, t_entrada=s.t_entrada,
                                   horizonte_s=horizonte_s, now=now)
        if r_a.r_mult is not None:
            valores_a.setdefault(s.token, []).append(r_a.r_mult)
        # Atribuicao: MESMA saida fiel aplicada aos 10 controles e aos K=20 aleatorios do MESMO sinal
        # (MESMA fase/distancia de stop -- `_evento_controle_sinal`), pra separar entrada de saida.
        for idx in vv3._controles_indices(s, params):
            ev_c = vv3._evento_controle_sinal(s, idx)
            if ev_c is None:
                continue
            r_c = _saida_fiel(s, ev_c, s.bars[idx].ts, horizonte_s, now, params, costs)
            if r_c.r_mult is not None:
                valores_controles.setdefault(s.token, []).append(r_c.r_mult)
        for idx in vv3._aleatorios_indices(s, params):
            ev_r = vv3._evento_controle_sinal(s, idx)
            if ev_r is None:
                continue
            r_r = _saida_fiel(s, ev_r, s.bars[idx].ts, horizonte_s, now, params, costs)
            if r_r.r_mult is not None:
                valores_aleatorio.setdefault(s.token, []).append(r_r.r_mult)
    fracao_tp1 = (100.0 * n_tp1 / n_vencido) if n_vencido else None
    return ResumoHorizonte(
        horizonte=horizonte, n_pendente=n_pendente, n_sem_dado=n_sem_dado, n_vencido=n_vencido,
        n_tp1=n_tp1, fracao_tp1_pct=fracao_tp1, saida_fiel=vv3._resumir_pareamento(valores_fiel),
        saida_atual_a=vv3._resumir_pareamento(valores_a),
        controles_saida_fiel=vv3._resumir_pareamento(valores_controles),
        aleatorio_saida_fiel=vv3._resumir_pareamento(valores_aleatorio),
    )


@dataclasses.dataclass
class ResumoOrigemSaidaFiel:
    origem: str
    n_sinais: int
    n_tokens: int
    por_horizonte: dict[str, ResumoHorizonte]


def agregar_origem_saida_fiel(sinais: list[vv3.SinalVarredura], origem_label: str, now: float
                              ) -> ResumoOrigemSaidaFiel:
    params = load_params_v3()
    costs = CostModel()
    por_horizonte = {h: agregar_horizonte(sinais, h, now, params, costs) for h in HORIZONTES_S}
    return ResumoOrigemSaidaFiel(origem=origem_label, n_sinais=len(sinais),
                                 n_tokens=len({s.token for s in sinais}), por_horizonte=por_horizonte)


# ---------------------------------------------------------------------------
# relatorio
# ---------------------------------------------------------------------------


def _formatar_resumo_horizonte(r: ResumoHorizonte) -> list[str]:
    frac_txt = f"{r.fracao_tp1_pct:.1f}%" if r.fracao_tp1_pct is not None else "s/d"
    out = [f"### horizonte {r.horizonte}", "",
          f"pendente={r.n_pendente} | sem_dado={r.n_sem_dado} | horizonte vencido (resolvido+marcado, "
          f"com ou sem TP1)={r.n_vencido} | realizou TP1={r.n_tp1} ({frac_txt} dos vencidos)", "",
          vv3._formatar_pareamento("saida FIEL (sinal real, todos os vencidos)", r.saida_fiel),
          vv3._formatar_pareamento("saida ATUAL A (sinal real, MESMO conjunto, regra oficial)",
                                   r.saida_atual_a),
          vv3._formatar_pareamento("saida fiel nos 10 controles pareados/token (efeito da ENTRADA)",
                                   r.controles_saida_fiel),
          vv3._formatar_pareamento("saida fiel em K=20 entradas aleatorias/sinal (efeito da ENTRADA)",
                                   r.aleatorio_saida_fiel),
          ""]
    return out


def _formatar_origem(r: ResumoOrigemSaidaFiel) -> list[str]:
    out = [f"## {r.origem}", "", f"n sinais: {r.n_sinais} | tokens distintos: {r.n_tokens}", ""]
    if r.n_sinais == 0:
        out.append("(sem sinais nesta origem -- universo vazio para esta fonte nesta base)")
        out.append("")
        return out
    for h in HORIZONTES_S:
        out.extend(_formatar_resumo_horizonte(r.por_horizonte[h]))
    return out


def formatar(ao_vivo: ResumoOrigemSaidaFiel, retro: ResumoOrigemSaidaFiel, replay: ResumoOrigemSaidaFiel
            ) -> str:
    out = ["# retrospectivo_saida_fiel -- saida fiel vs saida atual (A), nao condicionado", "",
          f"AVISO: {AVISO}", "",
          "Leitura: 'saida FIEL' e 'saida ATUAL A' sao o MESMO sinal real sob 2 regras de saida "
          "diferentes (efeito da SAIDA); 'controles'/'aleatorio' sao OUTRAS entradas (MESMA fase/"
          "distancia de stop) sob a MESMA saida fiel do sinal real (efeito da ENTRADA). Comparar os 4 "
          "numeros de cada horizonte separa os 2 efeitos -- nenhuma variante decide 'vencedora' aqui, "
          "so descreve.", ""]
    for r in (ao_vivo, retro, replay):
        out.extend(_formatar_origem(r))
    return "\n".join(out)


def executar(db_path: Path, progresso: bool = True, min_ram_mb: float = RAM_MINIMA_MB_PADRAO) -> str:
    import sys as _sys
    vv3.checar_ram_ou_abortar(min_ram_mb)

    def status(msg: str) -> None:
        if progresso:
            print(f"[retrospectivo_saida_fiel] {msg}", file=_sys.stderr, flush=True)

    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        garantir_saida_fiel_registrada(storage)
    finally:
        storage.close()

    now = time.time()
    status("carregando ao_vivo...")
    ao_vivo = carregar_ao_vivo(db_path)
    status(f"ao_vivo: {len(ao_vivo)} sinais. carregando retro_lote1...")
    retro = vv3.carregar_retro_lote1(db_path)
    status(f"retro_lote1: {len(retro)} sinais. carregando replay_v3 (pode levar um tempo -- replay "
          "completo de todos os pools admitidos)...")
    replay = vv3.carregar_universo_admitido(db_path)
    status(f"replay_v3: {len(replay)} sinais. agregando (saida fiel + saida A + controles + "
          "aleatorio, por horizonte)...")
    r_ao_vivo = agregar_origem_saida_fiel(ao_vivo, "ao_vivo", now)
    status("ao_vivo agregado.")
    r_retro = agregar_origem_saida_fiel(retro, "retro_lote1", now)
    status("retro_lote1 agregado.")
    r_replay = agregar_origem_saida_fiel(replay, "replay_v3", now)
    status("replay_v3 agregado. montando relatorio.")
    return formatar(r_ao_vivo, r_retro, r_replay)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Retrospectivo nao condicionado da saida fiel vs saida atual (A) -- PAPER/so "
                    "leitura/EXPLORATORIO.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--sem-progresso", action="store_true", help="nao imprime progresso em stderr")
    parser.add_argument("--min-ram-mb", type=float, default=RAM_MINIMA_MB_PADRAO,
                        help="aborta se a RAM disponivel ficar abaixo disso (MB)")
    args = parser.parse_args(argv)
    print(executar(args.db, progresso=not args.sem_progresso, min_ram_mb=args.min_ram_mb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
