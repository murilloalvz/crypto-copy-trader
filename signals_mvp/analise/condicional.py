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
import math
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import numpy as np

from ..config import Paths, make_paths
from ..pos_runner.bankroll_v1 import _dia_utc
from ..pos_runner.live import event_v1_from_json
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
# EMENDA 1 ao PLANO_ANALISE_PREREGISTRADO.md (2026-10-29, com o AJUSTE do mesmo dia -- ver secao
# "EMENDA 1" do plano): criterios (a)-(d) de robustez de H1, so entao EDGE_PROVISORIO.
P_VALOR_PERMUTACAO_MAX = 0.10
P_VALOR_ESCALAR_MAX = 0.01
MIN_TOKENS_ESCALAR = 100
CUSTO_CONSERVADOR_PCT_POR_PERNA = 3.0  # % adicional, ALEM do slippage_estimado_pct ja modelado
N_PERNAS_TRADE = 2  # entrada + saida
MEDIA_APARADA_PROP = 0.10  # so relatorio (item 1 da emenda)
LIMIAR_EXATO_PERMUTACAO_N = 20  # 2^n enumeravel ate aqui; acima, Monte Carlo deterministico
N_PERMUTACOES_MONTECARLO = 100_000
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


def registrar_emenda(storage: Any, path: Path = PLANO_PATH) -> tuple[str, str]:
    """EMENDA 1 (2026-10-29): re-registro EXPLICITO (nunca automatico dentro de `executar`) do hash
    atual do arquivo -- usado quando uma emenda pre-registrada ANTES de qualquer analise de dados
    precisa substituir o hash antigo (`garantir_plano_registrado` recusaria por mismatch). Grava a
    data + hash anterior + hash novo em `meta['plano_analise_emendas']` (lista JSON, append-only --
    historico de emendas nunca sobrescrito) e atualiza `meta[plano_analise_hash]`. Retorna
    (hash_anterior_ou_None, hash_novo). NUNCA chamado pela analise em si -- so pelo operador, via
    `--registrar-emenda`, antes da proxima coleta."""
    hash_anterior = storage.get_meta(META_KEY_HASH)
    hash_novo = hash_do_plano(path)
    historico = json.loads(storage.get_meta("plano_analise_emendas") or "[]")
    historico.append({"ts": time.time(), "hash_anterior": hash_anterior, "hash_novo": hash_novo})
    storage.set_meta("plano_analise_emendas", json.dumps(historico))
    storage.set_meta(META_KEY_HASH, hash_novo)
    return hash_anterior, hash_novo


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
    result_net: Optional[float] = None
    ticket_medio_usd: Optional[float] = None
    token_signal_seq: Optional[int] = None
    tempo_pico_caixa_s: Optional[float] = None

    @property
    def dia_utc(self) -> str:
        return _dia_utc(self.t_entrada)

    @property
    def r_realizado(self) -> Optional[float]:
        """EMENDA 1 (H10): R REALIZADO do sinal (nao `dif_pareada` -- pedido explicito da emenda),
        mesma convencao de `_r_multiplo`/`_sombra`."""
        return _r_multiplo(self.result_net, self.risco_pct)


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
            result_net=sinal["result_net"], ticket_medio_usd=sinal["ticket_medio_usd"],
            token_signal_seq=sinal["token_signal_seq"], tempo_pico_caixa_s=_tempo_pico_caixa_s(sinal),
        ))
    return out, excluidos


def _tempo_pico_caixa_s(sinal: Any) -> Optional[float]:
    """EMENDA 1 (H10): tempo (segundos) do PICO acumulado conhecido ate o INICIO da caixa/zona
    (`peak_ts` -> `box_start_ts`) -- os 2 JA estao gravados em `event_json.data` pelo detector
    (`detector_v1.py: EventV1`, unico ponto de construcao, mesma classe usada por V1 e V2); NENHUMA
    coluna nova foi necessaria. `None` quando o sinal e anterior a este campo existir no detector ou
    nao tem zona reconhecida."""
    try:
        data = event_v1_from_json(sinal["event_json"]).data
    except (TypeError, ValueError, KeyError):
        return None
    peak_ts, box_start_ts = data.get("peak_ts"), data.get("box_start_ts")
    if peak_ts is None or box_start_ts is None:
        return None
    return float(box_start_ts) - float(peak_ts)


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
    sinais: Sequence[SinalResolvido], chave_fn: Callable[[SinalResolvido], str] = lambda s: s.dia_utc,
    n_bootstrap: int = N_BOOTSTRAP_PADRAO, seed: int = SEED_PADRAO,
) -> float:
    """P(media bootstrap <= 0), em blocos de `chave_fn` (DIA por padrao -- mesma unidade de correlacao
    do H1, usado por H2-H9; EMENDA 1/H12 passa bloco por TOKEN, ja que um token hiperativo pode gerar
    varios sinais seq>=2 correlacionados)."""
    grupos = _blocos(sinais, chave_fn)
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
# EMENDA 1 ao PLANO_ANALISE_PREREGISTRADO.md (2026-10-29, com AJUSTE do mesmo dia -- ver secao
# "EMENDA 1" do plano): robustez de H1 (criterios a-d), H10-H12. Nenhuma coleta/analise real rodou
# ainda sobre este checkout (`meta.plano_analise_hash` so e gravado na 1a chamada de
# `garantir_plano_registrado`/`registrar_emenda`), entao esta e uma emenda PRE-registrada.
# ---------------------------------------------------------------------------


def media_sem_maior_ganho(sinais: Sequence[SinalResolvido]) -> float:
    """Criterio (b), ja com o AJUSTE do mesmo dia: estimativa PONTUAL da media de `dif_pareada` apos
    remover o UNICO maior ganho individual (leave-one-out do melhor trade) -- sem exigir limite
    inferior aqui (so a media). Um unico outlier de +50R nao pode sustentar 'edge' sozinho."""
    valores = [s.dif_pareada for s in sinais]
    if len(valores) <= 1:
        return 0.0
    idx_maior = max(range(len(valores)), key=lambda i: valores[i])
    resto = valores[:idx_maior] + valores[idx_maior + 1:]
    return float(np.mean(resto)) if resto else 0.0


def media_aparada(valores: Sequence[float], prop: float = MEDIA_APARADA_PROP) -> float:
    """Media aparada (remove prop/2 de cada ponta, arredondando p/ baixo) -- item 1 da emenda, SO
    relatorio (nunca decide status)."""
    vs = sorted(valores)
    n = len(vs)
    k = int(n * prop / 2.0)
    miolo = vs[k:n - k] if n - 2 * k > 0 else vs
    return float(np.mean(miolo)) if miolo else 0.0


def teste_permutacao_sinais(
    sinais: Sequence[SinalResolvido], n_permutacoes: int = N_PERMUTACOES_MONTECARLO, seed: int = SEED_PADRAO,
) -> float:
    """Criterio (c), ja com o AJUSTE do mesmo dia (mediana removida): teste de permutacao por
    INVERSAO DE SINAIS sobre a MEDIA das diferencas pareadas (`dif_pareada`), H0: o sinal de cada
    diferenca e +/- equiprovavel (magnitude fixa -- teste classico de pareamento). p unilateral =
    P(media_permutada >= media_observada), testando media > 0. EXATO (enumera as 2^n combinacoes de
    sinal) quando n <= 20; Monte Carlo deterministico (seed fixa) quando n > 20 -- 2^n deixa de ser
    enumeravel a partir dai."""
    valores = np.array([s.dif_pareada for s in sinais], dtype=float)
    n = len(valores)
    if n == 0:
        return 1.0
    media_obs = float(np.mean(valores))
    abs_valores = np.abs(valores)
    if n <= LIMIAR_EXATO_PERMUTACAO_N:
        total = 1 << n
        contagem = 0
        for mascara in range(total):
            sinais_flip = np.array([1.0 if (mascara >> i) & 1 else -1.0 for i in range(n)])
            if float(np.mean(abs_valores * sinais_flip)) >= media_obs:
                contagem += 1
        return contagem / total
    rng = np.random.default_rng(seed)
    opcoes = np.array([-1.0, 1.0])
    contagem = 0
    for _ in range(n_permutacoes):
        sinais_flip = rng.choice(opcoes, size=n)
        if float(np.mean(abs_valores * sinais_flip)) >= media_obs:
            contagem += 1
    return contagem / n_permutacoes


def media_custo_conservador(sinais: Sequence[SinalResolvido]) -> float:
    """Criterio (d): recalcula `dif_pareada` com um custo ADICIONAL de 3% por perna (entrada+saida,
    `CUSTO_CONSERVADOR_PCT_POR_PERNA` x `N_PERNAS_TRADE`) ALEM do que ja esta em `result_net`
    (`CostModel` oficial, intocado) -- so no lado do SINAL REAL (a baseline/controle e sintetica, sem
    execucao real a penalizar). `dif_pareada_ajustada = dif_pareada - 100*custo_extra_fracao/risco_pct`
    (mesma conversao R-multiplo de `_r_multiplo`). Sinais sem `risco_pct`/`result_net` nao entram
    neste calculo -- missingness nunca inventa um custo."""
    custo_extra_fracao = (CUSTO_CONSERVADOR_PCT_POR_PERNA / 100.0) * N_PERNAS_TRADE
    ajustadas = []
    for s in sinais:
        if not s.risco_pct or s.result_net is None:
            continue
        delta_r = 100.0 * custo_extra_fracao / s.risco_pct
        ajustadas.append(s.dif_pareada - delta_r)
    return float(np.mean(ajustadas)) if ajustadas else 0.0


def _rank_medios(valores: Sequence[float]) -> list[float]:
    """Rank 1..n; empates = media dos ranks (convencao padrao de Spearman/Mann-Whitney, sem scipy --
    nao e dependencia do projeto)."""
    n = len(valores)
    ordem = sorted(range(n), key=lambda i: valores[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and valores[ordem[j + 1]] == valores[ordem[i]]:
            j += 1
        rank_medio = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[ordem[k]] = rank_medio
        i = j + 1
    return ranks


def _rho_spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    rx = np.array(_rank_medios(list(xs)))
    ry = np.array(_rank_medios(list(ys)))
    if np.std(rx) == 0.0 or np.std(ry) == 0.0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def spearman(
    xs: Sequence[float], ys: Sequence[float], n_permutacoes: int = N_PERMUTACOES_MONTECARLO,
    seed: int = SEED_PADRAO,
) -> tuple[float, float]:
    """H10 (EMENDA 1, ja com o AJUSTE): correlacao de Spearman (rho = Pearson sobre os RANKS, empates
    pela media) entre `xs` e `ys`. p-valor por teste de permutacao (embaralha os ranks de `ys`, seed
    fixa, Monte Carlo) -- sem scipy. Retorna (0.0, 1.0) com n < 2."""
    n = len(xs)
    if n < 2:
        return 0.0, 1.0
    rx = np.array(_rank_medios(list(xs)))
    ry = np.array(_rank_medios(list(ys)))
    if np.std(rx) == 0.0 or np.std(ry) == 0.0:
        return 0.0, 1.0
    rho = float(np.corrcoef(rx, ry)[0, 1])
    rng = np.random.default_rng(seed)
    ry_embaralhado = ry.copy()
    extremos = 0
    for _ in range(n_permutacoes):
        rng.shuffle(ry_embaralhado)
        rho_perm = float(np.corrcoef(rx, ry_embaralhado)[0, 1])
        if abs(rho_perm) >= abs(rho):
            extremos += 1
    return rho, extremos / n_permutacoes


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def mann_whitney_u(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """H11 (EMENDA 1, ja com o AJUSTE): Mann-Whitney U bilateral, aproximacao normal com correcao de
    continuidade e correcao por empates no desvio-padrao -- sem scipy. Retorna (U_a, p); (0.0, 1.0)
    se algum lado estiver vazio ou a variancia for 0 (todos os valores iguais)."""
    na, nb = len(a), len(b)
    if na == 0 or nb == 0:
        return 0.0, 1.0
    todos = list(a) + list(b)
    ranks = _rank_medios(todos)
    u_a = sum(ranks[:na]) - na * (na + 1) / 2.0
    media_u = na * nb / 2.0
    n_total = na + nb
    contagem = Counter(todos)
    correcao_empates = sum(c ** 3 - c for c in contagem.values())
    if n_total <= 1:
        return u_a, 1.0
    var_u = (na * nb / 12.0) * ((n_total + 1) - correcao_empates / (n_total * (n_total - 1)))
    if var_u <= 0:
        return u_a, 1.0
    desvio = math.sqrt(var_u)
    continuidade = 0.5 if u_a > media_u else (-0.5 if u_a < media_u else 0.0)
    z = (u_a - media_u - continuidade) / desvio
    p = 2.0 * (1.0 - _norm_cdf(abs(z)))
    return u_a, min(1.0, p)


# ---------------------------------------------------------------------------
# H1 + exploratorias
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultadoH1:
    # EMENDA 1 (2026-10-29, com AJUSTE do mesmo dia): 3 desfechos possiveis em n>=30 -- nunca mais
    # PASS/FAIL. Falhar (b) ou (c) e INCONCLUSIVO, nunca "refutado" (FAIL deixou de existir).
    status: str  # 'AMOSTRA_INSUFICIENTE' | 'FUTIL' | 'EDGE_PROVISORIO' | 'INCONCLUSIVO'
    n_tokens: int
    media_dif_pareada: Optional[float] = None
    limite_inferior_dia: Optional[float] = None
    limite_inferior_token: Optional[float] = None
    criterio_a_bootstrap: Optional[bool] = None
    criterio_b_sem_maior_ganho: Optional[bool] = None
    criterio_c_permutacao: Optional[bool] = None
    criterio_d_custo_conservador: Optional[bool] = None
    media_sem_maior_ganho: Optional[float] = None
    media_aparada_10pct: Optional[float] = None
    p_valor_permutacao: Optional[float] = None
    n_diferencas_positivas: Optional[int] = None
    n_diferencas_total: Optional[int] = None
    media_custo_conservador: Optional[float] = None
    escalar_liberado: Optional[bool] = None  # n>=100 tokens distintos OU p_permutacao<0.01


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
    criterio_a = lim_dia > 0 and lim_token > 0
    media_sem_pico = media_sem_maior_ganho(sinais)
    criterio_b = media_sem_pico > 0
    p_perm = teste_permutacao_sinais(sinais)
    criterio_c = p_perm < P_VALOR_PERMUTACAO_MAX
    media_custo = media_custo_conservador(sinais)
    criterio_d = media_custo > 0
    status = "EDGE_PROVISORIO" if (criterio_a and criterio_b and criterio_c and criterio_d) else "INCONCLUSIVO"
    positivos = sum(1 for s in sinais if s.dif_pareada > 0)
    escalar = n >= MIN_TOKENS_ESCALAR or p_perm < P_VALOR_ESCALAR_MAX
    return ResultadoH1(
        status, n, media_dia, lim_dia, lim_token, criterio_a, criterio_b, criterio_c, criterio_d,
        media_sem_pico, media_aparada([s.dif_pareada for s in sinais]), p_perm, positivos, len(sinais),
        media_custo, escalar,
    )


@dataclass(frozen=True)
class GrupoExploratorio:
    hipotese: str
    grupo: str
    n_tokens: int
    media_dif_pareada: float
    p_valor: float
    significativo_holm: bool = False
    estatistica: Optional[str] = None  # EMENDA 1: rho (H10) / U (H11) -- teste nao e media>0 simples


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


def h10_velocidade_queda(sinais: Sequence[SinalResolvido]) -> Optional[GrupoExploratorio]:
    """H10 (EMENDA 1, ja com o AJUSTE do mesmo dia) -- geracao de hipoteses, NAO confirmatoria.
    Spearman entre o tempo (segundos, continuo) do PICO acumulado conhecido ate o INICIO da caixa/
    zona (`tempo_pico_caixa_s` -- `peak_ts`/`box_start_ts` ja gravados em `event_json.data` pelo
    detector, NENHUMA coluna nova precisou ser adicionada) e o R REALIZADO de cada sinal (nao
    `dif_pareada` -- pedido explicito da emenda). `None` (nao reportado) com < 10 tokens distintos com
    os 2 dados disponiveis."""
    pares = [(s.tempo_pico_caixa_s, s.r_realizado, s.mint) for s in sinais
             if s.tempo_pico_caixa_s is not None and s.r_realizado is not None]
    n = len({mint for _, _, mint in pares})
    if n < MIN_TOKENS_GRUPO:
        return None
    rho, p = spearman([p[0] for p in pares], [p[1] for p in pares])
    return GrupoExploratorio("H10 velocidade da queda (geracao de hipoteses, nao confirmatoria)",
                              "spearman(tempo pico->caixa, R realizado)", n, 0.0, p,
                              estatistica=f"rho={rho:+.3f}")


def h11_ticket_medio(sinais: Sequence[SinalResolvido]) -> Optional[GrupoExploratorio]:
    """H11 (EMENDA 1, ja com o AJUSTE) -- geracao de hipoteses, NAO confirmatoria. Mann-Whitney U
    comparando `dif_pareada` de abaixo vs acima da MEDIANA EXATA de `ticket_medio_usd` (recalculada a
    cada execucao, nunca um valor fixo). `None` se algum dos 2 lados tiver < 10 tokens distintos."""
    com_ticket = [s for s in sinais if s.ticket_medio_usd is not None]
    if not com_ticket:
        return None
    mediana = float(np.median([s.ticket_medio_usd for s in com_ticket]))
    abaixo = [s for s in com_ticket if s.ticket_medio_usd < mediana]
    acima = [s for s in com_ticket if s.ticket_medio_usd >= mediana]
    if n_tokens_distintos(abaixo) < MIN_TOKENS_GRUPO or n_tokens_distintos(acima) < MIN_TOKENS_GRUPO:
        return None
    u, p = mann_whitney_u([s.dif_pareada for s in abaixo], [s.dif_pareada for s in acima])
    return GrupoExploratorio("H11 ticket medio no gatilho (geracao de hipoteses, nao confirmatoria)",
                              "abaixo vs acima da mediana", n_tokens_distintos(com_ticket), 0.0, p,
                              estatistica=f"U={u:.1f}")


def h12_ordem_sinal_token(sinais: Sequence[SinalResolvido]) -> list[GrupoExploratorio]:
    """H12 (EMENDA 1, ja com o AJUSTE) -- geracao de hipoteses, NAO confirmatoria. 1o sinal do token
    (`token_signal_seq == 1`) vs 2o ou posterior (`>= 2`), bootstrap em blocos POR TOKEN (nao por dia
    -- um token hiperativo pode gerar varios sinais seq>=2 correlacionados, inflando o lado "2o ou
    posterior" se blocado por dia). Cada lado reporta seu proprio p (mesma convencao de H2-H9: media
    de `dif_pareada` > 0 dentro do grupo); lado com < 10 tokens distintos nao e reportado."""
    out: list[GrupoExploratorio] = []
    seq1 = [s for s in sinais if s.token_signal_seq == 1]
    seq2mais = [s for s in sinais if s.token_signal_seq is not None and s.token_signal_seq >= 2]
    for nome, grupo in (("1o sinal do token", seq1), ("2o ou posterior", seq2mais)):
        n = n_tokens_distintos(grupo)
        if n < MIN_TOKENS_GRUPO:
            continue
        media = float(np.mean([s.dif_pareada for s in grupo]))
        p = bootstrap_p_valor_unilateral(grupo, chave_fn=lambda s: s.mint)
        out.append(GrupoExploratorio("H12 ordem do sinal no token (geracao de hipoteses, nao confirmatoria)",
                                      nome, n, media, p))
    return out


# ---------------------------------------------------------------------------
# PEDIDO 2026-10-29 (auditoria+sensibilidade+sombra+radar), item 3: H13 -- tamanho_base_candles
# (`caixa_candles`, box_len no gatilho -- MESMA coluna ja persistida pela FASE 4 em pr1_signals/
# pr2_signals/pr_sombra, nenhuma coluna nova) vs R REALIZADO. Geracao de hipoteses, nao
# confirmatoria. Fora da familia de Holm de H2-H12 (fonte de dados DIFERENTE -- pool ENTRADAS reais
# fechadas (box_len sempre >=12, mesma mecanica de caixa em V1 e V2) com o candidato sombra
# `sombra:base_min4` fechado (box_len 4-11 -- >=12 ali e EXCLUIDO em `_on_event_sombra`, pra nunca
# duplicar o territorio real) -- e a UNICA forma de observar box_len < 12, que o V1/V2 reais nunca
# produzem (zone_min_candles=12 congelado). Reportada 1x, independente de --versao (pergunta sobre
# mecanica do detector, compartilhada por V1/V2 -- nunca mistura `dif_pareada`/H1-H9, que e sobre a
# baseline pareada).
# ---------------------------------------------------------------------------

FAIXAS_H13: tuple[tuple[str, int, Optional[int]], ...] = (("4-7", 4, 7), ("8-11", 8, 11), (">=12", 12, None))


def _risco_pct_sinal(s: Any) -> Optional[float]:
    entry_price, stop = s["entry_price"], s["stop"]
    return 100.0 * (1.0 - stop / entry_price) if entry_price and stop is not None else None


def _pares_tamanho_base(storage: Any) -> list[tuple[int, float, str]]:
    """[(tamanho_base_candles, R_realizado, mint), ...] -- V1/V2 reais fechados + sombra:base_min4
    fechado. `None` em qualquer um dos campos (box_len/result_net/risco_pct) nunca entra -- dado
    ausente nunca e inventado."""
    pares: list[tuple[int, float, str]] = []
    for sinais_fn in (storage.pr1_signals, storage.pr2_signals):
        for s in sinais_fn(status="fechado"):
            box_len = s["caixa_candles"]
            r = _r_multiplo(s["result_net"], _risco_pct_sinal(s))
            if box_len is not None and r is not None and s["mint"]:
                pares.append((int(box_len), r, s["mint"]))
    for s in storage.pr_sombra_signals(versao="sombra:base_min4", status="fechado"):
        box_len = s["caixa_candles"]
        r = _r_multiplo(s["result_net"], s["risco_pct"])
        if box_len is not None and r is not None and s["mint"]:
            pares.append((int(box_len), r, s["mint"]))
    return pares


def _spearman_bootstrap_p_por_token(
    pares: Sequence[tuple[float, float, str]], n_bootstrap: int = N_BOOTSTRAP_PADRAO, seed: int = SEED_PADRAO,
) -> float:
    """H13: p-valor bootstrap em blocos POR TOKEN (reamostra TOKENS com reposicao, recalcula rho a
    cada replica -- nunca reamostra pares individuais, que quebraria a correlacao dentro do mesmo
    token/episodio) -- 'agrupando por token' do pedido, mesmo principio de `bootstrap_media_e_
    limite_inferior`/H12, generalizado para uma correlacao em vez de uma media. p = P(rho_bootstrap
    <= 0), unilateral (testando rho > 0)."""
    grupos: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for x, y, token in pares:
        grupos[token].append((x, y))
    chaves = sorted(grupos)
    n = len(chaves)
    if n == 0:
        return 1.0
    rng = np.random.default_rng(seed)
    contagem = 0
    for _ in range(n_bootstrap):
        escolhidos = rng.integers(0, n, size=n)
        xs: list[float] = []
        ys: list[float] = []
        for idx in escolhidos:
            for x, y in grupos[chaves[idx]]:
                xs.append(x)
                ys.append(y)
        if _rho_spearman(xs, ys) <= 0.0:
            contagem += 1
    return contagem / n_bootstrap


def _faixas_h13(pares: Sequence[tuple[int, float, str]]) -> dict[str, Optional[tuple[int, float]]]:
    out: dict[str, Optional[tuple[int, float]]] = {}
    for nome, lo, hi in FAIXAS_H13:
        membros = [p for p in pares if p[0] >= lo and (hi is None or p[0] <= hi)]
        n = len({p[2] for p in membros})
        out[nome] = (n, float(np.mean([p[1] for p in membros]))) if n >= MIN_TOKENS_GRUPO else None
    return out


@dataclass(frozen=True)
class ResultadoH13:
    n_tokens: int
    rho: float
    p_valor: float
    por_faixa: dict[str, Optional[tuple[int, float]]]


def rodar_h13(storage: Any) -> Optional[ResultadoH13]:
    """`None` (nao reportada) com < 10 tokens distintos no total."""
    pares = _pares_tamanho_base(storage)
    n = len({p[2] for p in pares})
    if n < MIN_TOKENS_GRUPO:
        return None
    rho = _rho_spearman([float(p[0]) for p in pares], [p[1] for p in pares])
    p = _spearman_bootstrap_p_por_token(pares)
    return ResultadoH13(n, rho, p, _faixas_h13(pares))


def rodar_exploratorias(sinais: Sequence[SinalResolvido]) -> list[GrupoExploratorio]:
    """H2-H7 + H10-H12 (EMENDA 1): so grupos/testes com n >= 10 tokens distintos (por lado) entram;
    Holm aplicado sobre a familia completa. H8 fica de fora (carteiras_pro_presentes sempre NULL
    nesta entrega -- ver INTERPRETACOES.md #12e)."""
    candidatos = []
    for hipotese, grupo, membros in _grupos_h2_h7(sinais):
        n = n_tokens_distintos(membros)
        if n < MIN_TOKENS_GRUPO:
            continue
        media = float(np.mean([s.dif_pareada for s in membros]))
        p = bootstrap_p_valor_unilateral(membros)
        candidatos.append(GrupoExploratorio(hipotese, grupo, n, media, p))
    h10 = h10_velocidade_queda(sinais)
    if h10 is not None:
        candidatos.append(h10)
    h11 = h11_ticket_medio(sinais)
    if h11 is not None:
        candidatos.append(h11)
    candidatos.extend(h12_ordem_sinal_token(sinais))
    if not candidatos:
        return []
    significativos = holm_bonferroni([c.p_valor for c in candidatos])
    return [GrupoExploratorio(c.hipotese, c.grupo, c.n_tokens, c.media_dif_pareada, c.p_valor, sig, c.estatistica)
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
    h13: Optional[ResultadoH13] = None


def executar(storage: Any, versao: str, plano_path: Path = PLANO_PATH) -> RelatorioCondicional:
    garantir_plano_registrado(storage, plano_path)
    sinais, excluidos = carregar_sinais_e_excluidos(storage, versao)
    h1 = rodar_h1(sinais)
    exploratorias = rodar_exploratorias(sinais) if h1.status in ("EDGE_PROVISORIO", "INCONCLUSIVO") else []
    sombra = [comparar_sombra(storage, versao, motivo) for motivo in SOMBRA_MOTIVOS]
    h13 = rodar_h13(storage)
    return RelatorioCondicional(versao=versao, h1=h1, exploratorias=exploratorias, excluidos=excluidos,
                                sombra=sombra, h13=h13)


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
    if rel.h1.criterio_a_bootstrap is not None:
        # EMENDA 1 (2026-10-29, com AJUSTE do mesmo dia): criterios (a)-(d) -- EDGE_PROVISORIO exige
        # os 4; falhar (b)/(c) nunca e "refutado", so INCONCLUSIVO.
        linhas.append("EMENDA 1 — critérios de robustez (EDGE_PROVISORIO exige os 4):")
        linhas.append(f"  (a) limite inferior 90% (dia E token) > 0: {rel.h1.criterio_a_bootstrap}")
        linhas.append(f"  (b) média sem o maior ganho individual > 0: {rel.h1.criterio_b_sem_maior_ganho} "
                      f"(média sem ele: {rel.h1.media_sem_maior_ganho:+.3f} R)")
        linhas.append(f"  (c) permutação (inversão de sinais) p<0.10: {rel.h1.criterio_c_permutacao} "
                      f"(p={rel.h1.p_valor_permutacao:.4f})")
        linhas.append(f"  (d) sobrevive ao custo conservador (+3%/perna): {rel.h1.criterio_d_custo_conservador} "
                      f"(média ajustada: {rel.h1.media_custo_conservador:+.3f} R)")
        linhas.append(f"  média aparada (10%, só relatório): {rel.h1.media_aparada_10pct:+.3f} R")
        linhas.append(f"  diferenças positivas: {rel.h1.n_diferencas_positivas}/{rel.h1.n_diferencas_total}")
        linhas.append(f"  escalar mão liberado (n>=100 tokens OU p_permutação<0.01): {rel.h1.escalar_liberado}")
    linhas.append("")
    linhas.append("## H2–H8, H10–H12 (exploratórias, Holm sobre as testadas; H10–H12 geração de "
                  "hipóteses, não confirmatórias)")
    if not rel.exploratorias:
        linhas.append("(nenhum grupo com n >= 10 tokens distintos ainda, ou H1 não rodou)")
    for g in rel.exploratorias:
        marca = "**candidato (Holm)**" if g.significativo_holm else "não significativo"
        extra = f", {g.estatistica}" if g.estatistica else ""
        linhas.append(f"- {g.hipotese} / {g.grupo}: n={g.n_tokens}, média={g.media_dif_pareada:+.3f} R{extra}, "
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
    linhas.append("")
    linhas.append("## H13 (tamanho_base_candles vs R realizado, geração de hipóteses, não confirmatória)")
    if rel.h13 is None:
        linhas.append("(não reportada: < 10 tokens distintos no total V1/V2 reais + sombra:base_min4)")
    else:
        linhas.append(f"n (tokens distintos): {rel.h13.n_tokens}, rho={rel.h13.rho:+.3f}, "
                      f"p={rel.h13.p_valor:.4f} (bootstrap por token)")
        for nome, _lo, _hi in FAIXAS_H13:
            dado = rel.h13.por_faixa.get(nome)
            if dado is None:
                linhas.append(f"  faixa {nome}: n/d (< 10 tokens distintos)")
            else:
                linhas.append(f"  faixa {nome}: n={dado[0]}, R médio={dado[1]:+.2f}")
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
    if rel.h1.criterio_a_bootstrap is not None:
        crit = "abcd"
        marcas = [rel.h1.criterio_a_bootstrap, rel.h1.criterio_b_sem_maior_ganho,
                  rel.h1.criterio_c_permutacao, rel.h1.criterio_d_custo_conservador]
        linhas.append("Critérios EMENDA 1: " + " ".join(f"{c}={'OK' if m else 'x'}" for c, m in zip(crit, marcas)))
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
    parser.add_argument("--registrar-emenda", action="store_true",
                         help="EMENDA 1 (2026-10-29): re-registra o hash ATUAL do plano (ANTES de "
                              "qualquer analise sobre dados novos) -- nunca automatico, so quando "
                              "chamado explicitamente pelo operador.")
    args = parser.parse_args(argv)
    from ..storage import Storage

    paths: Paths = make_paths()
    storage = Storage(paths)
    if args.registrar_emenda:
        try:
            anterior, novo = registrar_emenda(storage)
            print(f"Emenda registrada: hash anterior={anterior or 's/d (1o registro)'} -> novo={novo}")
            return 0
        finally:
            storage.close()
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
