"""Integracao do DexPaprika com a POS-RUNNER-V1 (PEDIDO CONSOLIDADO, FASE 1). So leitura, PAPER.

O cliente puro fica em `signals_mvp.dexpaprika` (mesma interface do GeckoTerminal). Este modulo e a
logica de NEGOCIO em volta dele, tudo opcional e desligavel (`DexPaprikaProvider.habilitado=False` =
zero chamada):

  1. fallback de atualizacao recente (`candles_fallback`): so quando o GeckoTerminal falhou (429/timeout/
     5xx) para um pool/tf -- NUNCA substitui o GT na reconstrucao do setup. O volume devolvido e sempre
     0.0 (a unidade do campo `volume` do DexPaprika nao foi confirmada contra a do GeckoTerminal -- zerar
     e a escolha conservadora: no maximo deixa de disparar `rompimento_volume` num candle de fallback,
     nunca dispara por engano com uma escala errada). Documentado em docs/DEXPAPRIKA.md.
  2. conferencia cruzada (`conferir`): so log, nunca decide. Amostra 1 em cada `amostra_cada_n` eventos
     WATCHLIST/ENTRADA (nunca todos -- orcamento de creditos). Campo a campo (open/high/low/close/volume)
     com tolerancia percentual configuravel.
  3. atraso de seguranca (`aceitar_ts`): um candle do DexPaprika so e aceito com pelo menos `atraso_min_s`
     depois do proprio fechamento (as fontes divergem sobre o atraso real no plano gratuito).
  4. orcamento de creditos: le os headers `x-credits-limit`/`x-credits-remaining` da ULTIMA resposta
     (nunca um contador local reinventado -- o DexPaprika ja devolve o estado real da janela movel de 30
     dias). Acima do teto (`creditos_teto_pct`, padrao 80%), trata como indisponivel (zero chamada nova).
  5. circuit breaker: depois de `limiar_falhas` falhas SEGUIDAS (timeout/network/5xx -- nunca `plan_limit`,
     que e um limite esperado do plano, nao uma indisponibilidade), fica "aberto" por `pausa_s` e nenhuma
     chamada nova e tentada (nem gasta credito tentando)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..http import ApiError, RateLimited, RateLimiter
from .candles import Bar, tf_seconds
from ..dexpaprika import DexPaprikaClient, DexPaprikaHttp

log = logging.getLogger("signals_mvp.pos_runner.dexpaprika_v1")

# tf da V1/V0 -> interval do DexPaprika (so os que tem equivalente EXATO -- "4h" nao existe no DexPaprika,
# o mais proximo seria "6h", que mudaria o alinhamento dos candles: fica indisponivel, nunca um substituto
# aproximado).
TF_PARA_INTERVAL: dict[str, str] = {"5m": "5m", "15m": "15m", "1h": "1h"}

DIVERGENCIA_CAMPOS = ("open", "high", "low", "close", "volume")


@dataclass
class CircuitBreaker:
    """Fechado (chamadas normais) -> aberto (toda chamada e recusada sem tentar, por `pausa_s`) depois de
    `limiar_falhas` falhas SEGUIDAS -- fecha de novo no 1o sucesso apos a pausa."""

    limiar_falhas: int = 3
    pausa_s: float = 300.0
    clock: Callable[[], float] = time.monotonic
    falhas_seguidas: int = field(default=0, init=False)
    aberto_until: float = field(default=0.0, init=False)

    def permitido(self) -> bool:
        return self.clock() >= self.aberto_until

    def registrar_falha(self) -> None:
        self.falhas_seguidas += 1
        if self.falhas_seguidas >= self.limiar_falhas:
            self.aberto_until = self.clock() + self.pausa_s
            log.warning("DexPaprika: circuit breaker ABERTO por %.0fs (%d falhas seguidas)",
                       self.pausa_s, self.falhas_seguidas)

    def registrar_sucesso(self) -> None:
        self.falhas_seguidas = 0
        self.aberto_until = 0.0


@dataclass(frozen=True)
class Divergencia:
    campo: str
    valor_gt: float
    valor_dexpaprika: float
    diff_pct: float


def _diff_pct(a: float, b: float) -> float:
    base = max(abs(a), abs(b), 1e-12)
    return 100.0 * abs(a - b) / base


def comparar_candle(gt: Bar, dp: Any, tolerancia_pct: float) -> list[Divergencia]:
    """Compara um candle GT (ja fechado) com o candle do DexPaprika para o MESMO `ts`; devolve so os
    campos que divergem alem da tolerancia. `dp` e um `models.Candle` (duck-typed: precisa so dos 5
    atributos open/high/low/close/volume)."""
    out: list[Divergencia] = []
    for campo in DIVERGENCIA_CAMPOS:
        a, b = float(getattr(gt, campo)), float(getattr(dp, campo))
        diff = _diff_pct(a, b)
        if diff > tolerancia_pct:
            out.append(Divergencia(campo, a, b, diff))
    return out


class DexPaprikaProvider:
    def __init__(
        self,
        client: DexPaprikaClient,
        *,
        habilitado: bool = True,
        atraso_min_s: float = 120.0,
        creditos_teto_pct: float = 0.8,
        tolerancia_pct: float = 1.0,
        amostra_cada_n: int = 5,
        breaker: Optional[CircuitBreaker] = None,
        clock: Callable[[], float] = time.time,
    ):
        self.client = client
        self.habilitado = habilitado
        self.atraso_min_s = atraso_min_s
        self.creditos_teto_pct = creditos_teto_pct
        self.tolerancia_pct = tolerancia_pct
        self.amostra_cada_n = max(1, amostra_cada_n)
        self.breaker = breaker or CircuitBreaker()
        self.clock = clock
        self._contagem_eventos = 0
        # estatisticas para o resumo diario / heartbeat (item 5 do pedido: "informar o impacto")
        self.chamadas_fallback = 0
        self.chamadas_conferencia = 0
        self.atrasos_observados_s: list[float] = []

    # -- orcamento de creditos (le os headers da ultima resposta, nunca um contador local) --------------
    def orcamento_ok(self) -> bool:
        c = self.client.http.credits
        if c.credits_limit is None or c.credits_remaining is None or c.credits_limit <= 0:
            return True   # 1a chamada: ainda nao ha header -- deixa tentar
        usado_pct = 1.0 - (c.credits_remaining / c.credits_limit)
        return usado_pct < self.creditos_teto_pct

    def disponivel(self) -> bool:
        return self.habilitado and self.breaker.permitido() and self.orcamento_ok()

    def resumo_impacto(self) -> dict[str, Any]:
        c = self.client.http.credits
        return {
            "chamadas_fallback": self.chamadas_fallback, "chamadas_conferencia": self.chamadas_conferencia,
            "creditos_restantes": c.credits_remaining, "creditos_limite": c.credits_limit,
            "breaker_aberto": not self.breaker.permitido(),
            "atraso_observado_s_medio": (sum(self.atrasos_observados_s) / len(self.atrasos_observados_s))
                                        if self.atrasos_observados_s else None,
        }

    # -- atraso de seguranca -----------------------------------------------------------------------------
    def aceitar_ts(self, candle_fecha_ts: float, now: float) -> bool:
        """Um candle FECHADO em `candle_fecha_ts` so e aceito com pelo menos `atraso_min_s` de atraso
        (as fontes divergem sobre o atraso real do plano gratuito -- este e o piso de seguranca)."""
        return (now - candle_fecha_ts) >= self.atraso_min_s

    def _registrar_falha(self, exc: ApiError) -> None:
        if exc.kind != "plan_limit":    # limite de plano e esperado, nao e indisponibilidade real
            self.breaker.registrar_falha()

    # -- fallback de atualizacao recente (item 3a) --------------------------------------------------------
    def candles_fallback(self, network: str, pool: str, tf: str, since_ts: float, now: float) -> list[Bar]:
        """So candles FECHADOS, com o atraso de seguranca, e com volume SEMPRE ZERADO (unidade do
        DexPaprika nao confirmada contra o GT -- ver docstring do modulo). Nunca levanta: qualquer falha
        devolve [] (quem chama trata como "sem candle novo ainda", igual a uma pagina vazia do GT)."""
        if not self.disponivel():
            return []
        interval = TF_PARA_INTERVAL.get(tf)
        if interval is None:
            return []
        step = tf_seconds(tf)
        try:
            candles = self.client.ohlcv(network, pool, since_ts, now, interval=interval)
            self.breaker.registrar_sucesso()
        except RateLimited:
            self.breaker.registrar_falha()
            return []
        except ApiError as exc:
            self._registrar_falha(exc)
            return []
        self.chamadas_fallback += 1
        out: list[Bar] = []
        for c in candles:
            fecha_ts = c.ts + step
            if fecha_ts > since_ts and self.aceitar_ts(fecha_ts, now):
                self.atrasos_observados_s.append(now - fecha_ts)
                out.append(Bar(int(c.ts), c.open, c.high, c.low, c.close, 0.0))
        return out

    # -- conferencia cruzada (item 3b) --------------------------------------------------------------------
    def deve_conferir(self) -> bool:
        """Amostra 1 em cada `amostra_cada_n` eventos (WATCHLIST/ENTRADA) -- nunca todos, por orcamento."""
        self._contagem_eventos += 1
        return self._contagem_eventos % self.amostra_cada_n == 0

    def conferir(self, network: str, pool: str, tf: str, candle_gt: Bar) -> list[Divergencia]:
        """So log: compara o candle GT (ja fechado, ja usado na decisao) com o MESMO ts no DexPaprika.
        Nunca levanta e nunca influencia a decisao -- quem chama so grava o resultado."""
        if not self.disponivel():
            return []
        interval = TF_PARA_INTERVAL.get(tf)
        if interval is None:
            return []
        step = tf_seconds(tf)
        try:
            candles = self.client.ohlcv(network, pool, candle_gt.ts, candle_gt.ts + step, interval=interval)
            self.breaker.registrar_sucesso()
        except RateLimited:
            self.breaker.registrar_falha()
            return []
        except ApiError as exc:
            self._registrar_falha(exc)
            return []
        self.chamadas_conferencia += 1
        casado = next((c for c in candles if c.ts == candle_gt.ts), None)
        if casado is None:
            return []
        return comparar_candle(candle_gt, casado, self.tolerancia_pct)


def make_provider(
    api_key: Optional[str], *, habilitado: bool = True, per_min: Optional[float] = None,
    atraso_min_s: float = 120.0, creditos_teto_pct: float = 0.8, tolerancia_pct: float = 1.0,
    amostra_cada_n: int = 5,
) -> DexPaprikaProvider:
    """Fabrica usada pelo `worker.py`. `per_min`: None usa o padrao por tier (30 c/ chave, segundo a
    documentacao; 10 SEM chave, valor REAL medido ao vivo em 2026-10-26 -- ver docs/DEXPAPRIKA.md)."""
    taxa = per_min if per_min is not None else (30.0 if api_key else 10.0)
    limiter = RateLimiter(taxa, burst=3, pause_s=60.0, pause_max_s=300.0)
    http = DexPaprikaHttp(limiter, api_key=api_key)
    client = DexPaprikaClient(http)
    return DexPaprikaProvider(client, habilitado=habilitado, atraso_min_s=atraso_min_s,
                              creditos_teto_pct=creditos_teto_pct, tolerancia_pct=tolerancia_pct,
                              amostra_cada_n=amostra_cada_n)
