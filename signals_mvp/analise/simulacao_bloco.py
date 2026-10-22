"""Monte Carlo em blocos para a POS-RUNNER-V1 congelada (PAPER / somente leitura).

Projeta a trajetoria futura da banca real (`bankroll_v1`) a partir dos trades que JA fecharam ao
vivo, sem inventar nenhuma regra nova de entrada/saida/tamanho -- so estatistica sobre o que ja
aconteceu. Nunca executa ordem, nunca le chave privada.

Fontes de dado (sempre filtradas para a versao congelada `VERSAO_CONGELADA` = hash de
`pos_runner_v1.yaml`):
  - `pos_runner_v1.csv`    -- um sinal por linha (inclusive em aberto); da o `risco_pct` de cada trade.
  - `pos_runner_v1_banca.csv` -- um trade real de banca por sinal FECHADO (inclusive os "pulado: ..."
    / "sem dado: ..." que a trava de banca recusou); da o resultado liquido JA com slippage/custos reais.
  - tabela `pr1_feedback` (SQLite) -- so contexto para o relatorio (votos do operador); nunca entra
    na conta estatistica.

Join: nem o CSV de sinais nem o de banca tem uma chave literal compartilhada (so o SQLite tem
`pr1_signal_id`). Mas `BankrollLedgerV1.step` roda exatamente 1x por sinal FECHADO, na mesma ordem
cronologica em que `pos_runner_v1.csv` lista os sinais fechados daquele (contrato, tf) -- entao as
duas listas, agrupadas por (contrato, tf) e ordenadas por data, casam posicao a posicao. Se as
contagens de um grupo nao baterem, a carga se recusa (nunca casa no "chute").

Algoritmo do Monte Carlo (por rodada):
  1. sorteia uma taxa de acerto `p_win ~ Beta(n_ganhos+1, n_perdas+1)` UMA vez (incerteza do edge);
  2. para cada semana simulada, sorteia a quantidade de sinais da semana (Poisson ou binomial
     negativa, calibrada pela frequencia semanal observada -- nunca fixa);
  3. preenche a semana sorteando DIAS HISTORICOS inteiros (bloco por dia, com reposicao) at'e atingir
     a meta -- isso preserva o agrupamento real de quantos sinais caem no mesmo dia (dias ruins tem
     peso 2x no cenario de estresse); cada bloco cai num dia simulado novo e distinto;
  4. cada sinal dentro do bloco tem seu resultado resorteado: Bernoulli(p_win) decide ganho/perda,
     e o tamanho (R-multiplo + risco + tempo no trade) vem de bootstrap do pool historico de ganhos
     ou de perdas (o par R-multiplo/risco sempre vem do MESMO trade real -- nunca se mistura R de um
     trade com o risco de outro);
  5. cada sinal passa pelas travas REAIS da banca (`tamanho_posicao_usd`, limite de posicoes, stop
     diario/semanal) -- importadas de `bankroll_v1`/`params_v1`, nunca duplicadas aqui.

Seed fixa (`SEED_PADRAO`): a mesma entrada sempre produz a mesma saida.
"""

from __future__ import annotations

import argparse
import csv
import math
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

from ..config import Paths, make_paths
from ..pos_runner.bankroll_v1 import HEADER_LABELS as _BANCA_HEADER_LABELS
from ..pos_runner.bankroll_v1 import COLUMNS as _BANCA_COLUMNS
from ..pos_runner.bankroll_v1 import _dia_utc, _semana_utc, tamanho_posicao_usd
from ..pos_runner.params_v1 import ParamsV1, load_params_v1
from ..util import parse_iso

VERSAO_CONGELADA = "279b79ffa3f0"  # hash da V1 congelada em 2026-10-22 (FASE 1.1); ver pos_runner_v1.yaml
MIN_TRADES_FECHADOS = 30
SEED_PADRAO = 20_261_022
N_SIMULACOES_PADRAO = 5_000
N_SEMANAS_PADRAO = 26  # horizonte de projecao (~6 meses de semanas simuladas)
N_BOOTSTRAP_EXPECTANCIA_PADRAO = 10_000
SEGUNDOS_POR_DIA = 86_400.0
_Z_95 = 1.959963984540054  # quantil normal para IC ~95% (sem depender de scipy)


class RecusaAmostraInsuficiente(RuntimeError):
    """Levantado quando ha menos de MIN_TRADES_FECHADOS trades fechados da versao congelada."""


# ---------------------------------------------------------------------------
# carga e juncao dos dados reais
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TradeRealizado:
    """Um trade de banca real (ja fechado), com o risco do sinal que o originou."""

    contrato: str
    tf: str
    data_entrada: float  # timestamp UTC (epoch segundos)
    tamanho_posicao_usd: float
    resultado_usd: float
    lucro_liquido_pct: float  # fracao em %, ja com slippage/custos reais (ex.: -18.0)
    risco_pct: float  # fracao em %, distancia entrada->stop do sinal (ex.: 18.3)
    tempo_no_trade_h: float

    @property
    def r_multiplo(self) -> float:
        """PnL realizado dividido pelo risco do trade (R = lucro_liquido_% / risco_%)."""
        return self.lucro_liquido_pct / self.risco_pct

    @property
    def dia_utc(self) -> str:
        return _dia_utc(self.data_entrada)

    @property
    def semana_utc(self) -> str:
        return _semana_utc(self.data_entrada)


@dataclass(frozen=True)
class _SinalFechado:
    contrato: str
    tf: str
    data_ts: float
    risco_pct: Optional[float]
    versao_config_v1: str


@dataclass(frozen=True)
class _TradeBanca:
    contrato: str
    tf: str
    data_entrada_ts: float
    tamanho_posicao_usd: Optional[float]
    resultado_usd: Optional[float]
    lucro_liquido_pct: Optional[float]
    tempo_no_trade_h: Optional[float]


def _ler_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _carregar_sinais_fechados(path: Path) -> dict[tuple[str, str], list[_SinalFechado]]:
    """Agrupa por (contrato, tf) TODOS os sinais fechados (qualquer versao -- o filtro de versao
    acontece depois de casar com a banca, pra nao desalinhar a posicao do zip)."""
    grupos: dict[tuple[str, str], list[_SinalFechado]] = defaultdict(list)
    for row in _ler_csv(path):
        motivo = (row.get("motivo_saida") or "").strip()
        if motivo in ("", "em_aberto"):
            continue
        contrato = row.get("contrato") or ""
        tf = row.get("tf") or ""
        data_ts = parse_iso(row.get("data"))
        if not contrato or not tf or data_ts is None:
            continue
        grupos[(contrato, tf)].append(_SinalFechado(
            contrato=contrato, tf=tf, data_ts=data_ts,
            risco_pct=_num(row.get("risco_pct")),
            versao_config_v1=row.get("versao_config_v1") or "",
        ))
    for chave in grupos:
        grupos[chave].sort(key=lambda s: s.data_ts)
    return grupos


def _carregar_banca(path: Path) -> dict[tuple[str, str], list[_TradeBanca]]:
    """Agrupa por (contrato, tf) TODAS as linhas da banca (inclusive "pulado"/"sem dado" -- elas
    tambem correspondem a 1 sinal fechado e precisam entrar no zip pra manter o alinhamento)."""
    reverso = {label: campo for campo, label in _BANCA_HEADER_LABELS.items()}
    grupos: dict[tuple[str, str], list[_TradeBanca]] = defaultdict(list)
    for row_raw in _ler_csv(path):
        row = {reverso.get(k, k): v for k, v in row_raw.items()}
        contrato = row.get("contrato") or ""
        tf = row.get("tf") or ""
        data_ts = parse_iso(row.get("data_entrada"))
        if not contrato or not tf or data_ts is None:
            continue
        grupos[(contrato, tf)].append(_TradeBanca(
            contrato=contrato, tf=tf, data_entrada_ts=data_ts,
            tamanho_posicao_usd=_num(row.get("tamanho_posicao_usd")),
            resultado_usd=_num(row.get("resultado_usd")),
            lucro_liquido_pct=_num(row.get("lucro_liquido_pct")),
            tempo_no_trade_h=_num(row.get("tempo_no_trade_h")),
        ))
    for chave in grupos:
        grupos[chave].sort(key=lambda t: t.data_entrada_ts)
    return grupos


def _juntar(
    sinais: dict[tuple[str, str], list[_SinalFechado]],
    banca: dict[tuple[str, str], list[_TradeBanca]],
    versao: str,
) -> list[TradeRealizado]:
    trades: list[TradeRealizado] = []
    for chave in sorted(set(sinais) | set(banca)):
        grupo_sinais = sinais.get(chave, [])
        grupo_banca = banca.get(chave, [])
        if len(grupo_sinais) != len(grupo_banca):
            contrato, tf = chave
            raise ValueError(
                f"inconsistencia de dados: {contrato} ({tf}) tem {len(grupo_sinais)} sinal(is) fechado(s) "
                f"em pos_runner_v1.csv mas {len(grupo_banca)} linha(s) em pos_runner_v1_banca.csv -- "
                "nao e seguro casar por posicao (um dos dois arquivos pode estar desatualizado ou "
                "truncado); regenere os CSVs (`python -m signals_mvp exportar`) antes de repetir a analise."
            )
        for sinal, linha_banca in zip(grupo_sinais, grupo_banca):
            if sinal.versao_config_v1 != versao:
                continue
            if (linha_banca.tamanho_posicao_usd is None or linha_banca.resultado_usd is None
                    or linha_banca.lucro_liquido_pct is None):
                continue  # "pulado: ..." / "sem dado: ..." -- nao houve trade real
            if not sinal.risco_pct:
                continue  # risco_pct ausente/zero: nao da pra calcular R (missingness explicita)
            trades.append(TradeRealizado(
                contrato=sinal.contrato, tf=sinal.tf, data_entrada=linha_banca.data_entrada_ts,
                tamanho_posicao_usd=linha_banca.tamanho_posicao_usd, resultado_usd=linha_banca.resultado_usd,
                lucro_liquido_pct=linha_banca.lucro_liquido_pct, risco_pct=sinal.risco_pct,
                tempo_no_trade_h=linha_banca.tempo_no_trade_h or 0.0,
            ))
    trades.sort(key=lambda t: t.data_entrada)
    return trades


def _carregar_feedback(db_path: Path, versao: str) -> list[dict[str, Any]]:
    """So contexto para o relatorio (votos/notas do operador); nunca bloqueia a analise."""
    if not db_path.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        return []
    try:
        con.row_factory = sqlite3.Row
        cur = con.execute(
            "SELECT * FROM pr1_feedback WHERE versao_config_v1 = ? ORDER BY atualizado_ts, id", (versao,))
        return [dict(r) for r in cur.fetchall()]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def carregar_trades(paths: Paths, versao: str = VERSAO_CONGELADA) -> tuple[list[TradeRealizado], list[dict[str, Any]]]:
    sinais = _carregar_sinais_fechados(paths.pos_runner_v1_csv)
    banca = _carregar_banca(paths.pos_runner_v1_banca_csv)
    trades = _juntar(sinais, banca, versao)
    feedback = _carregar_feedback(paths.db, versao)
    return trades, feedback


# ---------------------------------------------------------------------------
# estatisticas historicas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EstatisticasHistoricas:
    n_trades: int
    n_ganhos: int
    r_multiplos: np.ndarray
    ganhos: list[TradeRealizado]
    perdas: list[TradeRealizado]
    por_dia: dict[str, list[TradeRealizado]]
    dias_ruins: frozenset[str]


def calcular_estatisticas(trades: Sequence[TradeRealizado]) -> EstatisticasHistoricas:
    r_multiplos = np.array([t.r_multiplo for t in trades], dtype=float)
    ganhos = [t for t in trades if t.r_multiplo > 0]
    perdas = [t for t in trades if t.r_multiplo <= 0]
    por_dia: dict[str, list[TradeRealizado]] = defaultdict(list)
    for t in trades:
        por_dia[t.dia_utc].append(t)
    dias_ruins = frozenset(dia for dia, ts in por_dia.items() if sum(t.r_multiplo for t in ts) < 0)
    return EstatisticasHistoricas(
        n_trades=len(trades), n_ganhos=len(ganhos), r_multiplos=r_multiplos,
        ganhos=ganhos, perdas=perdas, por_dia=dict(por_dia), dias_ruins=dias_ruins,
    )


def _semana_chave_para_segunda(chave: str) -> date:
    ano, semana = chave.split("-W")
    return date.fromisocalendar(int(ano), int(semana), 1)


def _todas_semanas_observadas(trades: Sequence[TradeRealizado]) -> list[int]:
    """Contagem de trades por semana ISO, incluindo semanas SEM nenhum trade (exposicao completa --
    sem isso a taxa semanal fica superestimada)."""
    if not trades:
        return []
    contagem: dict[str, int] = defaultdict(int)
    for t in trades:
        contagem[t.semana_utc] += 1
    semanas = sorted(contagem, key=_semana_chave_para_segunda)
    cursor = _semana_chave_para_segunda(semanas[0])
    fim = _semana_chave_para_segunda(semanas[-1])
    saida = []
    while cursor <= fim:
        iso = cursor.isocalendar()
        saida.append(contagem.get(f"{iso[0]}-W{iso[1]:02d}", 0))
        cursor += timedelta(days=7)
    return saida


@dataclass(frozen=True)
class DistribuicaoFrequencia:
    tipo: str  # "poisson" | "binomial_negativa" | "fixa" (fixa: so para teste, nunca produzida por calibrar_frequencia)
    media: float
    n: Optional[float] = None
    p: Optional[float] = None

    def sortear(self, rng: np.random.Generator, tamanho: int) -> np.ndarray:
        if self.tipo == "fixa":
            return np.full(tamanho, max(0, round(self.media)), dtype=int)
        if self.tipo == "binomial_negativa" and self.n and self.p:
            return rng.negative_binomial(self.n, self.p, size=tamanho)
        return rng.poisson(max(self.media, 1e-9), size=tamanho)


def calibrar_frequencia(contagens_semanais: Sequence[int]) -> DistribuicaoFrequencia:
    """Poisson por padrao; troca pra binomial negativa so se houver superdispersao real
    (variancia > media) na frequencia semanal observada -- nunca uma frequencia fixa."""
    if not contagens_semanais:
        return DistribuicaoFrequencia(tipo="poisson", media=0.0)
    arr = np.asarray(contagens_semanais, dtype=float)
    media = float(arr.mean())
    if len(arr) < 2 or media <= 0:
        return DistribuicaoFrequencia(tipo="poisson", media=max(media, 0.0))
    variancia = float(arr.var(ddof=1))
    if variancia > media * 1.05:
        p = media / variancia
        if 0 < p < 1:
            n = media * p / (1.0 - p)
            if n > 0:
                return DistribuicaoFrequencia(tipo="binomial_negativa", media=media, n=n, p=p)
    return DistribuicaoFrequencia(tipo="poisson", media=media)


# ---------------------------------------------------------------------------
# ledger simulado (mesmas travas de bankroll_v1.BankrollLedgerV1.step, sobre trades sorteados)
# ---------------------------------------------------------------------------


@dataclass
class _EstadoLedgerSim:
    banca: float
    peak_banca: float
    dia_atual: Optional[str] = None
    banca_inicio_dia: float = 0.0
    perdas_seguidas: int = 0
    dia_pausado: bool = False
    semana_atual: Optional[str] = None
    banca_inicio_semana: float = 0.0
    semana_pausada: bool = False
    maior_queda_pct: float = 0.0
    tocou_50pct: bool = False
    open_positions: list[tuple[float, float]] = field(default_factory=list)

    @classmethod
    def novo(cls, banca_inicial: float) -> "_EstadoLedgerSim":
        return cls(banca=banca_inicial, peak_banca=banca_inicial,
                   banca_inicio_dia=banca_inicial, banca_inicio_semana=banca_inicial)


def _aplicar_trade(
    estado: _EstadoLedgerSim, entry_ts: float, dia_chave: str, semana_chave: str,
    amostra: TradeRealizado, params: ParamsV1, banca_inicial: float,
) -> bool:
    """Um passo do ledger simulado sobre um trade sorteado. Devolve True se foi executado (False
    se as travas pularam). Mesma ordem/condicoes de BankrollLedgerV1.step, nunca duplicando valores
    de parametro (so a logica de controle, reaplicada sobre dados sinteticos)."""
    if dia_chave != estado.dia_atual:
        estado.dia_atual, estado.banca_inicio_dia, estado.perdas_seguidas, estado.dia_pausado = (
            dia_chave, estado.banca, 0, False)
    if semana_chave != estado.semana_atual:
        estado.semana_atual, estado.banca_inicio_semana, estado.semana_pausada = (
            semana_chave, estado.banca, False)
    estado.open_positions = [p for p in estado.open_positions if p[1] > entry_ts]
    if estado.semana_pausada or estado.dia_pausado or len(estado.open_positions) >= params.max_posicoes_abertas:
        return False
    position_usd = tamanho_posicao_usd(estado.banca, params)
    if position_usd <= 0:
        return False
    net_ret = amostra.lucro_liquido_pct / 100.0
    resultado_usd = position_usd * net_ret
    exit_ts = entry_ts + max(amostra.tempo_no_trade_h, 0.0) * 3600.0
    estado.open_positions.append((entry_ts, exit_ts))
    estado.banca += resultado_usd
    if resultado_usd > 0:
        estado.perdas_seguidas = 0
    else:
        estado.perdas_seguidas += 1
    estado.peak_banca = max(estado.peak_banca, estado.banca)
    queda_pct = 100.0 * (estado.peak_banca - estado.banca) / estado.peak_banca if estado.peak_banca > 0 else 0.0
    estado.maior_queda_pct = max(estado.maior_queda_pct, queda_pct)
    if estado.banca <= 0.5 * banca_inicial:
        estado.tocou_50pct = True
    if (estado.banca - estado.banca_inicio_dia <= -params.stop_diario_frac * estado.banca_inicio_dia
            or estado.perdas_seguidas >= params.stop_diario_perdas_seguidas):
        estado.dia_pausado = True
    if estado.banca - estado.banca_inicio_semana <= -params.stop_semanal_frac * estado.banca_inicio_semana:
        estado.semana_pausada = True
    return True


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultadoRodada:
    banca_final: float
    maior_queda_pct: float
    tocou_50pct: bool


def _preparar_dias(por_dia: dict[str, list[TradeRealizado]]) -> list[str]:
    return sorted(por_dia)


def _pesos_dias(dias: list[str], dias_ruins: frozenset[str], peso_stress: float) -> np.ndarray:
    pesos = np.array([peso_stress if d in dias_ruins else 1.0 for d in dias], dtype=float)
    return pesos / pesos.sum()


def _simular_uma_rodada(
    rng: np.random.Generator, params: ParamsV1, stats: EstatisticasHistoricas,
    dist_freq: DistribuicaoFrequencia, n_semanas: int, dias: list[str], pesos_dias: np.ndarray,
) -> ResultadoRodada:
    p_win = rng.beta(stats.n_ganhos + 1, (stats.n_trades - stats.n_ganhos) + 1)
    estado = _EstadoLedgerSim.novo(params.banca_inicial_usd)
    sim_ts = 0.0
    contagens_alvo = dist_freq.sortear(rng, n_semanas)
    for semana_idx, alvo in enumerate(contagens_alvo):
        alvo = int(alvo)
        semana_chave = f"s{semana_idx}"
        trades_da_semana = 0
        while trades_da_semana < alvo:
            dia_sorteado = dias[int(rng.choice(len(dias), p=pesos_dias))]
            bloco = stats.por_dia[dia_sorteado]
            sim_ts += SEGUNDOS_POR_DIA
            dia_chave = f"d{int(sim_ts // SEGUNDOS_POR_DIA)}"
            for i in range(len(bloco)):
                entry_ts = sim_ts + i * 60.0
                ganhou = rng.random() < p_win
                pool = stats.ganhos if (ganhou and stats.ganhos) else (stats.perdas if stats.perdas else stats.ganhos)
                amostra = pool[int(rng.integers(0, len(pool)))]
                _aplicar_trade(estado, entry_ts, dia_chave, semana_chave, amostra, params, params.banca_inicial_usd)
                trades_da_semana += 1
                if trades_da_semana >= alvo:
                    break
    return ResultadoRodada(banca_final=estado.banca, maior_queda_pct=estado.maior_queda_pct, tocou_50pct=estado.tocou_50pct)


def rodar_monte_carlo(
    params: ParamsV1, stats: EstatisticasHistoricas, dist_freq: DistribuicaoFrequencia,
    n_simulacoes: int, n_semanas: int, peso_stress: float, seed: int,
) -> list[ResultadoRodada]:
    rng = np.random.default_rng(seed)
    dias = _preparar_dias(stats.por_dia)
    pesos = _pesos_dias(dias, stats.dias_ruins, peso_stress)
    return [_simular_uma_rodada(rng, params, stats, dist_freq, n_semanas, dias, pesos) for _ in range(n_simulacoes)]


def expectancia_r_limite_inferior(
    stats: EstatisticasHistoricas, n_bootstrap: int, seed: int, confianca: float = 0.90,
) -> tuple[float, float]:
    """Media dos R-multiplos observados + limite inferior unilateral (bootstrap da media, em
    blocos por dia pra preservar a correlacao intradiaria)."""
    rng = np.random.default_rng(seed)
    dias = sorted(stats.por_dia)
    n_dias = len(dias)
    medias = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        escolhidos = rng.integers(0, n_dias, size=n_dias)
        valores = [t.r_multiplo for idx in escolhidos for t in stats.por_dia[dias[idx]]]
        medias[i] = float(np.mean(valores)) if valores else 0.0
    media_observada = float(stats.r_multiplos.mean()) if stats.n_trades else 0.0
    limite_inferior = float(np.percentile(medias, 100 * (1 - confianca)))
    return media_observada, limite_inferior


def proporcao_com_ic(sucessos: int, n: int, z: float = _Z_95) -> tuple[float, float, float]:
    if n == 0:
        return 0.0, 0.0, 0.0
    p = sucessos / n
    erro = z * math.sqrt(max(p * (1 - p), 0.0) / n)
    return p, max(0.0, p - erro), min(1.0, p + erro)


# ---------------------------------------------------------------------------
# relatorio
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelatorioMonteCarlo:
    cenario: str
    n_trades_historicos: int
    taxa_acerto_historica: float
    banca_mediana: float
    banca_p5: float
    banca_p95: float
    drawdown_mediana: float
    drawdown_p5: float
    drawdown_p95: float
    prob_toque_50pct: float
    prob_toque_50pct_ic_baixo: float
    prob_toque_50pct_ic_alto: float
    expectancia_r: float
    expectancia_r_limite_inferior_90: float
    nao_aumentar_a_mao: bool


def montar_relatorio(
    cenario: str, stats: EstatisticasHistoricas, resultados: list[ResultadoRodada],
    exp_r: float, exp_r_lb: float,
) -> RelatorioMonteCarlo:
    bancas = np.array([r.banca_final for r in resultados], dtype=float)
    quedas = np.array([r.maior_queda_pct for r in resultados], dtype=float)
    toques = sum(1 for r in resultados if r.tocou_50pct)
    p, ic_baixo, ic_alto = proporcao_com_ic(toques, len(resultados))
    return RelatorioMonteCarlo(
        cenario=cenario, n_trades_historicos=stats.n_trades,
        taxa_acerto_historica=(stats.n_ganhos / stats.n_trades) if stats.n_trades else 0.0,
        banca_mediana=float(np.median(bancas)), banca_p5=float(np.percentile(bancas, 5)),
        banca_p95=float(np.percentile(bancas, 95)),
        drawdown_mediana=float(np.median(quedas)), drawdown_p5=float(np.percentile(quedas, 5)),
        drawdown_p95=float(np.percentile(quedas, 95)),
        prob_toque_50pct=p, prob_toque_50pct_ic_baixo=ic_baixo, prob_toque_50pct_ic_alto=ic_alto,
        expectancia_r=exp_r, expectancia_r_limite_inferior_90=exp_r_lb,
        nao_aumentar_a_mao=exp_r_lb <= 0,
    )


def formatar_relatorio(rel: RelatorioMonteCarlo) -> str:
    linhas = [
        f"=== Monte Carlo em blocos -- cenario: {rel.cenario} ===",
        f"trades historicos usados: {rel.n_trades_historicos} "
        f"(taxa de acerto observada: {100 * rel.taxa_acerto_historica:.1f}%)",
        f"banca final apos a projecao: mediana ${rel.banca_mediana:.2f} | "
        f"p5 ${rel.banca_p5:.2f} | p95 ${rel.banca_p95:.2f}",
        f"drawdown maximo: mediana {rel.drawdown_mediana:.1f}% | "
        f"p5 {rel.drawdown_p5:.1f}% | p95 {rel.drawdown_p95:.1f}%",
        f"P(banca tocar 50% da inicial): {100 * rel.prob_toque_50pct:.1f}% "
        f"(IC~95%: {100 * rel.prob_toque_50pct_ic_baixo:.1f}%-{100 * rel.prob_toque_50pct_ic_alto:.1f}%)",
        f"expectativa por trade: {rel.expectancia_r:.3f} R | "
        f"limite inferior 90%: {rel.expectancia_r_limite_inferior_90:.3f} R",
    ]
    if rel.nao_aumentar_a_mao:
        linhas.append("*** NAO AUMENTAR A MAO *** (limite inferior de 90% da expectativa em R e <= 0)")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# orquestracao / CLI
# ---------------------------------------------------------------------------


def executar(
    paths: Optional[Paths] = None,
    *,
    versao: str = VERSAO_CONGELADA,
    seed: int = SEED_PADRAO,
    n_simulacoes: int = N_SIMULACOES_PADRAO,
    n_semanas: int = N_SEMANAS_PADRAO,
    n_bootstrap_expectancia: int = N_BOOTSTRAP_EXPECTANCIA_PADRAO,
    trades: Optional[Sequence[TradeRealizado]] = None,
) -> list[RelatorioMonteCarlo]:
    params = load_params_v1()
    if params.version != VERSAO_CONGELADA:
        raise RuntimeError(
            f"params_v1 atual tem hash {params.version}, mas esta analise e EXCLUSIVA da versao "
            f"congelada {VERSAO_CONGELADA} -- nao misture estatisticas de versoes diferentes."
        )
    if trades is None:
        paths = paths or make_paths()
        trades, _feedback = carregar_trades(paths, versao)
    if len(trades) < MIN_TRADES_FECHADOS:
        raise RecusaAmostraInsuficiente(
            f"RECUSA: apenas {len(trades)} trade(s) fechado(s) da versao {versao} "
            f"(minimo exigido: {MIN_TRADES_FECHADOS}). O Monte Carlo nao roda com amostra insuficiente -- "
            "espere mais trades reais fecharem antes de repetir esta analise."
        )
    stats = calcular_estatisticas(trades)
    dist_freq = calibrar_frequencia(_todas_semanas_observadas(trades))
    exp_r, exp_r_lb = expectancia_r_limite_inferior(stats, n_bootstrap_expectancia, seed + 100)
    relatorios = []
    for i, (cenario, peso_stress) in enumerate((
        ("normal", 1.0),
        ("estresse (2x frequencia de dias ruins)", 2.0),
    )):
        resultados = rodar_monte_carlo(params, stats, dist_freq, n_simulacoes, n_semanas, peso_stress, seed + i)
        relatorios.append(montar_relatorio(cenario, stats, resultados, exp_r, exp_r_lb))
    return relatorios


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Monte Carlo em blocos para a POS-RUNNER-V1 congelada (so leitura, PAPER).")
    parser.add_argument("--seed", type=int, default=SEED_PADRAO)
    parser.add_argument("--simulacoes", type=int, default=N_SIMULACOES_PADRAO)
    parser.add_argument("--semanas", type=int, default=N_SEMANAS_PADRAO, help="horizonte de projecao, em semanas")
    args = parser.parse_args(argv)
    try:
        relatorios = executar(seed=args.seed, n_simulacoes=args.simulacoes, n_semanas=args.semanas)
    except RecusaAmostraInsuficiente as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for rel in relatorios:
        print(formatar_relatorio(rel))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
