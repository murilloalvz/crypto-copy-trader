"""PEDIDO 2026-11-10 (autorizado, rodada 13): roda a grade FECHADA de 24 variantes de saída PARCIAL
antecipada (pré-registrada em `docs/pos-runner-v3/PREREGISTRO_SAIDAS_PARCIAIS_2026-11-10.md`, hash
congelado por `garantir_saidas_parciais_registrada`) sobre os sinais V3 JÁ EXISTENTES --
`ao_vivo`/`retro_lote1`/`replay_v3`, SEPARADOS, nunca somados. SOMENTE LEITURA no banco do bot (zero
chamada de rede, zero escrita em `pr3_signals`/alertas/trajetória -- só em `meta`, via
`garantir_saidas_parciais_registrada`). PAPER/READ-ONLY. Detector/simulate/ParamsV3/H1/critério de
sinal NUNCA alterados.

Horizontes 72h/7d (`horizonte_fixo.HORIZONTES_S`). Por variante × horizonte × origem: decomposição
(P(TP1), R médio da perna 1 dado TP1, R médio da perna do restante dado que chegou à fase 2, R médio
de quem nunca realiza TP1), média/mediana/sem-top-3/leave-one-token-out/IC90% bootstrap (10k
reamostras, semente fixa -- MESMOS defaults de `analise.condicional`) sobre TODOS os sinais com
horizonte vencido, sensibilidade de custo (slippage de saída 1x/2x/3x), atribuição (MESMA variante
aplicada aos 10 controles pareados e a K=20 entradas aleatórias, via `varredura_v3._controles_indices`/
`_aleatorios_indices`/`_evento_controle_sinal`, sem duplicar lógica), Holm-Bonferroni (α=0,05, família
de 24 variantes, por origem, no horizonte 72h) e uma checagem de sanidade contra B3b (a) -- "sobre
TODOS" (`auditoria_fidelidade_v3._r_b3b_variante_todos`, rodada 12 Parte 4a), nunca uma validação
formal (gatilho/restante não são idênticos).

Reusa `SinalVarredura`/`carregar_universo_admitido`/`carregar_retro_lote1`/`_controles_indices`/
`_aleatorios_indices`/`_evento_controle_sinal`/`_resumir_pareamento` de `varredura_v3.py`, o loader
`ao_vivo` de `retrospectivo_saida_fiel.py`, e `_de_sinal_varredura`/`_r_b3b_variante_todos` de
`auditoria_fidelidade_v3.py` -- zero duplicação de replay/estatística.

Uso (na VM, a partir da raiz do repo -- replay completo, RAM/CPU fracos):
    nice -n 19 tmux new-session -d -s grade_saidas_parciais \
        'python -m signals_mvp.scripts.grade_saidas_parciais --db signals_mvp/dados/estado.sqlite \
         2>&1 | tee grade_saidas_parciais.log'
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import statistics
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ..analise.condicional import N_BOOTSTRAP_PADRAO, SEED_PADRAO, holm_bonferroni
from ..config import make_paths
from ..pos_runner.costs import CostModel
from ..pos_runner.horizonte_fixo import HORIZONTES_S
from ..pos_runner.params_v3 import load_params_v3
from ..pos_runner.saidas_parciais import (
    GRADE_24,
    VarianteSaidaParcial,
    calcular_r_variante,
    garantir_saidas_parciais_registrada,
)
from ..storage import Storage
from . import auditoria_fidelidade_v3 as afv
from . import retrospectivo_saida_fiel as rsf
from . import varredura_v3 as vv3

AVISO = ("EXPLORATORIO -- motivado por achados ja vistos (B3b (a) = -0,15R sobre TODOS, rodada 12 "
        "Parte 4a); grade NAO CONDICIONADA sobre dados DENTRO DA AMOSTRA, nunca confirmatoria, nunca "
        "entra no N=30 nem na H1. ao_vivo/retro_lote1/replay_v3 SEPARADOS, nunca somados. Resultado "
        "em paper, TETO de execucao -- vies de sobrevivencia. Grade FECHADA de 24 variantes -- "
        "nenhuma e escolhida como vencedora aqui.")

RAM_MINIMA_MB_PADRAO = vv3.RAM_MINIMA_MB_PADRAO
SLIPPAGE_MULTS: tuple[float, ...] = (1.0, 2.0, 3.0)


# ---------------------------------------------------------------------------
# estatisticas por variante (reusa vv3._resumir_pareamento, so adiciona leave-one-token-out)
# ---------------------------------------------------------------------------


def _leave_one_token_out_pior_caso(valores_por_token: dict[str, list[float]]) -> Optional[float]:
    """Pior caso (minimo) da media recalculada removendo, um por vez, TODOS os valores de UM token --
    generaliza o leave-one-out de 1 trade (Emenda 1) pra unidade de TOKEN (a unidade de correlacao/
    acaso ja usada em todo o resto do projeto -- bootstrap/Holm por token)."""
    chaves = list(valores_por_token)
    if len(chaves) < 2:
        return None
    medias: list[float] = []
    for excluir in chaves:
        resto = [v for t in chaves if t != excluir for v in valores_por_token[t]]
        if resto:
            medias.append(statistics.fmean(resto))
    return min(medias) if medias else None


@dataclasses.dataclass
class PareamentoVariante:
    media: Optional[float]
    mediana: Optional[float]
    sem_top3: Optional[float]
    leave_one_token_out_pior_caso: Optional[float]
    ic90_bootstrap: Optional[tuple[float, float]]
    n: int
    n_tokens: int


def _resumir_variante(valores_por_token: dict[str, list[float]]) -> PareamentoVariante:
    base = vv3._resumir_pareamento(valores_por_token)
    return PareamentoVariante(base.media, base.mediana, base.sem_top3,
                              _leave_one_token_out_pior_caso(valores_por_token),
                              base.ic90_bootstrap, base.n, len(valores_por_token))


def _bootstrap_p_valor_por_token(valores_por_token: dict[str, list[float]],
                                 n_bootstrap: int = N_BOOTSTRAP_PADRAO, seed: int = SEED_PADRAO
                                 ) -> Optional[float]:
    """MESMA matematica de `analise.condicional.bootstrap_p_valor_unilateral` (P(media bootstrap <=
    0), blocos por token), generalizada pra dict{token:[valores]} em vez de `SinalResolvido` -- nunca
    um metodo estatistico novo."""
    chaves = sorted(valores_por_token)
    n = len(chaves)
    if n == 0:
        return None
    rng = np.random.default_rng(seed)
    medias = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        escolhidos = rng.integers(0, n, size=n)
        valores = [v for idx in escolhidos for v in valores_por_token[chaves[idx]]]
        medias[i] = float(np.mean(valores)) if valores else 0.0
    return float(np.mean(medias <= 0.0))


# ---------------------------------------------------------------------------
# decomposicao + agregacao por variante
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class DecomposicaoVariante:
    n_pendente: int
    n_sem_dado: int
    n_vencido: int
    n_tp1: int
    p_tp1_pct: Optional[float]
    r_leg1_medio: Optional[float]
    r_leg2_medio: Optional[float]
    r_medio_sem_tp1: Optional[float]


@dataclasses.dataclass
class ResumoVariante:
    nome: str
    decomposicao: DecomposicaoVariante
    saida: PareamentoVariante
    saida_slip2x: PareamentoVariante
    saida_slip3x: PareamentoVariante
    controles: PareamentoVariante
    aleatorio: PareamentoVariante
    dif_pareada_por_token: dict[str, list[float]] = dataclasses.field(default_factory=dict)
    p_valor_holm: Optional[float] = None
    significativo_holm: Optional[bool] = None


def _calcular_variante_sobre_sinais(
    sinais: list[vv3.SinalVarredura], variante: VarianteSaidaParcial, horizonte_s: float, now: float,
    params: Any, costs: CostModel, veto: str = "amplo",
) -> ResumoVariante:
    n_pendente = n_sem_dado = n_vencido = n_tp1 = 0
    leg1_vals: list[float] = []
    leg2_vals: list[float] = []
    sem_tp1_vals: list[float] = []
    valores_por_token: dict[str, list[float]] = {}
    valores_por_token_2x: dict[str, list[float]] = {}
    valores_por_token_3x: dict[str, list[float]] = {}
    valores_controles: dict[str, list[float]] = {}
    valores_aleatorio: dict[str, list[float]] = {}
    dif_pareada_por_token: dict[str, list[float]] = {}

    for s in sinais:
        r1x = calcular_r_variante(s.bars, s.ev, costs, s.dex, s.l_bc, s.t_entrada, horizonte_s, now,
                                  variante, slippage_saida_mult=1.0, veto=veto)
        if r1x.status == "pendente":
            n_pendente += 1
            continue
        if r1x.status == "sem_dado":
            n_sem_dado += 1
            continue
        n_vencido += 1
        if r1x.tp1_realizado:
            n_tp1 += 1
            if r1x.r_leg1 is not None:
                leg1_vals.append(r1x.r_leg1)
            if r1x.r_leg2 is not None:
                leg2_vals.append(r1x.r_leg2)
        elif r1x.r_mult is not None:
            sem_tp1_vals.append(r1x.r_mult)
        if r1x.r_mult is not None:
            valores_por_token.setdefault(s.token, []).append(r1x.r_mult)
            r2x = calcular_r_variante(s.bars, s.ev, costs, s.dex, s.l_bc, s.t_entrada, horizonte_s, now,
                                      variante, slippage_saida_mult=2.0, veto=veto)
            r3x = calcular_r_variante(s.bars, s.ev, costs, s.dex, s.l_bc, s.t_entrada, horizonte_s, now,
                                      variante, slippage_saida_mult=3.0, veto=veto)
            if r2x.r_mult is not None:
                valores_por_token_2x.setdefault(s.token, []).append(r2x.r_mult)
            if r3x.r_mult is not None:
                valores_por_token_3x.setdefault(s.token, []).append(r3x.r_mult)

        # Atribuicao: MESMA variante aplicada aos 10 controles e aos K=20 aleatorios do MESMO sinal.
        valores_controles_sinal: list[float] = []
        for idx in vv3._controles_indices(s, params):
            ev_c = vv3._evento_controle_sinal(s, idx)
            if ev_c is None:
                continue
            r_c = calcular_r_variante(s.bars, ev_c, costs, s.dex, s.l_bc, s.bars[idx].ts, horizonte_s,
                                      now, variante, veto=veto)
            if r_c.r_mult is not None:
                valores_controles.setdefault(s.token, []).append(r_c.r_mult)
                valores_controles_sinal.append(r_c.r_mult)
        for idx in vv3._aleatorios_indices(s, params):
            ev_r = vv3._evento_controle_sinal(s, idx)
            if ev_r is None:
                continue
            r_r = calcular_r_variante(s.bars, ev_r, costs, s.dex, s.l_bc, s.bars[idx].ts, horizonte_s,
                                      now, variante, veto=veto)
            if r_r.r_mult is not None:
                valores_aleatorio.setdefault(s.token, []).append(r_r.r_mult)
        if r1x.r_mult is not None and valores_controles_sinal:
            dif = r1x.r_mult - statistics.fmean(valores_controles_sinal)
            dif_pareada_por_token.setdefault(s.token, []).append(dif)

    p_tp1 = (100.0 * n_tp1 / n_vencido) if n_vencido else None
    decomposicao = DecomposicaoVariante(
        n_pendente=n_pendente, n_sem_dado=n_sem_dado, n_vencido=n_vencido, n_tp1=n_tp1,
        p_tp1_pct=p_tp1, r_leg1_medio=(statistics.fmean(leg1_vals) if leg1_vals else None),
        r_leg2_medio=(statistics.fmean(leg2_vals) if leg2_vals else None),
        r_medio_sem_tp1=(statistics.fmean(sem_tp1_vals) if sem_tp1_vals else None),
    )
    return ResumoVariante(
        nome=variante.nome, decomposicao=decomposicao, saida=_resumir_variante(valores_por_token),
        saida_slip2x=_resumir_variante(valores_por_token_2x),
        saida_slip3x=_resumir_variante(valores_por_token_3x),
        controles=_resumir_variante(valores_controles), aleatorio=_resumir_variante(valores_aleatorio),
        dif_pareada_por_token=dif_pareada_por_token,
    )


@dataclasses.dataclass
class ResumoOrigemGrade:
    origem: str
    n_sinais: int
    n_tokens: int
    por_horizonte: dict[str, dict[str, ResumoVariante]]   # horizonte -> nome_variante -> resumo
    b3b_a_sobre_todos_72h: Optional[float]


def agregar_origem_grade(sinais: list[vv3.SinalVarredura], origem_label: str, now: float,
                         veto: Optional[str] = None) -> ResumoOrigemGrade:
    """RODADA 18 (item 2): `veto` None preserva o comportamento historico de cada chamada interna
    (`_calcular_variante_sobre_sinais` ja usa 'amplo' por padrao -- herdado de `calcular_r_horizonte`
    desde a rodada 17); um valor explicito ('simples'/'amplo') forca o mesmo veto em toda a grade."""
    kwargs_veto = {"veto": veto} if veto is not None else {}
    params = load_params_v3()
    costs = CostModel()
    por_horizonte: dict[str, dict[str, ResumoVariante]] = {}
    for horizonte, horizonte_s in HORIZONTES_S.items():
        resumos: dict[str, ResumoVariante] = {}
        for variante in GRADE_24:
            resumos[variante.nome] = _calcular_variante_sobre_sinais(sinais, variante, horizonte_s,
                                                                     now, params, costs, **kwargs_veto)
        if horizonte == "72h":
            p_valores = [_bootstrap_p_valor_por_token(resumos[v.nome].dif_pareada_por_token) or 1.0
                        for v in GRADE_24]
            significativos = holm_bonferroni(p_valores)
            for i, v in enumerate(GRADE_24):
                resumos[v.nome].p_valor_holm = p_valores[i]
                resumos[v.nome].significativo_holm = significativos[i]
        por_horizonte[horizonte] = resumos

    b3b_72h: Optional[float] = None
    sinais_auditoria = [afv._de_sinal_varredura(s, s.origem) for s in sinais]
    sinais_auditoria = [s for s in sinais_auditoria if s is not None]
    if sinais_auditoria:
        valores_b3b: dict[str, list[float]] = {}
        for s in sinais_auditoria:
            rb = afv._r_b3b_variante_todos(s, HORIZONTES_S["72h"], now, params)
            if rb.r_mult is not None:
                valores_b3b.setdefault(s.token, []).append(rb.r_mult)
        todos = [v for lst in valores_b3b.values() for v in lst]
        b3b_72h = statistics.fmean(todos) if todos else None

    return ResumoOrigemGrade(origem=origem_label, n_sinais=len(sinais),
                             n_tokens=len({s.token for s in sinais}), por_horizonte=por_horizonte,
                             b3b_a_sobre_todos_72h=b3b_72h)


# ---------------------------------------------------------------------------
# relatorio + CSV
# ---------------------------------------------------------------------------


def _fmt(v: Optional[float], casas: int = 2) -> str:
    return f"{v:+.{casas}f}" if v is not None else "s/d"


def _formatar_variante(r: ResumoVariante) -> list[str]:
    d = r.decomposicao
    out = [f"  ## {r.nome}",
          f"     pendente={d.n_pendente} | sem_dado={d.n_sem_dado} | vencido={d.n_vencido} | "
          f"TP1={d.n_tp1} ({_fmt(d.p_tp1_pct, 1)}%)",
          f"     decomposicao: R perna1|TP1={_fmt(d.r_leg1_medio)} | R perna2|fase2="
          f"{_fmt(d.r_leg2_medio)} | R|sem_TP1={_fmt(d.r_medio_sem_tp1)}"]
    for label, p in (("saida (1x)", r.saida), ("saida (slip 2x)", r.saida_slip2x),
                     ("saida (slip 3x)", r.saida_slip3x), ("controles (10/token)", r.controles),
                     ("aleatorio (K=20)", r.aleatorio)):
        ic = (f"[{p.ic90_bootstrap[0]:+.2f},{p.ic90_bootstrap[1]:+.2f}]" if p.ic90_bootstrap else "s/d")
        out.append(f"     {label} (n={p.n}, tokens={p.n_tokens}): media={_fmt(p.media)} | "
                  f"mediana={_fmt(p.mediana)} | sem-top3={_fmt(p.sem_top3)} | "
                  f"leave-1-token-out(pior)={_fmt(p.leave_one_token_out_pior_caso)} | IC90%={ic}")
    if r.p_valor_holm is not None:
        out.append(f"     Holm: p={r.p_valor_holm:.4f} | significativo(alpha=0,05, familia=24)="
                  f"{r.significativo_holm}")
    return out


def _formatar_origem(r: ResumoOrigemGrade) -> list[str]:
    out = [f"## {r.origem}", "", f"n sinais: {r.n_sinais} | tokens distintos: {r.n_tokens}", ""]
    if r.n_sinais == 0:
        out.append("(sem sinais nesta origem)")
        out.append("")
        return out
    out.append(f"checagem de sanidade -- B3b (a) sobre TODOS, 72h (rodada 12 Parte 4a): "
              f"{_fmt(r.b3b_a_sobre_todos_72h)} (referencia ja medida: -0,15R; gatilho/restante "
              f"NAO identicos a nenhuma variante desta grade -- comparar com topo_caixa_f30_breakeven "
              f"abaixo e´ so qualitativo, nunca uma validacao)")
    out.append("")
    for horizonte in HORIZONTES_S:
        out.append(f"### horizonte {horizonte} (nº bruto de variantes testadas: {len(GRADE_24)})")
        for variante in GRADE_24:
            out.extend(_formatar_variante(r.por_horizonte[horizonte][variante.nome]))
        out.append("")
    return out


def formatar(ao_vivo: ResumoOrigemGrade, retro: ResumoOrigemGrade, replay: ResumoOrigemGrade) -> str:
    out = ["# grade_saidas_parciais -- 24 variantes de saida parcial antecipada, nao condicionado", "",
          f"AVISO: {AVISO}", ""]
    for r in (ao_vivo, retro, replay):
        out.extend(_formatar_origem(r))
    return "\n".join(out)


def _linhas_csv(r: ResumoOrigemGrade) -> list[dict[str, Any]]:
    linhas: list[dict[str, Any]] = []
    for horizonte in HORIZONTES_S:
        for variante in GRADE_24:
            v = r.por_horizonte[horizonte][variante.nome]
            d = v.decomposicao
            linhas.append({
                "origem": r.origem, "horizonte": horizonte, "variante": v.nome,
                "n_pendente": d.n_pendente, "n_sem_dado": d.n_sem_dado, "n_vencido": d.n_vencido,
                "n_tp1": d.n_tp1, "p_tp1_pct": d.p_tp1_pct, "r_leg1_medio": d.r_leg1_medio,
                "r_leg2_medio": d.r_leg2_medio, "r_medio_sem_tp1": d.r_medio_sem_tp1,
                "media": v.saida.media, "mediana": v.saida.mediana, "sem_top3": v.saida.sem_top3,
                "leave_1_token_out_pior": v.saida.leave_one_token_out_pior_caso,
                "media_slip2x": v.saida_slip2x.media, "media_slip3x": v.saida_slip3x.media,
                "media_controles": v.controles.media, "media_aleatorio": v.aleatorio.media,
                "p_valor_holm": v.p_valor_holm, "significativo_holm": v.significativo_holm,
            })
    return linhas


def _escrever_csv(path: Path, linhas: list[dict[str, Any]]) -> None:
    if not linhas:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(linhas[0]))
        writer.writeheader()
        writer.writerows(linhas)


def executar(db_path: Path, csv_path: Optional[Path] = None, progresso: bool = True,
            min_ram_mb: float = RAM_MINIMA_MB_PADRAO, veto: str = "amplo") -> str:
    """RODADA 18 (item 2): `veto` ('amplo' padrao DESTE SCRIPT/CLI) decide o veto de candle
    corrompido em todo o caminho (entrada corrigida nos loaders + todas as 24 variantes). Alem do
    relatorio normal, reporta tambem as mesmas metricas EXCLUINDO `vv3.TOKENS_EXCLUIDOS_DIAGNOSTICO`
    (leave-token-out, ex.: PEAK/HIGH)."""
    import sys as _sys
    vv3.checar_ram_ou_abortar(min_ram_mb)

    def status(msg: str) -> None:
        if progresso:
            print(f"[grade_saidas_parciais] {msg}", file=_sys.stderr, flush=True)

    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        garantir_saidas_parciais_registrada(storage)
    finally:
        storage.close()

    now = time.time()
    status(f"veto de candle corrompido: {veto}")
    status("carregando ao_vivo...")
    ao_vivo = rsf.carregar_ao_vivo(db_path)
    status(f"ao_vivo: {len(ao_vivo)} sinais. carregando retro_lote1...")
    retro = vv3.carregar_retro_lote1(db_path, veto=veto)
    status(f"retro_lote1: {len(retro)} sinais. carregando replay_v3 (pode levar um tempo -- replay "
          "completo de todos os pools admitidos)...")
    replay = vv3.carregar_universo_admitido(db_path, veto=veto)
    status(f"replay_v3: {len(replay)} sinais. agregando (24 variantes x 2 horizontes x controles x "
          "aleatorio x 3 niveis de custo -- pode levar bastante tempo)...")
    r_ao_vivo = agregar_origem_grade(ao_vivo, "ao_vivo", now, veto=veto)
    status("ao_vivo agregado.")
    r_retro = agregar_origem_grade(retro, "retro_lote1", now, veto=veto)
    status("retro_lote1 agregado.")
    r_replay = agregar_origem_grade(replay, "replay_v3", now, veto=veto)
    status("replay_v3 agregado. agregando leave-token-out (sem PEAK/HIGH)...")
    sufixo = f"_sem_{'_'.join(vv3.TOKENS_EXCLUIDOS_DIAGNOSTICO)}"
    r_ao_vivo_lto = agregar_origem_grade(vv3._sem_outliers(ao_vivo, vv3.TOKENS_EXCLUIDOS_DIAGNOSTICO),
                                         "ao_vivo" + sufixo, now, veto=veto)
    r_retro_lto = agregar_origem_grade(vv3._sem_outliers(retro, vv3.TOKENS_EXCLUIDOS_DIAGNOSTICO),
                                       "retro_lote1" + sufixo, now, veto=veto)
    r_replay_lto = agregar_origem_grade(vv3._sem_outliers(replay, vv3.TOKENS_EXCLUIDOS_DIAGNOSTICO),
                                        "replay_v3" + sufixo, now, veto=veto)
    status("leave-token-out agregado. montando relatorio.")
    texto = formatar(r_ao_vivo, r_retro, r_replay)
    texto += ("\n\n# leave-token-out (sem " + ", ".join(vv3.TOKENS_EXCLUIDOS_DIAGNOSTICO) + ")\n\n" +
             formatar(r_ao_vivo_lto, r_retro_lto, r_replay_lto))
    if csv_path is not None:
        linhas = (_linhas_csv(r_ao_vivo) + _linhas_csv(r_retro) + _linhas_csv(r_replay) +
                 _linhas_csv(r_ao_vivo_lto) + _linhas_csv(r_retro_lto) + _linhas_csv(r_replay_lto))
        _escrever_csv(csv_path, linhas)
        texto += f"\n(tabela tambem gravada em {csv_path})"
    return texto


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Grade fechada de 24 variantes de saida parcial antecipada -- PAPER/so leitura/"
                    "EXPLORATORIO.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--csv", type=Path, default=None, help="grava a tabela por variante em CSV")
    parser.add_argument("--sem-progresso", action="store_true", help="nao imprime progresso em stderr")
    parser.add_argument("--min-ram-mb", type=float, default=RAM_MINIMA_MB_PADRAO,
                        help="aborta se a RAM disponivel ficar abaixo disso (MB)")
    parser.add_argument("--veto", choices=("simples", "amplo"), default="amplo",
                        help="veto de candle corrompido usado em todo o caminho (padrao: amplo)")
    args = parser.parse_args(argv)
    print(executar(args.db, csv_path=args.csv, progresso=not args.sem_progresso,
                   min_ram_mb=args.min_ram_mb, veto=args.veto))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
