"""PEDIDO (PARTE 1 de 2) FASE 2c: analise condicional da baseline pareada (`pr_baseline`), seguindo
`docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md` -- H1 (primaria/confirmatoria) e H2-H8
(exploratorias, Holm-Bonferroni sobre as testadas). PAPER / so leitura; nunca escreve em pr1_signals/
pr2_signals/pr_baseline/pr_trajetoria.

O plano precisa estar registrado (hash do arquivo em `meta`) ANTES de qualquer analise -- a 1a chamada
registra; chamadas seguintes recusam se o arquivo em disco mudou depois do registro (o plano nao pode
ser editado no meio da coleta).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import numpy as np

from ..config import Paths, make_paths
from ..pos_runner.bankroll_v1 import _dia_utc
from ..util import short_hash

PLANO_PATH = Path(__file__).resolve().parents[2] / "docs" / "pos-runner-v1" / "PLANO_ANALISE_PREREGISTRADO.md"
META_KEY_HASH = "plano_analise_hash"
MIN_TOKENS_H1 = 30
MIN_TOKENS_FUTILIDADE = 15
LIMITE_FUTILIDADE_R = -0.5
MIN_TOKENS_GRUPO = 10
SEED_PADRAO = 20_261_026
N_BOOTSTRAP_PADRAO = 10_000
CONFIANCA_H1 = 0.90
ALPHA_HOLM = 0.05
# DIAGNOSTICO 2026-10-27 (McRib/yagi, ver docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md "Exclusao
# pre-declarada"): mesma ordem de grandeza da tolerancia padrao da conferencia cruzada DexPaprika
# (dexpaprika_v1.DexPaprikaProvider.tolerancia_pct = 1.0) -- nao e um limiar novo inventado pra esta
# regra, e o mesmo criterio ja usado pelo sistema pra marcar um campo de candle como divergente.
TOLERANCIA_PRECO_ALERTA_PCT = 1.0


class PlanoAlteradoError(RuntimeError):
    """O plano pre-registrado em disco nao bate com o hash registrado -- a analise recusa rodar."""


def hash_do_plano(path: Path = PLANO_PATH) -> str:
    return short_hash(path.read_text(encoding="utf-8"))


def garantir_plano_registrado(storage: Any, path: Path = PLANO_PATH) -> str:
    """1a chamada registra o hash atual do arquivo; chamadas seguintes recusam (`PlanoAlteradoError`)
    se o arquivo em disco mudou depois do registro."""
    atual = hash_do_plano(path)
    registrado = storage.get_meta(META_KEY_HASH)
    if registrado is None:
        storage.set_meta(META_KEY_HASH, atual)
        return atual
    if registrado != atual:
        raise PlanoAlteradoError(
            f"docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md mudou depois de registrado "
            f"(registrado {registrado}, atual {atual}) -- o plano pre-registrado nao pode ser editado "
            "no meio da coleta. Abra uma nova secao/versao em vez de reescrever o texto ja em vigor."
        )
    return atual


# ---------------------------------------------------------------------------
# carga
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SinalResolvido:
    entry_id: int
    mint: str
    symbol: str
    t_entrada: float
    dif_pareada: float
    gatilho: tuple[str, ...]
    risco_pct: Optional[float]
    liquidez_usd: Optional[float]
    holders_tag: Optional[str]
    tags: tuple[str, ...]
    janela_ouro: Optional[str]

    @property
    def dia_utc(self) -> str:
        return _dia_utc(self.t_entrada)


@dataclass(frozen=True)
class Excluido:
    """DIAGNOSTICO 2026-10-27, regra de exclusao pre-declarada (PLANO_ANALISE_PREREGISTRADO.md "Exclusao
    pre-declarada"): candle/preco absurdo CONFIRMADO -- fora de H1-H8, listado aqui com o motivo."""
    entry_id: int
    mint: str
    symbol: str
    motivo: str  # 'preco_entrada_divergente' | 'candle_divergente' | 'risco_irrealista' | 'contaminado_candle'


def _preco_entrada_divergente(sinal: Any) -> bool:
    """`entry_price_alerta` (preco PROVISORIO mostrado no alerta ENTRADA, nunca sobrescrito) vs
    `entry_price` (preco gravado/corrigido depois que o fill real -- bars[j0].open -- e conhecido,
    `simulate_v1.py`). Sinais antigos (coluna adicionada nesta revisao) tem `entry_price_alerta` NULL
    -- nunca contam como divergente por falta de dado."""
    alerta, gravado = sinal["entry_price_alerta"], sinal["entry_price"]
    if alerta is None or gravado is None or alerta == 0:
        return False
    return 100.0 * abs(gravado - alerta) / abs(alerta) > TOLERANCIA_PRECO_ALERTA_PCT


def _candle_divergente_confirmado(storage: Any, versao: str, sinal: Any) -> bool:
    """So a V1 tem conferencia cruzada DexPaprika (`pr1_dexpaprika_divergencias`, PEDIDO CONSOLIDADO
    FASE 1 item 3b) -- a V2 nao tem a sua propria (ver `live.py: _entry_v2`/`_on_event_v2`). Qualquer
    linha logada para o candle do GATILHO (`ts_fechamento`) do sinal JA passou da tolerancia
    configurada (`dexpaprika_v1.comparar_candle` so grava divergencia CONFIRMADA, nunca um valor
    dentro da tolerancia) -- por isso basta checar presenca, sem limiar novo aqui."""
    if versao != "v1":
        return False
    ts = sinal["ts_fechamento"]
    pool = sinal["pool"]
    return any(r["pool"] == pool and r["candle_ts"] == ts for r in storage.pr1_dexpaprika_divergencias())


def _risco_irrealista(sinal: Any) -> bool:
    """PATCH 2026-10-27 (item 3 do pedido): risco real (fill vs stop, `PosRunnerLive.
    RISCO_IRREALISTA_MIN_PCT` = 3%) tagueado em `live.py: _confirmar_entrada` -- nunca bloqueia o
    sinal (continua negociando no paper normalmente), so fica fora de H1-H8 (amostra confiavel)."""
    return "risco_irrealista" in json.loads(sinal["tags"] or "[]")


def _contaminado_candle(sinal: Any) -> bool:
    """PATCH 2026-10-27 (item 2 do pedido pos-auditoria): marcacao RETROATIVA e EXPLICITA do operador
    (`scripts/marcar_contaminados.py`, tag `contaminado_candle`) para um trade confirmado contaminado
    por um candle corrompido em QUALQUER ponto do seu ciclo de vida -- nao so o candle do gatilho (ja
    coberto por `_candle_divergente_confirmado`) ou o preco de entrada (`_preco_entrada_divergente`).
    Nunca auto-detectada aqui: so o operador decide, depois de ler a auditoria."""
    return "contaminado_candle" in json.loads(sinal["tags"] or "[]")


def carregar_sinais_e_excluidos(storage: Any, versao: str) -> tuple[list[SinalResolvido], list[Excluido]]:
    """So sinais com `dif_pareada` JA calculada (controles e sinal real resolvidos -- ver
    `pr_baseline_resolvidas_com_dif`); junta com `pr_trajetoria` (mesmo entry_id/versao) so para o
    `t_entrada` (pr_baseline nao guarda isso) e com pr1_signals/pr2_signals para os campos de grupo.
    Aplica a regra de exclusao pre-declarada (candle/preco absurdo confirmado) ANTES de devolver a
    lista usavel -- os excluidos saem numa lista separada, com motivo, nunca silenciosamente."""
    out: list[SinalResolvido] = []
    excluidos: list[Excluido] = []
    sinal_lookup = storage.pr1_signal if versao == "v1" else storage.pr2_signal
    for b in storage.pr_baseline_resolvidas_com_dif(versao):
        traj = storage.pr_trajetoria_get(versao, b["entry_id"])
        sinal = sinal_lookup(b["entry_id"])
        if traj is None or sinal is None or traj["t_entrada"] is None or not sinal["mint"]:
            continue
        if _preco_entrada_divergente(sinal):
            excluidos.append(Excluido(b["entry_id"], sinal["mint"], sinal["symbol"] or "",
                                       "preco_entrada_divergente"))
            continue
        if _candle_divergente_confirmado(storage, versao, sinal):
            excluidos.append(Excluido(b["entry_id"], sinal["mint"], sinal["symbol"] or "",
                                       "candle_divergente"))
            continue
        if _risco_irrealista(sinal):
            excluidos.append(Excluido(b["entry_id"], sinal["mint"], sinal["symbol"] or "",
                                       "risco_irrealista"))
            continue
        if _contaminado_candle(sinal):
            excluidos.append(Excluido(b["entry_id"], sinal["mint"], sinal["symbol"] or "",
                                       "contaminado_candle"))
            continue
        entry_price, stop = sinal["entry_price"], sinal["stop"]
        risco_pct = 100.0 * (1.0 - stop / entry_price) if entry_price and stop is not None else None
        out.append(SinalResolvido(
            entry_id=b["entry_id"], mint=sinal["mint"], symbol=sinal["symbol"] or "",
            t_entrada=traj["t_entrada"], dif_pareada=b["dif_pareada"],
            gatilho=tuple(json.loads(sinal["gatilho"] or "[]")), risco_pct=risco_pct,
            liquidez_usd=sinal["liquidez_usd"], holders_tag=sinal["holders_tag"],
            tags=tuple(json.loads(sinal["tags"] or "[]")), janela_ouro=sinal["janela_ouro"],
        ))
    return out, excluidos


def carregar_sinais_resolvidos(storage: Any, versao: str) -> list[SinalResolvido]:
    """Compat: so a lista ja filtrada pela regra de exclusao -- ver `carregar_sinais_e_excluidos` para
    a lista de excluidos com motivo."""
    sinais, _ = carregar_sinais_e_excluidos(storage, versao)
    return sinais


def n_tokens_distintos(sinais: Sequence[SinalResolvido]) -> int:
    return len({s.mint for s in sinais})


# ---------------------------------------------------------------------------
# PARTE 2A FASE 3: comparacao com os sinais sombra (candidatos que os filtros barraram -- ver
# `pos_runner/live.py: _on_event_sombra`) -- R medio COM o filtro (amostra normal da V1/V2, fechada)
# vs SEM o filtro (`pr_sombra`, mesmo motivo, fechada). Nunca a comparacao confirmatoria H1 (n minimo
# das exploratorias, 10 -- so informal/comparativo).
# ---------------------------------------------------------------------------

SOMBRA_MOTIVOS = ("filtrado_mc_baixo", "filtrado_idade", "queda_96_mais")
RISCO_IRREALISTA_MIN_PCT = 3.0


@dataclass(frozen=True)
class ComparacaoSombra:
    motivo: str
    n_com_filtro: int
    r_medio_com_filtro: Optional[float]
    n_sem_filtro: int
    r_medio_sem_filtro: Optional[float]
    n_minimo: int
    amostra_suficiente: bool


def _r_multiplo(result_net: Optional[float], risco_pct: Optional[float]) -> Optional[float]:
    if result_net is None or not risco_pct:
        return None
    return result_net / (risco_pct / 100.0)


def comparar_sombra(storage: Any, versao: str, motivo: str, n_minimo: int = MIN_TOKENS_GRUPO) -> ComparacaoSombra:
    """R medio dos sinais REAIS (COM o filtro aplicado -- ja passaram pela V1/V2, fechados) vs os
    sinais sombra (SEM o filtro, `pr_sombra` versao=`sombra:<motivo>`, fechados). MESMAS exclusoes de
    risco<3% nos 2 lados; candle contaminado/divergente SO no lado real (a sombra nao tem conferencia
    cruzada DexPaprika nem marcacao retroativa do operador -- nunca finge ter essa checagem). MESMO n
    minimo das exploratorias (10) -- esta comparacao e informal, nunca a confirmatoria H1."""
    sinais_lookup = storage.pr1_signals if versao == "v1" else storage.pr2_signals
    r_com: list[float] = []
    for s in sinais_lookup(status="fechado"):
        if _risco_irrealista(s) or _contaminado_candle(s) or _candle_divergente_confirmado(storage, versao, s):
            continue
        entry_price, stop = s["entry_price"], s["stop"]
        risco_pct = 100.0 * (1.0 - stop / entry_price) if entry_price and stop is not None else None
        if risco_pct is not None and risco_pct < RISCO_IRREALISTA_MIN_PCT:
            continue
        r = _r_multiplo(s["result_net"], risco_pct)
        if r is not None:
            r_com.append(r)
    r_sem: list[float] = []
    for s in storage.pr_sombra_signals(versao=f"sombra:{motivo}", status="fechado"):
        if s["risco_pct"] is not None and s["risco_pct"] < RISCO_IRREALISTA_MIN_PCT:
            continue
        r = _r_multiplo(s["result_net"], s["risco_pct"])
        if r is not None:
            r_sem.append(r)
    media = (lambda xs: (sum(xs) / len(xs)) if xs else None)
    return ComparacaoSombra(
        motivo=motivo, n_com_filtro=len(r_com), r_medio_com_filtro=media(r_com),
        n_sem_filtro=len(r_sem), r_medio_sem_filtro=media(r_sem), n_minimo=n_minimo,
        amostra_suficiente=len(r_com) >= n_minimo and len(r_sem) >= n_minimo,
    )


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


def _blocos(sinais: Sequence[SinalResolvido], chave_fn: Callable[[SinalResolvido], str]) -> dict[str, list[float]]:
    grupos: dict[str, list[float]] = defaultdict(list)
    for s in sinais:
        grupos[chave_fn(s)].append(s.dif_pareada)
    return dict(grupos)


def bootstrap_media_e_limite_inferior(
    sinais: Sequence[SinalResolvido], chave_fn: Callable[[SinalResolvido], str],
    n_bootstrap: int = N_BOOTSTRAP_PADRAO, seed: int = SEED_PADRAO, confianca: float = CONFIANCA_H1,
) -> tuple[float, float]:
    """Media observada + limite inferior unilateral (bootstrap da media, em blocos de `chave_fn` --
    dia ou token -- pra preservar a correlacao entre sinais do mesmo bloco). Mesmo metodo de
    `analise.simulacao_bloco.expectancia_r_limite_inferior`, generalizado pra qualquer chave de bloco."""
    grupos = _blocos(sinais, chave_fn)
    chaves = sorted(grupos)
    n = len(chaves)
    if n == 0:
        return 0.0, 0.0
    rng = np.random.default_rng(seed)
    medias = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        escolhidos = rng.integers(0, n, size=n)
        valores = [v for idx in escolhidos for v in grupos[chaves[idx]]]
        medias[i] = float(np.mean(valores)) if valores else 0.0
    media_observada = float(np.mean([s.dif_pareada for s in sinais])) if sinais else 0.0
    limite_inferior = float(np.percentile(medias, 100 * (1 - confianca)))
    return media_observada, limite_inferior


def bootstrap_p_valor_unilateral(
    sinais: Sequence[SinalResolvido], n_bootstrap: int = N_BOOTSTRAP_PADRAO, seed: int = SEED_PADRAO,
) -> float:
    """P(media bootstrap <= 0), em blocos por DIA (mesma unidade de correlacao do H1; usado pelas
    sub-hipoteses exploratorias H2-H7)."""
    grupos = _blocos(sinais, lambda s: s.dia_utc)
    chaves = sorted(grupos)
    n = len(chaves)
    if n == 0:
        return 1.0
    rng = np.random.default_rng(seed)
    medias = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        escolhidos = rng.integers(0, n, size=n)
        valores = [v for idx in escolhidos for v in grupos[chaves[idx]]]
        medias[i] = float(np.mean(valores)) if valores else 0.0
    return float(np.mean(medias <= 0.0))


def holm_bonferroni(p_valores: Sequence[float], alpha: float = ALPHA_HOLM) -> list[bool]:
    """Step-down classico: ordena p-valores crescente, compara o i-esimo (rank 0-based) contra
    alpha/(m-rank); para no 1o que falha (os seguintes, com p maior, tambem falham)."""
    m = len(p_valores)
    significativo = [False] * m
    ordem = sorted(range(m), key=lambda i: p_valores[i])
    for rank, idx in enumerate(ordem):
        limiar = alpha / (m - rank)
        if p_valores[idx] <= limiar:
            significativo[idx] = True
        else:
            break
    return significativo


# ---------------------------------------------------------------------------
# H1 + exploratorias
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultadoH1:
    status: str  # 'AMOSTRA_INSUFICIENTE' | 'FUTIL' | 'PASS' | 'FAIL'
    n_tokens: int
    media_dif_pareada: Optional[float] = None
    limite_inferior_dia: Optional[float] = None
    limite_inferior_token: Optional[float] = None


def rodar_h1(sinais: Sequence[SinalResolvido]) -> ResultadoH1:
    n = n_tokens_distintos(sinais)
    if n < MIN_TOKENS_FUTILIDADE:
        return ResultadoH1("AMOSTRA_INSUFICIENTE", n)
    media_bruta = float(np.mean([s.dif_pareada for s in sinais])) if sinais else 0.0
    if n < MIN_TOKENS_H1:
        if media_bruta < LIMITE_FUTILIDADE_R:
            return ResultadoH1("FUTIL", n, media_dif_pareada=media_bruta)
        return ResultadoH1("AMOSTRA_INSUFICIENTE", n, media_dif_pareada=media_bruta)
    if media_bruta < LIMITE_FUTILIDADE_R:
        return ResultadoH1("FUTIL", n, media_dif_pareada=media_bruta)
    media_dia, lim_dia = bootstrap_media_e_limite_inferior(sinais, lambda s: s.dia_utc)
    _media_token, lim_token = bootstrap_media_e_limite_inferior(sinais, lambda s: s.mint)
    status = "PASS" if (lim_dia > 0 and lim_token > 0) else "FAIL"
    return ResultadoH1(status, n, media_dia, lim_dia, lim_token)


@dataclass(frozen=True)
class GrupoExploratorio:
    hipotese: str
    grupo: str
    n_tokens: int
    media_dif_pareada: float
    p_valor: float
    significativo_holm: bool = False


def _grupos_h2_h7(sinais: Sequence[SinalResolvido]) -> list[tuple[str, str, list[SinalResolvido]]]:
    """[(hipotese, nome_do_grupo, sinais_do_grupo), ...] -- so a particao, sem calcular nada ainda."""
    mediana_liq = float(np.median([s.liquidez_usd for s in sinais if s.liquidez_usd is not None])) \
        if any(s.liquidez_usd is not None for s in sinais) else None
    out: list[tuple[str, str, list[SinalResolvido]]] = []
    for gatilho in ("reacao_suporte", "power_candle_rompimento", "rompimento_volume"):
        out.append(("H2 tipo de gatilho", gatilho, [s for s in sinais if gatilho in s.gatilho]))
    out.append(("H3 risco", "risco < 25%", [s for s in sinais if s.risco_pct is not None and s.risco_pct < 25.0]))
    out.append(("H3 risco", "risco >= 25%", [s for s in sinais if s.risco_pct is not None and s.risco_pct >= 25.0]))
    if mediana_liq is not None:
        out.append(("H4 liquidez", "acima da mediana",
                    [s for s in sinais if s.liquidez_usd is not None and s.liquidez_usd >= mediana_liq]))
        out.append(("H4 liquidez", "abaixo da mediana",
                    [s for s in sinais if s.liquidez_usd is not None and s.liquidez_usd < mediana_liq]))
    out.append(("H5 holder concentrado", "sim", [s for s in sinais if s.holders_tag == "HOLDER_CONCENTRADO"]))
    out.append(("H5 holder concentrado", "nao", [s for s in sinais if s.holders_tag is None]))
    out.append(("H6 base_ge_2d", "sim", [s for s in sinais if "base_ge_2d" in s.tags]))
    out.append(("H6 base_ge_2d", "nao", [s for s in sinais if "base_ge_2d" not in s.tags]))
    out.append(("H7 janela de ouro", "janela_ouro", [s for s in sinais if s.janela_ouro == "janela_ouro"]))
    out.append(("H7 janela de ouro", "fora_da_janela", [s for s in sinais if s.janela_ouro == "fora_da_janela"]))
    return out


def rodar_exploratorias(sinais: Sequence[SinalResolvido]) -> list[GrupoExploratorio]:
    """H2-H7: so grupos com n >= 10 tokens distintos entram; Holm aplicado sobre a familia completa.
    H8 fica de fora (carteiras_pro_presentes sempre NULL nesta entrega -- ver INTERPRETACOES.md #12e)."""
    candidatos = []
    for hipotese, grupo, membros in _grupos_h2_h7(sinais):
        n = n_tokens_distintos(membros)
        if n < MIN_TOKENS_GRUPO:
            continue
        media = float(np.mean([s.dif_pareada for s in membros]))
        p = bootstrap_p_valor_unilateral(membros)
        candidatos.append(GrupoExploratorio(hipotese, grupo, n, media, p))
    if not candidatos:
        return []
    significativos = holm_bonferroni([c.p_valor for c in candidatos])
    return [GrupoExploratorio(c.hipotese, c.grupo, c.n_tokens, c.media_dif_pareada, c.p_valor, sig)
            for c, sig in zip(candidatos, significativos)]


# ---------------------------------------------------------------------------
# relatorio
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelatorioCondicional:
    versao: str
    h1: ResultadoH1
    exploratorias: list[GrupoExploratorio] = field(default_factory=list)
    h8_status: str = "nao_testada"
    excluidos: list[Excluido] = field(default_factory=list)
    sombra: list[ComparacaoSombra] = field(default_factory=list)


def executar(storage: Any, versao: str, plano_path: Path = PLANO_PATH) -> RelatorioCondicional:
    garantir_plano_registrado(storage, plano_path)
    sinais, excluidos = carregar_sinais_e_excluidos(storage, versao)
    h1 = rodar_h1(sinais)
    exploratorias = rodar_exploratorias(sinais) if h1.status in ("PASS", "FAIL") else []
    sombra = [comparar_sombra(storage, versao, motivo) for motivo in SOMBRA_MOTIVOS]
    return RelatorioCondicional(versao=versao, h1=h1, exploratorias=exploratorias, excluidos=excluidos, sombra=sombra)


def formatar_markdown(rel: RelatorioCondicional) -> str:
    linhas = [f"# Análise condicional — POS-RUNNER-{rel.versao.upper()}", ""]
    linhas.append(f"## H1 (primária): {rel.h1.status}")
    linhas.append(f"n (tokens distintos): {rel.h1.n_tokens}")
    if rel.h1.media_dif_pareada is not None:
        linhas.append(f"média de `dif_pareada`: {rel.h1.media_dif_pareada:+.3f} R")
    if rel.h1.limite_inferior_dia is not None:
        linhas.append(f"limite inferior 90% (bloco por dia): {rel.h1.limite_inferior_dia:+.3f} R")
    if rel.h1.limite_inferior_token is not None:
        linhas.append(f"limite inferior 90% (bloco por token): {rel.h1.limite_inferior_token:+.3f} R")
    linhas.append("")
    linhas.append("## H2–H8 (exploratórias, Holm sobre as testadas)")
    if not rel.exploratorias:
        linhas.append("(nenhum grupo com n >= 10 tokens distintos ainda, ou H1 não rodou)")
    for g in rel.exploratorias:
        marca = "**candidato (Holm)**" if g.significativo_holm else "não significativo"
        linhas.append(f"- {g.hipotese} / {g.grupo}: n={g.n_tokens}, média={g.media_dif_pareada:+.3f} R, "
                      f"p={g.p_valor:.4f} -> {marca}")
    linhas.append(f"- H8 (carteiras_pro_presentes): {rel.h8_status} (coluna NULL nesta entrega)")
    linhas.append("")
    linhas.append(f"## Excluídos (regra pré-declarada, candle/preço divergente confirmado): {len(rel.excluidos)}")
    for e in rel.excluidos:
        linhas.append(f"- entry_id={e.entry_id} {e.symbol} ({e.mint}): {e.motivo}")
    linhas.append("")
    linhas.append("## Sombra (candidatos que os filtros barraram, PARTE 2A FASE 3) — R médio com vs sem o filtro")
    for c in rel.sombra:
        suf = "amostra suficiente" if c.amostra_suficiente else f"amostra insuficiente (mín. {c.n_minimo} cada lado)"
        com = f"{c.r_medio_com_filtro:+.2f} R" if c.r_medio_com_filtro is not None else "s/d"
        sem = f"{c.r_medio_sem_filtro:+.2f} R" if c.r_medio_sem_filtro is not None else "s/d"
        linhas.append(f"- {c.motivo}: com filtro n={c.n_com_filtro} ({com}) | sem filtro (sombra) "
                      f"n={c.n_sem_filtro} ({sem}) | {suf}")
    return "\n".join(linhas)


def formatar_telegram(rel: RelatorioCondicional) -> str:
    if rel.h1.status == "AMOSTRA_INSUFICIENTE":
        # PARTE 2A FASE 3: a sombra tem o SEU PROPRIO n minimo (10, das exploratorias), independente
        # da amostra H1 (30) -- nunca escondida so porque H1 ainda nao tem n suficiente. 1a linha
        # IDENTICA a antes (testes existentes fixam esse texto exato) quando nao ha sombra pronta.
        texto = f"amostra insuficiente ({rel.h1.n_tokens}/{MIN_TOKENS_H1})"
        sombra_prontos = [c for c in rel.sombra if c.amostra_suficiente]
        if not sombra_prontos:
            return texto
        extra = "Sombra (com vs sem filtro): " + " | ".join(
            f"{c.motivo} {c.r_medio_com_filtro:+.2f}R vs {c.r_medio_sem_filtro:+.2f}R" for c in sombra_prontos)
        return f"{texto}\n{extra}"
    linhas = [f"📐 ANÁLISE CONDICIONAL — {rel.versao.upper()} | H1: {rel.h1.status} (n={rel.h1.n_tokens})"]
    if rel.h1.media_dif_pareada is not None:
        linhas.append(f"dif_pareada médio: {rel.h1.media_dif_pareada:+.2f} R")
    candidatos = [g for g in rel.exploratorias if g.significativo_holm]
    if candidatos:
        linhas.append("Candidatos (Holm): " + ", ".join(f"{g.hipotese}/{g.grupo}" for g in candidatos))
    else:
        linhas.append("Sem candidato exploratório significativo (Holm) ainda.")
    if rel.excluidos:
        linhas.append(f"{len(rel.excluidos)} excluído(s) por candle/preço divergente confirmado.")
    sombra_prontos = [c for c in rel.sombra if c.amostra_suficiente]
    if sombra_prontos:
        linhas.append("Sombra (com vs sem filtro): " + " | ".join(
            f"{c.motivo} {c.r_medio_com_filtro:+.2f}R vs {c.r_medio_sem_filtro:+.2f}R" for c in sombra_prontos))
    else:
        linhas.append("Sombra: nenhum motivo com amostra suficiente ainda (ver /analise completo).")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analise condicional da baseline pareada (PAPER / so leitura).")
    parser.add_argument("--versao", choices=("v1", "v2"), default="v1")
    args = parser.parse_args(argv)
    from ..storage import Storage

    paths: Paths = make_paths()
    storage = Storage(paths)
    try:
        rel = executar(storage, args.versao)
    except PlanoAlteradoError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        storage.close()
    print(formatar_markdown(rel))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
