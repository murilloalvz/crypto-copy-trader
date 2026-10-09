"""SIG-FAST H2 piloto -- step A (rev. 4, 2026-10-08 operator review; Fase E
partes 1 e 2 addenda same day: endpoint rotation, windowed sampling, 429
desacelera-nao-aborta).

Pure systems check: measures RPC cost and decode coverage on migrations
SAMPLED OUTSIDE the frozen discovery/confirmation calendar blocks. Never
reads a return, never touches the sealed blocks, never spends a hypothesis
attempt (registry rule 5). The one price-derived number this script computes
(20-minute MemeTrans survival, as a 0/1 system count) was explicitly
authorized by the operator for K-sizing only -- "a taxa de sobrevivencia do
piloto e contagem de sistema, nao retorno" -- and is never used to judge H2
itself; step B (real download) and any EV/PF/edge computation stay gated
behind the operator's separate OK on the coverage report.

Fase E parte 1 split (deliberate, see handoff): Stage 1 (migration
ENUMERATION) stays on Helius's exclusive getTransactionsForAddress with a
blockTime jump -- MOVE-FIRST-H-DISC-V0 already found that walking
MIGRATION_AUTHORITY's signatures sequentially hits ~1.5M signatures without
leaving the last ~2 months, so pure getSignaturesForAddress is not practical
for this account specifically. Stage 2 (per-pool TRADE fetch, one pool's own
much smaller history) uses the operator-requested 2-stage method
(getSignaturesForAddress + getTransaction) with endpoint rotation
(EndpointRotator / load_rotation_rpc_urls in h2_historical_backfill_v0),
priced QuickNode/public first and Helius last to spare it for Stage 1.

Fase E parte 2 addenda (operator, 2026-10-08, same day): (1) enumeration no
longer walks a whole calendar day -- it samples K random non-overlapping
10-minute windows per block (sample_calendar_windows) and fetches ALL
successful migrations inside each one (fetch_migrations_in_windows), the
window being the sampling unit (cluster sampling, every migration in it
included -- never "next migration after a random instant", which would bias
toward migrations following quiet periods); (2) a 429 now SLOWS DOWN instead
of aborting (Retry-After honored, exponential backoff capped at 60s, abort
only after ~10min with zero success) and never counts toward the
consecutive-failure breaker (that breaker still exists, but only for
non-429 errors); (3) progress checkpoints to disk per window/pool so a
re-run does not redo already-fetched work.

See docs/sig-fast-disc-v0-batch-preregistration-DRAFT-2026-10-08.md (rev. 4,
"Regras anti-vies do discovery historico de H2") for the frozen protocol.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.move_first_h_coverage_audit_v0 import sample_migration_account as _mfh
from benchmarks.sig_fast_v0.h2_historical_backfill_v0 import (
    CarbonDecoderProcess,
    EndpointRotator,
    GRID_BUCKET_SECONDS,
    MigrationCandidate,
    POOL_TRADE_WINDOW_SECONDS,
    SIGNAL_MARKER_SECONDS,
    _load_rpc_url,
    fetch_migrations_in_windows,
    fetch_pool_signatures_in_window,
    group_successful_signatures_by_bucket,
    load_rotation_rpc_urls,
    resolve_bucket_swap_price,
    resolve_price_at_marker,
    resolve_price_at_t0,
    sample_calendar_windows,
)
from src.opportunity_path_metrics_v0 import PathTrade, mid_price_sol

VERSION = "sig_fast_h2_pilot_v0"

# DRAFT rev. 4, regra 2 -- blocos congelados, o piloto nunca os toca (as
# janelas sao sorteadas so dentro do lookback abaixo, que termina exatamente
# onde o discovery comeca -- sem overlap por construcao da data).
DISCOVERY_BLOCK_START = "2026-08-20"
DISCOVERY_BLOCK_END = "2026-09-17"
CONFIRMATION_BLOCK_START = "2026-09-24"
CONFIRMATION_BLOCK_END = "2026-10-08"
PILOT_SEED = 20261008
# Operador (Fase E parte 2): "K do piloto = o suficiente pra ~10 migracoes
# (estimar pela taxa ~40/h: 2-3 janelas)".
PILOT_K_DEFAULT = 3
PILOT_WINDOW_MINUTES_DEFAULT = 10
# Lookback pro universo de ONDE sortear o piloto: janela ampla e anterior ao
# embargo, deliberadamente sem overlap mesmo por acidente (ver regra 2).
PILOT_LOOKBACK_START = "2026-07-21"  # pos-BOOST, mesmo piso do resto da rodada
PILOT_LOOKBACK_END = DISCOVERY_BLOCK_START

# Helius pricing (helius.dev/docs/billing/credits, lido 2026-10-08 via
# WebFetch; a pagina nao mostra data/versao -- ver handoff pra a ressalva
# completa sobre fontes conflitantes encontradas em paginas de outros
# idiomas). getTransaction / getSignaturesForAddress = 1 credito flat (nao
# usados neste piloto). getTransactionsForAddress = 10 creditos por bloco
# iniciado de 100 transacoes completas retornadas.
HELIUS_CREDITS_PER_BLOCK = 10
HELIUS_BLOCK_SIZE = 100


def _credits_for_tx_count(n_tx: int) -> int:
    if n_tx <= 0:
        return 0
    return HELIUS_CREDITS_PER_BLOCK * math.ceil(n_tx / HELIUS_BLOCK_SIZE)


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))
    return ordered[index]


def _load_checkpoint(path: Path) -> dict[str, Any]:
    """Operador (Fase E parte 2): "checkpoint por janela/pool (retomar sem
    refazer o que ja baixou)". Formato simples: janelas de enumeracao ja
    processadas, as candidatas (migracoes) ja encontradas, e os resultados
    por pool_mint ja calculados -- um re-run pula tudo que ja esta aqui."""
    if not path.exists():
        return {"windows_done": [], "candidates": [], "tokens": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_checkpoint(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


# Operator review (2026-10-08, segunda rodada): limitador global conservador
# pra endpoints NAO-Helius (QuickNode/publico no rodizio do Estagio 2).
DEFAULT_MAX_RPS = 5.0
# Operador (Fase E parte 2): "Helius a 1 req/s" -- limiter proprio, mais
# conservador, so pra chamadas que vao pra Helius (Estagio 1 inteiro +
# qualquer chamada do Estagio 2 que caia nela como ultimo recurso).
HELIUS_MAX_RPS_DEFAULT = 1.0
# Operador (Fase E parte 2): "429 = desacelerar, nao abortar (...) so
# abortar apos ~10 min sem nenhum sucesso". Backoff exponencial capado em
# 60s, Retry-After respeitado quando presente.
MAX_429_BACKOFF_SECONDS = 60.0
MAX_429_STALL_SECONDS = 10 * 60.0
# "o circuit breaker de 3 falhas continua so para erros que NAO sao 429"
# (5xx, timeout, resposta invalida) -- 429 nunca incrementa este contador,
# so o stall de ~10min acima decide quando abortar por 429.
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3


def _retry_after_seconds(exc: BaseException) -> float | None:
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class RateLimiter:
    """Pacer de intervalo minimo entre chamadas -- nunca mais rapido que
    max_rps, aplicado a toda chamada RPC do piloto (enumeracao + busca de
    trades + resolucao de migracao), nao so uma parte."""

    def __init__(self, max_rps: float):
        if max_rps <= 0:
            raise ValueError("max_rps must be positive")
        self.min_interval = 1.0 / max_rps
        self._last_call_monotonic: float | None = None

    def wait(self) -> None:
        now = time.monotonic()
        if self._last_call_monotonic is not None:
            remaining = self.min_interval - (now - self._last_call_monotonic)
            if remaining > 0:
                time.sleep(remaining)
        self._last_call_monotonic = time.monotonic()


class PilotAbortedRateLimited(RuntimeError):
    """Rajada de falhas consecutivas (ja com retry/backoff esgotado em
    cada uma) -- o piloto para e reporta o que ja tinha, sem insistir."""

    def __init__(self, consecutive_failures: int, last_error: str):
        super().__init__(
            f"abortando apos {consecutive_failures} falhas de RPC consecutivas "
            f"(cada uma ja com retry/backoff esgotado) -- ultimo erro: {last_error}"
        )
        self.consecutive_failures = consecutive_failures
        self.last_error = last_error


@dataclass(frozen=True)
class RpcCallLogEntry:
    method: str
    credits: int
    elapsed_seconds_since_start: float


@dataclass
class RpcUsageTracker:
    """Credito por chamada e total -- 'registrar creditos consumidos por
    chamada e no total' (instrucao verbatim do operador)."""

    start_monotonic: float = field(default_factory=time.monotonic)
    calls: list[RpcCallLogEntry] = field(default_factory=list)

    @property
    def total_credits(self) -> int:
        return sum(entry.credits for entry in self.calls)

    def record(self, method: str, result: dict[str, Any]) -> int:
        credits = self._credits_for(method, result)
        self.calls.append(
            RpcCallLogEntry(
                method=method,
                credits=credits,
                elapsed_seconds_since_start=round(time.monotonic() - self.start_monotonic, 3),
            )
        )
        return credits

    @staticmethod
    def _credits_for(method: str, result: dict[str, Any]) -> int:
        # Helius docs/billing/credits (lido via WebFetch 2026-10-08, sem
        # data/versao visivel na pagina -- ver handoff pra a ressalva sobre
        # fontes conflitantes encontradas em paginas de outros idiomas).
        if method in ("getTransaction", "getSignaturesForAddress"):
            return 1
        if method == "getTransactionsForAddress":
            n_tx = len((result.get("result") or {}).get("data") or [])
            return _credits_for_tx_count(n_tx)
        return 0


def install_rate_limited_rpc(
    *,
    max_rps: float,
    helius_url: str,
    max_consecutive_failures: int,
    tracker: RpcUsageTracker,
    helius_max_rps: float = HELIUS_MAX_RPS_DEFAULT,
    max_429_stall_seconds: float = MAX_429_STALL_SECONDS,
):
    """Troca _mfh._rpc (sample_migration_account, modulo singleton -- nunca
    reimportado em __main__, ver commit 1b4da44 desta rodada) por uma versao
    que: espera um RateLimiter proprio por destino (Helius a helius_max_rps,
    qualquer outro endpoint a max_rps); em 429, DESACELERA em vez de abortar
    -- respeita Retry-After quando presente, senao backoff exponencial
    dobrando ate MAX_429_BACKOFF_SECONDS, e so aborta se passar
    max_429_stall_seconds (~10min) sem NENHUM sucesso (operador, Fase E
    parte 2: "429 = desacelerar, nao abortar"); conta falhas consecutivas
    SO para erros que NAO sao 429 e levanta PilotAbortedRateLimited ao bater
    o limite. Retorna a funcao de restauracao -- chamar sempre, mesmo em
    erro."""
    original_rpc = _mfh._rpc
    default_limiter = RateLimiter(max_rps)
    helius_limiter = RateLimiter(helius_max_rps)
    state = {"consecutive_failures": 0, "last_success_monotonic": time.monotonic()}

    def wrapped(rpc_url: str, method: str, params: list, *, retries: int = 5) -> dict:
        limiter = helius_limiter if rpc_url == helius_url else default_limiter
        backoff = 1.0
        while True:
            limiter.wait()
            try:
                # retries=1: este wrapper e o unico controlador de retry/
                # backoff a partir daqui -- deixar _mfh._rpc tentar de novo
                # por conta propria so duplicaria/confundiria a politica de
                # 429 abaixo.
                result = original_rpc(rpc_url, method, params, retries=1)
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    stalled_for = time.monotonic() - state["last_success_monotonic"]
                    if stalled_for >= max_429_stall_seconds:
                        raise PilotAbortedRateLimited(
                            state["consecutive_failures"],
                            f"429 sustentado por {stalled_for:.0f}s sem nenhum sucesso",
                        ) from exc
                    wait_s = min(_retry_after_seconds(exc) or backoff, MAX_429_BACKOFF_SECONDS)
                    time.sleep(wait_s)
                    backoff = min(backoff * 2, MAX_429_BACKOFF_SECONDS)
                    continue  # 429 nunca conta pro breaker de falhas consecutivas
                state["consecutive_failures"] += 1
                if state["consecutive_failures"] >= max_consecutive_failures:
                    raise PilotAbortedRateLimited(state["consecutive_failures"], str(exc)) from exc
                raise
            except Exception as exc:
                state["consecutive_failures"] += 1
                if state["consecutive_failures"] >= max_consecutive_failures:
                    raise PilotAbortedRateLimited(state["consecutive_failures"], str(exc)) from exc
                raise
            state["consecutive_failures"] = 0
            state["last_success_monotonic"] = time.monotonic()
            tracker.record(method, result)
            return result

    _mfh._rpc = wrapped

    def restore() -> None:
        _mfh._rpc = original_rpc

    return restore


# Operador (addendum Fase E parte 4): "contagem de trades bem-sucedidos
# nos ultimos 5 min" antes do marco de 20min -- diagnostico de sistema,
# vem direto da lista de assinaturas (regra 1), nunca de uma chamada nova.
LAST_5MIN_SECONDS = 5 * 60


@dataclass(frozen=True)
class PilotTokenResult:
    pool_mint: str
    migration_signature: str
    migration_block_time: int
    n_signatures_in_window: int
    n_failed_tx: int
    pct_failed_tx: float
    n_successful_trades_last_5min_before_marker: int
    n_events_decoded: int
    n_events_with_reserves_and_fee: int
    pct_decoded_with_reserves_and_fee: float
    estimated_credits: int
    n_rpc_calls: int
    elapsed_seconds: float
    survived_20min_system_count: bool | None


def _survival_system_count_from_resolved(
    t0_resolved: dict[str, Any] | None, marker_resolved: dict[str, Any] | None
) -> bool | None:
    """MemeTrans 20-minute survival proxy, operator-authorized as a system
    count for K-sizing only (never an H2 verdict input) -- MESMA regua
    pre-registrada (razao marco/T0 >= 0,40) de antes do addendum Fase E
    parte 4; o que mudou e so a FONTE do preco (grade de 5s em vez de
    "qualquer swap decodificado na janela"), nunca a regra de decisao.
    None se um dos dois lados nao foi resolvido -- nunca inferido como 0."""
    if t0_resolved is None or marker_resolved is None:
        return None
    event_t0 = t0_resolved["event"]
    event_marker = marker_resolved["event"]
    if (
        event_t0.get("pool_base_token_reserves_raw") is None
        or event_t0.get("pool_quote_token_reserves_raw") is None
        or event_marker.get("pool_base_token_reserves_raw") is None
        or event_marker.get("pool_quote_token_reserves_raw") is None
    ):
        return None
    price_t0 = mid_price_sol(
        PathTrade(
            chain_time=0,
            venue="pumpswap",
            base_reserves_raw=event_t0["pool_base_token_reserves_raw"],
            quote_reserves_raw=event_t0["pool_quote_token_reserves_raw"],
        )
    )
    price_marker = mid_price_sol(
        PathTrade(
            chain_time=0,
            venue="pumpswap",
            base_reserves_raw=event_marker["pool_base_token_reserves_raw"],
            quote_reserves_raw=event_marker["pool_quote_token_reserves_raw"],
        )
    )
    if price_t0 is None or price_marker is None or price_t0 <= 0:
        return None
    return (price_marker / price_t0) >= 0.40


def run_pilot_token(
    carbon: CarbonDecoderProcess,
    candidate: MigrationCandidate,
    *,
    rotator: EndpointRotator,
    tracker: RpcUsageTracker,
) -> PilotTokenResult:
    """Estagio 1 barato (addendum Fase E parte 4, operador 2026-10-09):
    substitui o metodo antigo de 1 getTransaction por trade (achado:
    16.473 transacoes numa janela real, proibitivo). Lista de assinaturas
    da janela inteira e barata (so getSignaturesForAddress, err/block_time
    ja vem na resposta); preco em T0 e no marco de 20min vem da grade de
    5s (resolve_price_at_t0/resolve_price_at_marker), tipicamente 2
    getTransaction no caso otimista. `candidate.migration_block_time` ja e
    o instante real (fetch_migrations_in_windows le direto da propria
    enumeracao, Fase E parte 2)."""
    t0_wall = time.monotonic()
    credits_before = tracker.total_credits
    calls_before = len(tracker.calls)
    window_start = candidate.migration_block_time
    window_end = window_start + POOL_TRADE_WINDOW_SECONDS

    entries = fetch_pool_signatures_in_window(
        rotator, pool_mint=candidate.pool_mint, window_start=window_start, window_end=window_end
    )
    n_total = len(entries)
    n_failed = sum(1 for e in entries if e.failed)
    pct_failed = round(100.0 * n_failed / n_total, 2) if n_total else 0.0

    n_last_5min = sum(
        1
        for e in entries
        if not e.failed
        and e.block_time is not None
        and (SIGNAL_MARKER_SECONDS - LAST_5MIN_SECONDS) <= (e.block_time - window_start) < SIGNAL_MARKER_SECONDS
    )

    buckets = group_successful_signatures_by_bucket(entries, window_start=window_start)
    t0_resolved = resolve_price_at_t0(rotator, carbon, buckets)
    marker_resolved = resolve_price_at_marker(rotator, carbon, buckets, marker_seconds=SIGNAL_MARKER_SECONDS)

    decoded_events = [r["event"] for r in (t0_resolved, marker_resolved) if r is not None]
    n_decoded = len(decoded_events)
    n_with_both = sum(
        1
        for e in decoded_events
        if e.get("pool_base_token_reserves_raw") is not None
        and (e.get("lp_fee_raw") is not None or e.get("fee_raw") is not None)
    )
    pct = round(100.0 * n_with_both / n_decoded, 2) if n_decoded else 0.0

    return PilotTokenResult(
        pool_mint=candidate.pool_mint,
        migration_signature=candidate.migration_signature,
        migration_block_time=window_start,
        n_signatures_in_window=n_total,
        n_failed_tx=n_failed,
        pct_failed_tx=pct_failed,
        n_successful_trades_last_5min_before_marker=n_last_5min,
        n_events_decoded=n_decoded,
        n_events_with_reserves_and_fee=n_with_both,
        pct_decoded_with_reserves_and_fee=pct,
        estimated_credits=tracker.total_credits - credits_before,
        n_rpc_calls=len(tracker.calls) - calls_before,
        elapsed_seconds=round(time.monotonic() - t0_wall, 3),
        survived_20min_system_count=_survival_system_count_from_resolved(t0_resolved, marker_resolved),
    )


@dataclass(frozen=True)
class PilotSummary:
    n_sampled: int
    avg_rpc_calls_per_pool: float
    median_rpc_calls_per_pool: float | None
    p90_rpc_calls_per_pool: float | None
    avg_elapsed_seconds_per_pool: float
    avg_credits_per_pool: float
    avg_pct_failed_tx: float
    avg_pct_decoded_with_reserves_and_fee: float
    n_survived_system_count: int
    n_survival_determinable: int
    survival_rate_system_count: float | None
    k_windows_used: int
    avg_migrations_per_window: float | None
    h2_signals_per_window_system_count: float | None
    k_windows_proposed_for_n30_signals: int | None
    estimated_total_seconds_for_k_proposed: float | None


def summarize_pilot(results: list[PilotTokenResult], *, k_windows_used: int) -> PilotSummary:
    """k_windows_used e o numero de janelas de 10min REALMENTE enumeradas
    (nao o K pedido) -- base real pra extrapolar quantas janelas por bloco
    dariam n>=30 sinais H2 no treino (operador, Fase E partes 2/4). "Sinal
    H2" aqui = migracao com sobrevivencia determinavel (survived_20min_
    system_count is not None), ou seja, teve preco resolvido em T0 e no
    marco -- contagem de sistema, nao julgamento economico. O tempo total
    estimado usa o tempo medio REAL do Estagio 1 barato por pool (regra 3
    do addendum) -- NAO inclui a grade completa do Estagio 2 (regra 4,
    discovery/confirmacao reais), que e medida separadamente (ver
    run_price_grid_benchmark)."""
    n = len(results)
    determinable = [r for r in results if r.survived_20min_system_count is not None]
    survived = [r for r in determinable if r.survived_20min_system_count]
    survival_rate = (len(survived) / len(determinable)) if determinable else None

    avg_migrations_per_window = (n / k_windows_used) if k_windows_used else None
    signals_per_window = (len(determinable) / k_windows_used) if k_windows_used else None

    k_proposed = None
    estimated_total_seconds = None
    if signals_per_window and signals_per_window > 0:
        k_proposed = math.ceil(30 / signals_per_window)
        if n and avg_migrations_per_window:
            avg_seconds = sum(r.elapsed_seconds for r in results) / n
            estimated_total_seconds = round(k_proposed * avg_migrations_per_window * avg_seconds, 1)

    calls_counts = [float(r.n_rpc_calls) for r in results]
    return PilotSummary(
        n_sampled=n,
        avg_rpc_calls_per_pool=(sum(r.n_rpc_calls for r in results) / n) if n else 0.0,
        median_rpc_calls_per_pool=_percentile(calls_counts, 0.50),
        p90_rpc_calls_per_pool=_percentile(calls_counts, 0.90),
        avg_elapsed_seconds_per_pool=(sum(r.elapsed_seconds for r in results) / n) if n else 0.0,
        avg_credits_per_pool=(sum(r.estimated_credits for r in results) / n) if n else 0.0,
        avg_pct_failed_tx=(sum(r.pct_failed_tx for r in results) / n) if n else 0.0,
        avg_pct_decoded_with_reserves_and_fee=(
            sum(r.pct_decoded_with_reserves_and_fee for r in results) / n if n else 0.0
        ),
        n_survived_system_count=len(survived),
        n_survival_determinable=len(determinable),
        survival_rate_system_count=survival_rate,
        k_windows_used=k_windows_used,
        avg_migrations_per_window=avg_migrations_per_window,
        h2_signals_per_window_system_count=signals_per_window,
        k_windows_proposed_for_n30_signals=k_proposed,
        estimated_total_seconds_for_k_proposed=estimated_total_seconds,
    )


@dataclass(frozen=True)
class GridBenchmarkResult:
    pool_mint: str
    bucket_seconds: int
    n_buckets_total: int
    n_buckets_processed: int
    n_buckets_with_swap_resolved: int
    n_rpc_calls: int
    elapsed_seconds: float
    time_budget_seconds: float
    completed: bool


def run_price_grid_benchmark(
    carbon: CarbonDecoderProcess,
    candidate: MigrationCandidate,
    *,
    rotator: EndpointRotator,
    tracker: RpcUsageTracker,
    time_budget_seconds: float,
) -> GridBenchmarkResult:
    """Mede o custo REAL do Estagio 2 (grade completa, regra 4) num unico
    token real -- so pra extrapolar tempo/chamadas, nunca pra julgar H2
    nem calcular retorno. Orcamento de tempo prende a medicao (nunca roda
    sem teto); `completed=False` quando o orcamento acaba antes da janela
    inteira (migracao + 80min) ser percorrida -- os numeros parciais ainda
    sao reais, nao extrapolados."""
    t0_wall = time.monotonic()
    calls_before = len(tracker.calls)
    window_start = candidate.migration_block_time
    window_end = window_start + POOL_TRADE_WINDOW_SECONDS

    entries = fetch_pool_signatures_in_window(
        rotator, pool_mint=candidate.pool_mint, window_start=window_start, window_end=window_end
    )
    buckets = group_successful_signatures_by_bucket(entries, window_start=window_start)
    n_buckets_total = POOL_TRADE_WINDOW_SECONDS // GRID_BUCKET_SECONDS

    completed = True
    n_processed = 0
    n_resolved = 0
    for bucket_index in range(n_buckets_total):
        if time.monotonic() - t0_wall > time_budget_seconds:
            completed = False
            break
        resolved = resolve_bucket_swap_price(rotator, carbon, buckets.get(bucket_index, []))
        n_processed += 1
        if resolved is not None:
            n_resolved += 1

    return GridBenchmarkResult(
        pool_mint=candidate.pool_mint,
        bucket_seconds=GRID_BUCKET_SECONDS,
        n_buckets_total=n_buckets_total,
        n_buckets_processed=n_processed,
        n_buckets_with_swap_resolved=n_resolved,
        n_rpc_calls=len(tracker.calls) - calls_before,
        elapsed_seconds=round(time.monotonic() - t0_wall, 3),
        time_budget_seconds=time_budget_seconds,
        completed=completed,
    )


def _self_check_rate_limiter_and_breaker() -> None:
    limiter = RateLimiter(max_rps=20.0)  # min_interval = 0.05s
    t0 = time.monotonic()
    limiter.wait()
    limiter.wait()
    assert time.monotonic() - t0 >= 0.04, "RateLimiter did not pace the second call"

    tracker = RpcUsageTracker()
    assert tracker._credits_for("getTransaction", {}) == 1
    assert tracker._credits_for("getSignaturesForAddress", {}) == 1
    assert tracker._credits_for("getTransactionsForAddress", {"result": {"data": [{}] * 150}}) == 20
    assert tracker._credits_for("unknownMethod", {}) == 0

    # ok, fail, ok, fail, fail, fail -- breaker must only trip on the 3rd
    # CONSECUTIVE non-429 failure (the "ok" in the middle resets the
    # counter). Uses RuntimeError (not a 429 HTTPError) deliberately -- the
    # 429-specific slow-down-not-abort path is covered separately in
    # _self_check_429_policy.
    outcomes = iter(["ok", "fail", "ok", "fail", "fail", "fail"])

    def fake_rpc(rpc_url: str, method: str, params: list, *, retries: int = 5) -> dict:
        if next(outcomes) == "fail":
            raise RuntimeError("simulated 500")
        return {"result": {"data": [{}] * 5}}

    def call() -> tuple[str, Exception | None]:
        try:
            _mfh._rpc("fake://rpc", "getTransactionsForAddress", [], retries=1)
            return "ok", None
        except Exception as exc:  # noqa: BLE001 -- self-check needs the exact exception
            return "failed", exc

    original_rpc = _mfh._rpc
    _mfh._rpc = fake_rpc
    try:
        tracker2 = RpcUsageTracker()
        restore = install_rate_limited_rpc(
            max_rps=1000.0, helius_url="fake://helius-unused", max_consecutive_failures=3, tracker=tracker2
        )
        try:
            outcome, _ = call()
            assert outcome == "ok", outcome
            assert tracker2.total_credits == 10, tracker2.total_credits

            outcome, exc = call()  # 1st consecutive failure
            assert outcome == "failed" and not isinstance(exc, PilotAbortedRateLimited), (outcome, exc)

            outcome, _ = call()  # success resets the counter
            assert outcome == "ok", outcome
            assert tracker2.total_credits == 20, tracker2.total_credits

            outcome, exc = call()  # 1st consecutive failure again
            assert outcome == "failed" and not isinstance(exc, PilotAbortedRateLimited), (outcome, exc)
            outcome, exc = call()  # 2nd consecutive failure
            assert outcome == "failed" and not isinstance(exc, PilotAbortedRateLimited), (outcome, exc)
            outcome, exc = call()  # 3rd consecutive failure -> abort
            assert outcome == "failed" and isinstance(exc, PilotAbortedRateLimited), (outcome, exc)
            assert exc.consecutive_failures == 3, exc.consecutive_failures
        finally:
            restore()
    finally:
        _mfh._rpc = original_rpc


def _self_check_429_policy() -> None:
    import email.message

    def make_429(retry_after: str | None) -> urllib.error.HTTPError:
        hdrs = email.message.Message()
        if retry_after is not None:
            hdrs["Retry-After"] = retry_after
        return urllib.error.HTTPError(
            url="fake://rpc", code=429, msg="Too Many Requests", hdrs=hdrs, fp=None
        )

    assert _retry_after_seconds(make_429("7")) == 7.0
    assert _retry_after_seconds(make_429(None)) is None

    # 429 retries with backoff (sleep mocked -- no real wait): 1st failure
    # honors Retry-After (0.01, overriding the internal backoff clock);
    # 2nd failure has no Retry-After, so it falls back to the internal
    # backoff clock, which had already doubled to 2.0 after the 1st retry.
    # Never trips the 3-failure breaker; succeeds once the fake RPC stops
    # failing.
    attempts = {"n": 0}

    def fake_429_then_ok(rpc_url: str, method: str, params: list, *, retries: int = 1) -> dict:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise make_429("0.01")
        if attempts["n"] == 2:
            raise make_429(None)
        return {"result": {"data": []}}

    sleep_calls: list[float] = []
    original_rpc = _mfh._rpc
    original_sleep = time.sleep
    _mfh._rpc = fake_429_then_ok
    time.sleep = lambda s: sleep_calls.append(s)
    try:
        tracker = RpcUsageTracker()
        # helius_max_rps=1000 here on purpose -- this test isolates the
        # 429-backoff sleeps from the RateLimiter's OWN pacing sleep (tested
        # separately below), which would otherwise also land in sleep_calls.
        restore = install_rate_limited_rpc(
            max_rps=1000.0,
            helius_url="fake://helius",
            helius_max_rps=1000.0,
            max_consecutive_failures=3,
            tracker=tracker,
        )
        try:
            result = _mfh._rpc("fake://helius", "getSlot", [])
        finally:
            restore()
    finally:
        _mfh._rpc = original_rpc
        time.sleep = original_sleep
    assert result == {"result": {"data": []}}, result
    assert attempts["n"] == 3, attempts
    # Each retry also re-paces through limiter.wait() (tiny ~0.001s sleeps at
    # helius_max_rps=1000) -- filter those out to isolate the 429-backoff
    # sleeps specifically: Retry-After (0.01) honored on the 1st failure,
    # then the internal backoff clock (already doubled to 2.0) on the 2nd.
    backoff_sleeps = [s for s in sleep_calls if s >= 0.005]
    assert backoff_sleeps == [0.01, 2.0], sleep_calls

    # Sustained 429 (zero success window via max_429_stall_seconds=0.0)
    # aborts citing the stall -- never the 3-failure breaker (429 never
    # increments consecutive_failures).
    def always_429(rpc_url: str, method: str, params: list, *, retries: int = 1) -> dict:
        raise make_429(None)

    _mfh._rpc = always_429
    time.sleep = lambda s: None
    try:
        tracker2 = RpcUsageTracker()
        restore = install_rate_limited_rpc(
            max_rps=1000.0,
            helius_url="fake://helius",
            max_consecutive_failures=3,
            tracker=tracker2,
            max_429_stall_seconds=0.0,
        )
        try:
            try:
                _mfh._rpc("fake://helius", "getSlot", [])
                raise AssertionError("expected PilotAbortedRateLimited")
            except PilotAbortedRateLimited as exc:
                assert exc.consecutive_failures == 0, exc
                assert "429" in exc.last_error, exc
        finally:
            restore()
    finally:
        _mfh._rpc = original_rpc
        time.sleep = original_sleep

    # Non-429 error: breaker still trips after 3 CONSECUTIVE failures.
    def fake_5xx(rpc_url: str, method: str, params: list, *, retries: int = 1) -> dict:
        raise RuntimeError("simulated 500")

    _mfh._rpc = fake_5xx
    try:
        tracker3 = RpcUsageTracker()
        restore = install_rate_limited_rpc(
            max_rps=1000.0, helius_url="fake://helius", max_consecutive_failures=3, tracker=tracker3
        )
        try:
            for _ in range(2):
                try:
                    _mfh._rpc("fake://helius", "getSlot", [])
                    raise AssertionError("expected RuntimeError")
                except PilotAbortedRateLimited:
                    raise AssertionError("should not abort before the 3rd consecutive failure")
                except RuntimeError:
                    pass
            try:
                _mfh._rpc("fake://helius", "getSlot", [])
                raise AssertionError("expected abort on 3rd consecutive failure")
            except PilotAbortedRateLimited as exc:
                assert exc.consecutive_failures == 3, exc
        finally:
            restore()
    finally:
        _mfh._rpc = original_rpc

    # Helius gets its OWN (slower) limiter, independent of max_rps.
    def fake_ok(rpc_url: str, method: str, params: list, *, retries: int = 1) -> dict:
        return {"result": {"data": []}}

    _mfh._rpc = fake_ok
    try:
        tracker4 = RpcUsageTracker()
        restore = install_rate_limited_rpc(
            max_rps=1000.0,
            helius_url="fake://helius",
            helius_max_rps=20.0,
            max_consecutive_failures=3,
            tracker=tracker4,
        )
        try:
            t0 = time.monotonic()
            _mfh._rpc("fake://helius", "getSlot", [])
            _mfh._rpc("fake://helius", "getSlot", [])
            assert time.monotonic() - t0 >= 0.04, "Helius limiter (20 req/s) did not pace the 2nd call"
            t1 = time.monotonic()
            _mfh._rpc("fake://quicknode", "getSlot", [])
            _mfh._rpc("fake://quicknode", "getSlot", [])
            assert time.monotonic() - t1 < 0.04, "non-Helius calls must not be paced by the Helius limiter"
        finally:
            restore()
    finally:
        _mfh._rpc = original_rpc


def _self_check_credits_formula() -> None:
    # Matches the worked examples on helius.dev/docs/billing/credits (read
    # 2026-10-08): 1-100 full tx = 10 credits (one started block, minimum);
    # 250 = 30; 1000 = 100.
    assert _credits_for_tx_count(0) == 0
    assert _credits_for_tx_count(1) == 10
    assert _credits_for_tx_count(100) == 10
    assert _credits_for_tx_count(101) == 20
    assert _credits_for_tx_count(250) == 30
    assert _credits_for_tx_count(1000) == 100


def _self_check_survival() -> None:
    def _resolved(base_reserves: int, quote_reserves: int) -> dict[str, Any]:
        return {
            "signature": "SIG",
            "block_time": 0,
            "event": {
                "status": "decoded",
                "event_type": "pumpswap_buy",
                "pool_base_token_reserves_raw": base_reserves,
                "pool_quote_token_reserves_raw": quote_reserves,
            },
        }

    # Survives: price at marker (quote/base = 60/1000=0.06) is exactly the
    # same as at migration (600/10000=0.06) -- ratio 1.0 >= 0.40.
    survived = _survival_system_count_from_resolved(_resolved(10_000, 600), _resolved(10_000, 600))
    assert survived is True, survived

    # Dies: price at marker is 10% of price at migration -- ratio 0.10 < 0.40.
    died = _survival_system_count_from_resolved(_resolved(10_000, 600), _resolved(10_000, 60))
    assert died is False, died

    # Undeterminable: either side unresolved (grade nao achou swap no
    # bucket) -- nunca inferido como 0.
    assert _survival_system_count_from_resolved(None, _resolved(10_000, 600)) is None
    assert _survival_system_count_from_resolved(_resolved(10_000, 600), None) is None
    assert _survival_system_count_from_resolved(None, None) is None


def _self_check_summary() -> None:
    results = [
        PilotTokenResult("P1", "S1", 0, 100, 5, 5.0, 10, 2, 2, 100.0, 10, 3, 1.5, True),
        PilotTokenResult("P2", "S2", 0, 300, 10, 3.33, 20, 2, 1, 50.0, 20, 4, 2.5, False),
        PilotTokenResult("P3", "S3", 0, 50, 0, 0.0, 0, 0, 0, 0.0, 5, 2, 1.0, None),
    ]
    summary = summarize_pilot(results, k_windows_used=2)
    assert summary.n_sampled == 3, summary
    assert summary.n_survival_determinable == 2, summary
    assert summary.n_survived_system_count == 1, summary
    assert summary.survival_rate_system_count == 0.5, summary
    # k_windows_used=2 -> avg_migrations_per_window = 3/2 = 1.5;
    # signals_per_window = 2/2 = 1.0; k_proposed = ceil(30/1.0) = 30; avg
    # elapsed over ALL 3 tokens (1.5, 2.5, 1.0) = 5.0/3; estimated =
    # 30 * 1.5 * (5.0/3) = 75.0.
    assert summary.avg_migrations_per_window == 1.5, summary
    assert summary.h2_signals_per_window_system_count == 1.0, summary
    assert summary.k_windows_proposed_for_n30_signals == 30, summary
    assert summary.estimated_total_seconds_for_k_proposed == 75.0, summary
    # calls = [3, 4, 2] -> sorted [2,3,4]; median (p50, index round(0.5*2)=1)=3;
    # p90 (index round(0.9*2)=2) = 4.
    assert summary.median_rpc_calls_per_pool == 3.0, summary
    assert summary.p90_rpc_calls_per_pool == 4.0, summary
    # avg_pct_failed_tx = (5.0 + 3.33 + 0.0) / 3.
    assert round(summary.avg_pct_failed_tx, 2) == round((5.0 + 3.33 + 0.0) / 3, 2), summary


def _self_check_run_pilot_token_wiring() -> None:
    from unittest.mock import patch

    migration_sig = "SIGMIGRATION"
    pool_mint = "POOLpump"
    window_start = 2_000_000
    sig_t0 = "SIG_T0"
    sig_marker = "SIG_MARKER"
    sig_failed = "SIG_FAILED"
    sig_last5min = "SIG_LAST5MIN"
    marker_offset = SIGNAL_MARKER_SECONDS  # bucket index = marker_offset // 5

    def _fake_swap_tx(signature: str, block_time: int) -> dict[str, Any]:
        from benchmarks.carbon_decoder_parity_v1.parity import (
            PUMPSWAP_BUY_EVENT_DISCRIMINATOR,
            PUMPSWAP_PROGRAM_ID,
        )
        import base64 as _b64

        payload = _b64.b64encode(PUMPSWAP_BUY_EVENT_DISCRIMINATOR + b"\x00" * 16).decode("ascii")
        return {
            "slot": 1,
            "blockTime": block_time,
            "transaction": {"signatures": [signature], "message": {"accountKeys": [PUMPSWAP_PROGRAM_ID]}},
            "meta": {
                "logMessages": [
                    f"Program {PUMPSWAP_PROGRAM_ID} invoke [1]",
                    f"Program data: {payload}",
                    f"Program {PUMPSWAP_PROGRAM_ID} success",
                ]
            },
        }

    raw_rows_by_sig = {
        sig_t0: _fake_swap_tx(sig_t0, window_start),
        sig_marker: _fake_swap_tx(sig_marker, window_start + marker_offset),
    }

    def fake_rpc(rpc_url: str, method: str, params: list, *, retries: int = 5) -> dict:
        if method == "getSignaturesForAddress":
            assert params[0] == pool_mint
            return {
                "result": [
                    {"signature": sig_t0, "blockTime": window_start, "err": None},
                    {
                        "signature": sig_last5min,
                        "blockTime": window_start + marker_offset - 50,
                        "err": None,
                    },
                    {
                        "signature": sig_failed,
                        "blockTime": window_start + marker_offset - 100,
                        "err": {"InstructionError": [0, "boom"]},
                    },
                    {"signature": sig_marker, "blockTime": window_start + marker_offset, "err": None},
                ]
            }
        if method == "getTransaction":
            signature = params[0]
            row = raw_rows_by_sig.get(signature)
            if row is None:
                raise AssertionError(f"unexpected getTransaction for {signature}")
            return {"result": row}
        raise AssertionError(f"unexpected RPC call in self-check: {method} {params}")

    class _FakeCarbon:
        def request(self, payload: dict[str, Any]) -> dict[str, Any]:
            event_key = payload["items"][0]["event_key"]
            signature = event_key.split(":")[0]
            reserves = {sig_t0: (1000, 600), sig_marker: (500, 900)}[signature]
            return {
                "type": "carbon_canonical_batch",
                "batch_id": payload["batch_id"],
                "items": [
                    {
                        "event_key": event_key,
                        "status": "decoded",
                        "event_type": "pumpswap_buy",
                        "signature": signature,
                        "pool_base_token_reserves_raw": reserves[0],
                        "pool_quote_token_reserves_raw": reserves[1],
                        "lp_fee_raw": 7,
                    }
                ],
            }

    with patch(
        "benchmarks.move_first_h_coverage_audit_v0.sample_migration_account._rpc",
        side_effect=fake_rpc,
    ):
        tracker = RpcUsageTracker()
        restore = install_rate_limited_rpc(
            max_rps=1000.0, helius_url="fake://helius-unused", max_consecutive_failures=99, tracker=tracker
        )
        try:
            rotator = EndpointRotator(["fake://rpc"])
            result = run_pilot_token(
                _FakeCarbon(),
                MigrationCandidate(
                    pool_mint=pool_mint,
                    migration_signature=migration_sig,
                    migration_block_time=window_start,
                ),
                rotator=rotator,
                tracker=tracker,
            )
        finally:
            restore()
    assert result.migration_block_time == window_start, result
    assert result.n_signatures_in_window == 4, result
    assert result.n_failed_tx == 1, result
    assert result.pct_failed_tx == 25.0, result
    # so sig_last5min cai em [marker-5min, marker) E e bem-sucedida.
    assert result.n_successful_trades_last_5min_before_marker == 1, result
    assert result.n_events_decoded == 2, result
    assert result.n_events_with_reserves_and_fee == 2, result
    assert result.pct_decoded_with_reserves_and_fee == 100.0, result
    # 1 getSignaturesForAddress + 2 getTransaction (bucket 0 e bucket do
    # marco resolvem na primeira tentativa) = 3 chamadas/creditos.
    assert result.n_rpc_calls == 3, result
    assert result.estimated_credits == 3, result
    assert result.survived_20min_system_count is not None, result


class _FakeCarbonNoop:
    """Carbon de mentira que nunca deveria ser chamado -- usado nos
    self-checks do benchmark da grade onde todos os buckets ficam vazios
    (sem assinatura nenhuma), logo nenhum getTransaction/decode acontece."""

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("nao deveria decodificar nada -- buckets vazios neste self-check")


def _self_check_grid_benchmark() -> None:
    from unittest.mock import patch

    def fake_rpc_empty(rpc_url: str, method: str, params: list, *, retries: int = 5) -> dict:
        if method == "getSignaturesForAddress":
            return {"result": []}
        raise AssertionError(f"unexpected method: {method}")

    candidate = MigrationCandidate(pool_mint="POOLpump", migration_signature="SIG", migration_block_time=0)

    with patch(
        "benchmarks.move_first_h_coverage_audit_v0.sample_migration_account._rpc",
        side_effect=fake_rpc_empty,
    ):
        tracker = RpcUsageTracker()
        restore = install_rate_limited_rpc(
            max_rps=1000.0, helius_url="fake://helius-unused", max_consecutive_failures=99, tracker=tracker
        )
        try:
            rotator = EndpointRotator(["fake://rpc"])
            # Orcamento generoso + lista de assinaturas vazia -> percorre as
            # ~960 buckets sem NENHUM getTransaction (nenhum bucket tem
            # candidato), completo dentro do orcamento.
            result = run_price_grid_benchmark(
                _FakeCarbonNoop(), candidate, rotator=rotator, tracker=tracker, time_budget_seconds=30.0
            )
        finally:
            restore()
    assert result.completed is True, result
    assert result.n_buckets_total == POOL_TRADE_WINDOW_SECONDS // GRID_BUCKET_SECONDS, result
    assert result.n_buckets_processed == result.n_buckets_total, result
    assert result.n_buckets_with_swap_resolved == 0, result
    assert result.n_rpc_calls == 1, result  # so a enumeracao -- nenhum getTransaction

    # Orcamento ja esgotado antes de processar qualquer bucket ->
    # completed=False, numeros parciais honestos, nunca extrapolados.
    with patch(
        "benchmarks.move_first_h_coverage_audit_v0.sample_migration_account._rpc",
        side_effect=fake_rpc_empty,
    ):
        tracker2 = RpcUsageTracker()
        restore = install_rate_limited_rpc(
            max_rps=1000.0, helius_url="fake://helius-unused", max_consecutive_failures=99, tracker=tracker2
        )
        try:
            rotator2 = EndpointRotator(["fake://rpc"])
            result2 = run_price_grid_benchmark(
                _FakeCarbonNoop(), candidate, rotator=rotator2, tracker=tracker2, time_budget_seconds=-1.0
            )
        finally:
            restore()
    assert result2.completed is False, result2
    assert result2.n_buckets_processed == 0, result2


def _self_check_checkpoint() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "checkpoint.json"
        assert _load_checkpoint(path) == {"windows_done": [], "candidates": [], "tokens": {}}

        data = _load_checkpoint(path)
        data["windows_done"].append([1000, 1600])
        data["tokens"]["POOLpump"] = {"pool_mint": "POOLpump"}
        _save_checkpoint(path, data)

        reloaded = _load_checkpoint(path)
        assert reloaded["windows_done"] == [[1000, 1600]], reloaded
        assert reloaded["tokens"]["POOLpump"]["pool_mint"] == "POOLpump", reloaded


def _self_check() -> None:
    _self_check_rate_limiter_and_breaker()
    _self_check_429_policy()
    _self_check_credits_formula()
    _self_check_survival()
    _self_check_summary()
    _self_check_run_pilot_token_wiring()
    _self_check_grid_benchmark()
    _self_check_checkpoint()
    print(
        "self-check OK: rate limiter + consecutive-failure breaker + 429 slow-down policy + "
        "credit tracker + credits formula + survival system-count (grade de 5s) + summary "
        "arithmetic (median/p90 + K-per-window) + run_pilot_token wiring (Estagio 1 barato) + "
        "grid benchmark (completed/budget-exceeded) + checkpoint round-trip"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument(
        "--k", type=int, default=PILOT_K_DEFAULT, help="numero de janelas sorteadas"
    )
    parser.add_argument("--window-minutes", type=int, default=PILOT_WINDOW_MINUTES_DEFAULT)
    parser.add_argument("--seed", type=int, default=PILOT_SEED)
    parser.add_argument("--lookback-start", default=PILOT_LOOKBACK_START)
    parser.add_argument("--lookback-end", default=PILOT_LOOKBACK_END)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument(
        "--max-rps",
        type=float,
        default=DEFAULT_MAX_RPS,
        help="teto pra endpoints NAO-Helius (QuickNode/publico no rodizio do Estagio 2)",
    )
    parser.add_argument(
        "--helius-max-rps",
        type=float,
        default=HELIUS_MAX_RPS_DEFAULT,
        help="teto pra Helius (operador, Fase E parte 2: 1 req/s)",
    )
    parser.add_argument(
        "--plan-rps",
        type=float,
        default=None,
        help="RPS medido do plano -- se informado, --max-rps (nao-Helius) e limitado a 50%% disso",
    )
    parser.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=DEFAULT_MAX_CONSECUTIVE_FAILURES,
        help="falhas de RPC consecutivas NAO-429 (cada uma ja pos-backoff) antes de parar",
    )
    parser.add_argument(
        "--max-429-stall-seconds",
        type=float,
        default=MAX_429_STALL_SECONDS,
        help="aborta se passar este tempo em 429 sustentado sem nenhum sucesso (operador: ~10min)",
    )
    parser.add_argument(
        "--checkpoint", type=Path, default=Path("artifacts/sig_fast_h2_pilot_v0/checkpoint.json")
    )
    parser.add_argument(
        "--grid-benchmark-seconds",
        type=float,
        default=90.0,
        help="orcamento de tempo (s) pro benchmark da grade completa (Estagio 2) num token real",
    )
    parser.add_argument(
        "--skip-grid-benchmark",
        action="store_true",
        help="pula o benchmark da grade completa (so mede o Estagio 1 barato)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("artifacts/sig_fast_h2_pilot_v0/report.json")
    )
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0

    max_rps = args.max_rps
    if args.plan_rps is not None:
        max_rps = min(max_rps, args.plan_rps * 0.5)
    print(
        f"[piloto] rate limit efetivo: nao-Helius={max_rps:.2f} req/s "
        f"(--max-rps={args.max_rps}, --plan-rps={args.plan_rps}), Helius={args.helius_max_rps:.2f} req/s"
    )

    # Stage 1 (enumeration) stays pinned to Helius -- see module docstring.
    rpc_url = _load_rpc_url()
    tracker = RpcUsageTracker()
    restore_rpc = install_rate_limited_rpc(
        max_rps=max_rps,
        helius_url=rpc_url,
        helius_max_rps=args.helius_max_rps,
        max_consecutive_failures=args.max_consecutive_failures,
        tracker=tracker,
        max_429_stall_seconds=args.max_429_stall_seconds,
    )
    # Stage 2 (per-pool trade fetch) rotates across H2_BACKFILL_RPC_URLS
    # (e.g. QuickNode free tier) + the public cluster endpoint, Helius LAST
    # (load_rotation_rpc_urls, Fase E parte 2 -- poupa a Helius pra Estagio
    # 1). Goes through the same _mfh._rpc the line above just wrapped, so
    # the rate limiter / breaker / credit tracker apply uniformly regardless
    # of which endpoint a given call lands on.
    rotator = EndpointRotator(load_rotation_rpc_urls())

    checkpoint = _load_checkpoint(args.checkpoint)
    windows = sample_calendar_windows(
        start_date=args.lookback_start,
        end_date=args.lookback_end,
        window_minutes=args.window_minutes,
        k=args.k,
        seed=args.seed,
    )
    windows_done = {tuple(w) for w in checkpoint["windows_done"]}
    candidates_by_pool: dict[str, MigrationCandidate] = {
        c["pool_mint"]: MigrationCandidate(**c) for c in checkpoint["candidates"]
    }
    tokens_done: dict[str, dict[str, Any]] = checkpoint["tokens"]

    # Enumeracao e Stage 2 abortam de forma independente -- se a enumeracao
    # parar numa janela (ex. 429 sustentado na Helius), os candidatos JA
    # encontrados em janelas anteriores ainda vao pro Stage 2 (que prioriza
    # QuickNode/publico, nao a Helius), em vez de descartar esse trabalho.
    # Isso serve o proprio pedido de checkpoint do operador: nao refazer (ou
    # jogar fora) o que ja foi encontrado.
    enumeration_aborted = False
    enumeration_abort_reason: str | None = None
    stage2_aborted = False
    stage2_abort_reason: str | None = None
    k_windows_used = len(windows_done & set(windows))
    try:
        for window in windows:
            if window in windows_done:
                continue
            try:
                new_candidates = fetch_migrations_in_windows(
                    rpc_url, window_start=window[0], window_end=window[1]
                )
            except PilotAbortedRateLimited as exc:
                enumeration_aborted = True
                enumeration_abort_reason = str(exc)
                print(f"[piloto] PAROU durante a enumeracao (janela {window}): {exc}")
                break
            except Exception as exc:
                enumeration_aborted = True
                enumeration_abort_reason = (
                    f"falha na enumeracao da janela {window}: {type(exc).__name__}: {exc}"
                )
                print(f"[piloto] PAROU durante a enumeracao: {enumeration_abort_reason}")
                break
            for candidate in new_candidates:
                candidates_by_pool.setdefault(candidate.pool_mint, candidate)
            windows_done.add(window)
            k_windows_used = len(windows_done & set(windows))
            checkpoint["windows_done"] = [list(w) for w in windows_done]
            checkpoint["candidates"] = [asdict(c) for c in candidates_by_pool.values()]
            _save_checkpoint(args.checkpoint, checkpoint)
            print(
                f"[piloto] janela {window}: {len(new_candidates)} migracoes novas, "
                f"{len(candidates_by_pool)} candidatas no total"
            )

        grid_benchmark: GridBenchmarkResult | None = None
        if candidates_by_pool:
            from benchmarks.integrated_market_signal_plane_v1.live_shadow import (
                JsonLineProcess,
                _carbon_command,
            )

            carbon = JsonLineProcess(
                _carbon_command(args.cargo), ready_type="carbon_stream_decoder_ready"
            )
            carbon.start()
            try:
                for pool_mint, candidate in candidates_by_pool.items():
                    if pool_mint in tokens_done:
                        continue
                    try:
                        result = run_pilot_token(carbon, candidate, rotator=rotator, tracker=tracker)
                    except PilotAbortedRateLimited as exc:
                        stage2_aborted = True
                        stage2_abort_reason = str(exc)
                        print(f"[piloto] PAROU: {exc}")
                        break
                    except Exception as exc:  # token isolado, nao e rajada de 429
                        print(
                            f"[piloto] token {pool_mint} falhou "
                            f"(nao abortou o piloto): {type(exc).__name__}: {exc}"
                        )
                        continue
                    tokens_done[pool_mint] = asdict(result)
                    checkpoint["tokens"] = tokens_done
                    _save_checkpoint(args.checkpoint, checkpoint)
                    print(
                        f"[piloto] token {result.pool_mint}: assinaturas={result.n_signatures_in_window} "
                        f"falha%={result.pct_failed_tx} decoded={result.n_events_decoded} "
                        f"sobreviveu={result.survived_20min_system_count} "
                        f"chamadas={result.n_rpc_calls} tempo={result.elapsed_seconds}s "
                        f"total_creditos_acumulado={tracker.total_credits}"
                    )

                # Benchmark da grade COMPLETA (Estagio 2, regra 4) -- so pra
                # medir custo real/extrapolar, nunca pra julgar H2. Roda em
                # UM token conhecido, com orcamento de tempo; nunca insiste
                # se o Estagio 1 ja abortou (respeita o mesmo sinal de parada).
                if not stage2_aborted and not args.skip_grid_benchmark and candidates_by_pool:
                    benchmark_candidate = next(iter(candidates_by_pool.values()))
                    print(
                        f"[piloto] benchmark da grade completa (Estagio 2) em "
                        f"{benchmark_candidate.pool_mint}, orcamento {args.grid_benchmark_seconds}s..."
                    )
                    try:
                        grid_benchmark = run_price_grid_benchmark(
                            carbon,
                            benchmark_candidate,
                            rotator=rotator,
                            tracker=tracker,
                            time_budget_seconds=args.grid_benchmark_seconds,
                        )
                        print(
                            f"[piloto] benchmark grade: buckets={grid_benchmark.n_buckets_processed}/"
                            f"{grid_benchmark.n_buckets_total} resolvidos={grid_benchmark.n_buckets_with_swap_resolved} "
                            f"chamadas={grid_benchmark.n_rpc_calls} tempo={grid_benchmark.elapsed_seconds}s "
                            f"completo={grid_benchmark.completed}"
                        )
                    except PilotAbortedRateLimited as exc:
                        print(f"[piloto] benchmark da grade PAROU (429 sustentado): {exc}")
            finally:
                carbon.close()
    finally:
        restore_rpc()

    aborted = enumeration_aborted or stage2_aborted
    abort_reason = stage2_abort_reason or enumeration_abort_reason

    results = [PilotTokenResult(**v) for v in tokens_done.values()]
    summary = summarize_pilot(results, k_windows_used=k_windows_used)
    payload = {
        "version": VERSION,
        "classification": "SYSTEMS_COST_AND_COVERAGE_ONLY_NOT_AN_ECONOMIC_TEST",
        "aborted_rate_limited": aborted,
        "abort_reason": abort_reason,
        "enumeration_aborted": enumeration_aborted,
        "enumeration_abort_reason": enumeration_abort_reason,
        "stage2_aborted": stage2_aborted,
        "stage2_abort_reason": stage2_abort_reason,
        "k_windows_requested": args.k,
        "k_windows_used": k_windows_used,
        "window_minutes": args.window_minutes,
        "windows_sampled": [list(w) for w in windows],
        "n_candidates_found": len(candidates_by_pool),
        "seed": args.seed,
        "lookback_start": args.lookback_start,
        "lookback_end": args.lookback_end,
        "excluded_blocks": {
            "discovery": [DISCOVERY_BLOCK_START, DISCOVERY_BLOCK_END],
            "confirmation": [CONFIRMATION_BLOCK_START, CONFIRMATION_BLOCK_END],
        },
        "rate_limit": {
            "max_rps_effective_non_helius": max_rps,
            "helius_max_rps": args.helius_max_rps,
            "max_consecutive_failures": args.max_consecutive_failures,
            "max_429_stall_seconds": args.max_429_stall_seconds,
        },
        "checkpoint_path": str(args.checkpoint),
        "tokens": [asdict(r) for r in results],
        "summary": asdict(summary),
        "grid_benchmark": asdict(grid_benchmark) if grid_benchmark is not None else None,
        "rpc_usage": {
            "total_credits": tracker.total_credits,
            "n_calls": len(tracker.calls),
            "calls": [asdict(entry) for entry in tracker.calls],
        },
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(text)
    return 1 if aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
