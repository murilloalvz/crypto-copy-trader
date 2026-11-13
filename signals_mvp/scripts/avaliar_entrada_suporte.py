"""PEDIDO 2026-11-12 (autorizado, rodada 18, item 3): avalia a hipotese EXPLORATORIA "entrada no
suporte" pre-registrada em `docs/pos-runner-v3/PREREGISTRO_ENTRADA_SUPORTE_2026-11-12.md` (hash
congelado por `entrada_suporte.garantir_entrada_suporte_registrada`, igual ao padrao da saida fiel).
PAPER/READ-ONLY, zero chamada de rede, zero escrita fora de `meta`. Detector/ParamsV3/H1/criterio de
sinal da V3 NUNCA alterados -- esta e uma variante de ENTRADA isolada, julgada com a MESMA saida A
oficial (`horizonte_fixo.calcular_r_horizonte`), nunca uma saida nova.

Reusa, sem duplicar: `SinalVarredura`/`carregar_universo_admitido`/`carregar_retro_lote1`/
`_montar_sinal`/`_aleatorios_indices`/`_evento_controle_sinal`/`_r72h_de_indices`/`_primeiro_toque`/
`Pareamento`/`_resumir_pareamento`/`_formatar_pareamento`/`_bootstrap_ic_media` de `varredura_v3.py`,
o loader `ao_vivo` de `retrospectivo_saida_fiel.py`, e `entrada_suporte.localizar_revisitas_suporte`
(a reconstrucao causal da caixa, mora em `pos_runner/` por nao depender de `scripts/`).

NUNCA entra no N=30 nem na H1 -- `docs/research-hypothesis-registry-v1-2026-10-04.md` continua
sendo a unica autoridade formal (ver pre-registro, secao "O que esta hipotese NAO faz").

Uso (na VM, a partir da raiz do repo -- replay completo, RAM/CPU fracos):
    nice -n 19 tmux new-session -d -s avaliar_entrada_suporte \
        'python -m signals_mvp.scripts.avaliar_entrada_suporte --db signals_mvp/dados/estado.sqlite \
         2>&1 | tee avaliar_entrada_suporte.log'
"""

from __future__ import annotations

import argparse
import dataclasses
import math
import time
from pathlib import Path
from typing import Any, Optional

from ..config import make_paths
from ..pos_runner.costs import CostModel
from ..pos_runner.entrada_suporte import garantir_entrada_suporte_registrada, localizar_revisitas_suporte
from ..pos_runner.horizonte_fixo import HORIZONTES_S, calcular_r_horizonte
from ..pos_runner.params_v3 import load_params_v3
from ..storage import Storage
from . import retrospectivo_saida_fiel as rsf
from . import varredura_v3 as vv3

AVISO = ("EXPLORATORIA -- motivada por achados ja vistos (rodada 11, B4: toque pareado medio -0,14R); "
        "variante de ENTRADA isolada, julgada com a MESMA saida A oficial. NUNCA entra no N=30 nem na "
        "H1 (docs/research-hypothesis-registry-v1-2026-10-04.md continua sendo a unica autoridade). "
        "ao_vivo/retro_lote1/replay_v3 SEPARADOS, nunca somados. Elegibilidade reduz N -- sinais sem "
        "revisita apos a caixa formada e antes do gatilho real ficam de fora, nunca inventados.")

RAM_MINIMA_MB_PADRAO = vv3.RAM_MINIMA_MB_PADRAO
ALVOS_TOQUE = (2.0, 5.0)   # pedido explicito: toque +2R/+5R


# ---------------------------------------------------------------------------
# por sinal: localiza a(s) revisita(s), monta o sinal sintetico, aplica a MESMA saida A
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ResultadoSinalSuporte:
    elegivel: bool
    r_suporte: Optional[float] = None               # (hipotese) saida A sobre a 1a revisita
    r_v3: Optional[float] = None                    # (a) saida A sobre o sinal V3 real
    r_aleatorio_medio: Optional[float] = None       # (b) media da saida A sobre K=20 aleatorios
    r_outros_instantes: list[float] = dataclasses.field(default_factory=list)   # (c)
    risco_pct: Optional[float] = None               # distancia do stop em % (entrada no suporte)
    toques: dict[float, Optional[str]] = dataclasses.field(default_factory=dict)   # +2R/+5R


def avaliar_sinal(sinal: vv3.SinalVarredura, params: Any, costs: CostModel, horizonte_s: float,
                  now: float, veto: str) -> ResultadoSinalSuporte:
    zona_alvo = sinal.ev.data.get("zona")
    if zona_alvo is None:
        return ResultadoSinalSuporte(elegivel=False)
    revisitas = localizar_revisitas_suporte(sinal.bars, sinal.tf, sinal.l_bc, sinal.created_ts, params,
                                            zona_alvo, sinal.ev.idx)
    if not revisitas:
        return ResultadoSinalSuporte(elegivel=False)

    def _sinal_na_revisita(rev: Any) -> Optional[vv3.SinalVarredura]:
        from ..pos_runner.detector_v1 import EventV1
        ev = EventV1(kind="ENTRADA_SUPORTE_HIP", idx=rev.idx, ts=sinal.bars[rev.idx].ts,
                    decision_ts=sinal.bars[rev.idx].ts,
                    data={"stop": rev.stop, "TOPO": sinal.topo, "S": rev.s_no_momento})
        return vv3._montar_sinal(sinal.bars, ev, sinal.dex, sinal.l_bc, sinal.origem, sinal.token,
                                 sinal.mint, sinal.pool, sinal.tf, sinal.created_ts, sinal.supply,
                                 veto=veto)

    s_suporte = _sinal_na_revisita(revisitas[0])
    if s_suporte is None:
        return ResultadoSinalSuporte(elegivel=False)

    r_suporte = calcular_r_horizonte(s_suporte.bars, s_suporte.ev, params, costs, s_suporte.dex,
                                     s_suporte.l_bc, t_entrada=s_suporte.t_entrada,
                                     horizonte_s=horizonte_s, now=now, veto=veto)
    r_v3 = calcular_r_horizonte(sinal.bars, sinal.ev, params, costs, sinal.dex, sinal.l_bc,
                               t_entrada=sinal.t_entrada, horizonte_s=horizonte_s, now=now, veto=veto)

    indices_aleatorios = vv3._aleatorios_indices(sinal, params)
    r_aleatorios = vv3._r72h_de_indices(sinal, indices_aleatorios, params, costs, now, veto=veto)
    r_aleatorio_medio = (sum(r_aleatorios) / len(r_aleatorios)) if r_aleatorios else None

    r_outros: list[float] = []
    for rev in revisitas[1:]:
        s_outro = _sinal_na_revisita(rev)
        if s_outro is None:
            continue
        r_outro = calcular_r_horizonte(s_outro.bars, s_outro.ev, params, costs, s_outro.dex,
                                       s_outro.l_bc, t_entrada=s_outro.t_entrada,
                                       horizonte_s=horizonte_s, now=now, veto=veto)
        if r_outro.r_mult is not None:
            r_outros.append(r_outro.r_mult)

    toques = {alvo: vv3._primeiro_toque(s_suporte, alvo, veto=veto) for alvo in ALVOS_TOQUE}

    return ResultadoSinalSuporte(
        elegivel=True, r_suporte=r_suporte.r_mult, r_v3=r_v3.r_mult,
        r_aleatorio_medio=r_aleatorio_medio, r_outros_instantes=r_outros,
        risco_pct=100.0 * s_suporte.risk_frac, toques=toques,
    )


# ---------------------------------------------------------------------------
# agregacao por origem (pareado por token, bootstrap, poder honesto)
# ---------------------------------------------------------------------------


Z_0_95 = 1.6449   # unilateral alpha=0,05 -- MESMA convencao de EMENDA_2026-11-05_PODER_ESTATISTICO_N30
Z_0_80 = 0.8416   # poder 80%


def _poder_honesto_mde(ic90: Optional[tuple[float, float]], n: int) -> Optional[float]:
    """MESMA formula MDE normal-aproximada da emenda do N=30 (rodada 9 item 6), reaplicada ao DP
    observado AQUI (nunca ao N=30 da H1) -- diferenca minima detectavel em R, poder 80%, alpha 0,05
    unilateral (equivalente ao IC90% de 2 caudas)."""
    if ic90 is None or n <= 1:
        return None
    meia_largura = (ic90[1] - ic90[0]) / 2.0
    dp = meia_largura * math.sqrt(n) / Z_0_95
    return (Z_0_95 + Z_0_80) * dp / math.sqrt(n)


@dataclasses.dataclass
class ResumoOrigemSuporte:
    origem: str
    n_sinais: int
    n_elegiveis: int
    n_tokens_elegiveis: int
    suporte: vv3.Pareamento
    v3: vv3.Pareamento
    aleatorio: vv3.Pareamento
    outros_instantes: vv3.Pareamento
    dif_vs_v3_por_token: dict[str, list[float]]
    risco_pct_medio: Optional[float]
    toques: dict[float, dict[str, Any]]
    poder_mde_vs_v3: Optional[float]


def agregar_origem_suporte(sinais: list[vv3.SinalVarredura], origem_label: str, horizonte: str,
                           now: float, veto: str) -> ResumoOrigemSuporte:
    params = load_params_v3()
    costs = CostModel()
    horizonte_s = HORIZONTES_S[horizonte]
    resultados = [avaliar_sinal(s, params, costs, horizonte_s, now, veto) for s in sinais]
    elegiveis = [(s, r) for s, r in zip(sinais, resultados) if r.elegivel]

    vals_suporte: dict[str, list[float]] = {}
    vals_v3: dict[str, list[float]] = {}
    vals_aleatorio: dict[str, list[float]] = {}
    vals_outros: dict[str, list[float]] = {}
    dif_vs_v3: dict[str, list[float]] = {}
    riscos: list[float] = []
    toques_por_alvo: dict[float, list[Optional[str]]] = {alvo: [] for alvo in ALVOS_TOQUE}

    for s, r in elegiveis:
        if r.risco_pct is not None:
            riscos.append(r.risco_pct)
        for alvo in ALVOS_TOQUE:
            toques_por_alvo[alvo].append(r.toques.get(alvo))
        if r.r_suporte is None:
            continue
        vals_suporte.setdefault(s.mint, []).append(r.r_suporte)
        if r.r_v3 is not None:
            vals_v3.setdefault(s.mint, []).append(r.r_v3)
            dif_vs_v3.setdefault(s.mint, []).append(r.r_suporte - r.r_v3)
        if r.r_aleatorio_medio is not None:
            vals_aleatorio.setdefault(s.mint, []).append(r.r_aleatorio_medio)
        if r.r_outros_instantes:
            vals_outros.setdefault(s.mint, []).extend(r.r_outros_instantes)

    toques_resumo: dict[float, dict[str, Any]] = {}
    for alvo in ALVOS_TOQUE:
        decididos = [t for t in toques_por_alvo[alvo] if t is not None]
        n_alvo = sum(1 for t in decididos if t == "alvo")
        n = len(decididos)
        toques_resumo[alvo] = {
            "n_decididos": n, "n_indefinido": len(toques_por_alvo[alvo]) - n, "n_alvo": n_alvo,
            "p_observado_pct": (100.0 * n_alvo / n) if n else None,
        }

    pareamento_suporte = vv3._resumir_pareamento(vals_suporte)
    poder = _poder_honesto_mde(vv3._bootstrap_ic_media(dif_vs_v3) if dif_vs_v3 else None,
                              pareamento_suporte.n)

    return ResumoOrigemSuporte(
        origem=origem_label, n_sinais=len(sinais), n_elegiveis=len(elegiveis),
        n_tokens_elegiveis=len({s.mint for s, _ in elegiveis}),
        suporte=pareamento_suporte, v3=vv3._resumir_pareamento(vals_v3),
        aleatorio=vv3._resumir_pareamento(vals_aleatorio),
        outros_instantes=vv3._resumir_pareamento(vals_outros),
        dif_vs_v3_por_token=dif_vs_v3,
        risco_pct_medio=(sum(riscos) / len(riscos)) if riscos else None,
        toques=toques_resumo, poder_mde_vs_v3=poder,
    )


# ---------------------------------------------------------------------------
# relatorio
# ---------------------------------------------------------------------------


def _fmt(v: Optional[float], casas: int = 2) -> str:
    return f"{v:+.{casas}f}" if v is not None else "s/d"


def _formatar_origem(r: ResumoOrigemSuporte) -> list[str]:
    out = [f"## {r.origem}", "",
          f"n sinais V3: {r.n_sinais} | elegiveis (revisita apos caixa formada, antes do gatilho): "
          f"{r.n_elegiveis} | tokens elegiveis: {r.n_tokens_elegiveis}", "",
          f"risco (distancia do stop) medio: {_fmt(r.risco_pct_medio, 1)}%", ""]
    if r.n_elegiveis == 0:
        out.append("(nenhum sinal elegivel nesta origem -- nunca inventado)")
        out.append("")
        return out
    out.append(vv3._formatar_pareamento("entrada no suporte (1a revisita, saida A oficial)", r.suporte))
    out.append(vv3._formatar_pareamento("(a) sinal V3 real (MESMO sinal, saida A oficial)", r.v3))
    out.append(vv3._formatar_pareamento("(b) K=20 entradas aleatorias/sinal (MESMA fase, saida A)",
                                       r.aleatorio))
    out.append(vv3._formatar_pareamento("(c) mesma regra, outras revisitas (quando houver)",
                                       r.outros_instantes))
    for alvo in ALVOS_TOQUE:
        t = r.toques[alvo]
        p = f"{t['p_observado_pct']:.1f}%" if t["p_observado_pct"] is not None else "s/d"
        out.append(f"  toque causal +{alvo:g}R antes de -1R: {p} (n_decididos={t['n_decididos']}, "
                  f"indefinido={t['n_indefinido']})")
    out.append(f"  poder honesto (MDE, 80%/alpha=0,05, vs (a)): "
              f"{_fmt(r.poder_mde_vs_v3)}R" if r.poder_mde_vs_v3 is not None else
              "  poder honesto (MDE): s/d (N insuficiente)")
    out.append("")
    return out


def formatar(resultados: dict[str, dict[str, ResumoOrigemSuporte]]) -> str:
    out = ["# avaliar_entrada_suporte -- hipotese EXPLORATORIA de ENTRADA, nao condicionado", "",
          f"AVISO: {AVISO}", ""]
    for horizonte in HORIZONTES_S:
        out.append(f"# horizonte {horizonte}")
        out.append("")
        for origem in ("ao_vivo", "retro_lote1", "replay_v3"):
            out.extend(_formatar_origem(resultados[horizonte][origem]))
    return "\n".join(out)


def executar(db_path: Path, progresso: bool = True, min_ram_mb: float = RAM_MINIMA_MB_PADRAO,
            veto: str = "amplo") -> str:
    import sys as _sys
    vv3.checar_ram_ou_abortar(min_ram_mb)

    def status(msg: str) -> None:
        if progresso:
            print(f"[avaliar_entrada_suporte] {msg}", file=_sys.stderr, flush=True)

    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        garantir_entrada_suporte_registrada(storage)
    finally:
        storage.close()

    now = time.time()
    status(f"veto de candle corrompido: {veto}")
    status("carregando ao_vivo...")
    ao_vivo = rsf.carregar_ao_vivo(db_path, veto=veto)
    status(f"ao_vivo: {len(ao_vivo)} sinais. carregando retro_lote1...")
    retro = vv3.carregar_retro_lote1(db_path, veto=veto)
    status(f"retro_lote1: {len(retro)} sinais. carregando replay_v3 (pode levar um tempo -- replay "
          "completo de todos os pools admitidos)...")
    replay = vv3.carregar_universo_admitido(db_path, veto=veto)
    status(f"replay_v3: {len(replay)} sinais. localizando revisitas e agregando (pode ser lento -- "
          "reexecuta o detector por sinal)...")

    origens = {"ao_vivo": ao_vivo, "retro_lote1": retro, "replay_v3": replay}
    resultados: dict[str, dict[str, ResumoOrigemSuporte]] = {h: {} for h in HORIZONTES_S}
    for horizonte in HORIZONTES_S:
        for nome, sinais in origens.items():
            resultados[horizonte][nome] = agregar_origem_suporte(sinais, nome, horizonte, now, veto)
            status(f"{nome} ({horizonte}) agregado.")
    status("montando relatorio.")
    return formatar(resultados)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hipotese EXPLORATORIA 'entrada no suporte' -- PAPER/so leitura/NUNCA entra no "
                    "N=30 nem na H1.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--sem-progresso", action="store_true", help="nao imprime progresso em stderr")
    parser.add_argument("--min-ram-mb", type=float, default=RAM_MINIMA_MB_PADRAO,
                        help="aborta se a RAM disponivel ficar abaixo disso (MB)")
    parser.add_argument("--veto", choices=("simples", "amplo"), default="amplo",
                        help="veto de candle corrompido usado em todo o caminho (padrao: amplo)")
    args = parser.parse_args(argv)
    print(executar(args.db, progresso=not args.sem_progresso, min_ram_mb=args.min_ram_mb,
                   veto=args.veto))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
