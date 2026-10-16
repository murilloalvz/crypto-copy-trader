"""RPC Solana padrao, SOMENTE LEITURA (getSlot/getBlockTime/getBlock/getSignaturesForAddress/getTransaction).

Nada aqui assina ou envia transacao. Endpoints: variavel de ambiente `POS_RUNNER_RPC_URLS` (lista separada
por virgula, ex.: um QuickNode do operador) ou, sem ela, os RPCs publicos abaixo. O RPC publico limita por IP,
entao cada endpoint tem o seu limitador adaptativo (o mesmo `RateLimiter` do bot) e falhas de transporte
fazem rodizio de endpoint.

A busca de slot por tempo e a ancora de assinatura foram COPIADAS (nao importadas) de
`benchmarks/sig_fast_v0/h2_enumeration_no_helius_v0.py` (branch `research/rust-signal-plane-live-shadow-v0`,
commit da37ce6, enumeracao do H2 sem Helius): mesma garantia de nunca cair ANTES do alvo (undershoot), mesmo
nudge so para frente em slot pulado e mesma falha explicita (`SlotTimeUnresolvable`) em vez de resposta inventada.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Optional, Sequence

from urllib.parse import urlsplit

import requests

from ..http import RateLimiter

log = logging.getLogger("signals_mvp.pos_runner.rpc")

ENV_ENDPOINTS = "POS_RUNNER_RPC_URLS"
# so o RPC publico oficial tem o historico longo (medido 2026-10-15: o publicnode apaga blocos com mais de
# ~2 dias e responde -32001 "cleaned up"). Endpoint podado e tirado do rodizio, nunca lido como "slot pulado".
DEFAULT_ENDPOINTS = ("https://api.mainnet-beta.solana.com",)

# erros JSON-RPC de "slot sem bloco" (slot pulado): um FATO sobre o slot, nao falha de transporte
SKIPPED_SLOT_CODES = {-32004, -32007, -32009}
PRUNED_CODE = -32001
# limite DIARIO do plano (ex.: QuickNode "daily request limit reached") -- NAO e um 429 passageiro (a
# AIMD normal nao se recupera num dia inteiro parado): o endpoint sai do rodizio por uma pausa longa, mas
# limitada, para sondar sozinho quando o provedor liberar de novo, sem travar as janelas que ainda nao
# foram tentadas no outro endpoint (decisao operacional de 2026-10-16: "nao esperar parado").
DAILY_LIMIT_CODE = -32003
DAILY_LIMIT_PAUSE_S = 3600.0

AVG_SLOT_SECONDS = 0.4
MAX_SKIPPED_SLOT_NUDGE = 50
MAX_BRACKET_EXPANSIONS = 40
MAX_BINARY_SEARCH_ITERATIONS = 64
SIGNATURES_PAGE_SIZE = 1000


class RpcError(Exception):
    """Falha de RPC. `kind`: transport | app | exhausted."""

    def __init__(self, kind: str, message: str = "", code: Optional[int] = None):
        super().__init__(f"{kind}: {message}" if message else kind)
        self.kind = kind
        self.code = code


class SlotTimeUnresolvable(RuntimeError):
    """Nao deu para resolver um blockTime/assinatura real (falha explicita, nunca um valor por baixo)."""


def host_of(url: str) -> str:
    """So o host do endpoint para log: URL de RPC pago costuma levar a chave no caminho ou na query."""
    return urlsplit(url).hostname or "?"


def endpoints_from_env(env: Optional[dict] = None) -> list[str]:
    raw = (env if env is not None else os.environ).get(ENV_ENDPOINTS, "")
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    return urls or list(DEFAULT_ENDPOINTS)


class SolanaRpc:
    """JSON-RPC com limitador por endpoint, rodizio e repeticao em falha de transporte."""

    def __init__(
        self,
        endpoints: Sequence[str],
        per_min: float = 150.0,
        burst: int = 4,
        timeout_s: float = 40.0,
        max_attempts: int = 8,
        session: Optional[requests.Session] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        post: Optional[Callable[[str, dict], Any]] = None,
    ):
        if not endpoints:
            raise ValueError("sem endpoint RPC")
        self.endpoints = list(endpoints)
        self.limiters = {
            url: RateLimiter(per_min, burst, pause_s=5.0, pause_max_s=120.0, clock=clock, sleep=sleep, min_per_min=20.0)
            for url in self.endpoints
        }
        self.timeout = (10.0, timeout_s)
        self.max_attempts = max_attempts
        self.session = session or requests.Session()
        self._clock = clock
        self._sleep = sleep
        self._post = post
        self._next = 0
        self.calls = 0
        self.failures = 0
        self.pruned: set[str] = set()   # endpoints sem o historico pedido (saem do rodizio)
        self.daily_limited: dict[str, float] = {}   # endpoint -> ate quando fica de fora do rodizio

    def _send(self, url: str, payload: dict) -> Any:
        if self._post is not None:
            return self._post(url, payload)
        response = self.session.post(url, json=payload, timeout=self.timeout)
        if response.status_code == 429:
            code = None
            try:
                code = (response.json() or {}).get("error", {}).get("code")
            except ValueError:
                pass
            if code == DAILY_LIMIT_CODE:
                raise RpcError("transport", "limite diario do plano", DAILY_LIMIT_CODE)
            raise RpcError("transport", "HTTP 429", 429)
        if response.status_code >= 400:
            raise RpcError("transport", f"HTTP {response.status_code}", response.status_code)
        try:
            return response.json()
        except ValueError:
            raise RpcError("transport", "resposta nao e JSON") from None

    def _pause_daily_limit(self, url: str) -> None:
        self.daily_limited[url] = self._clock() + DAILY_LIMIT_PAUSE_S
        log.warning("rpc: %s bateu o limite diario do plano -- pausado %.0f min (outros endpoints seguem; retomo sozinho)",
                    host_of(url), DAILY_LIMIT_PAUSE_S / 60.0)

    def call_raw(self, method: str, params: list) -> dict:
        """Resposta JSON-RPC inteira ({result} ou {error}). Erro de transporte -> rodizio e nova tentativa."""
        last: Optional[Exception] = None
        for attempt in range(self.max_attempts):
            now = self._clock()
            live = [u for u in self.endpoints if u not in self.pruned and self.daily_limited.get(u, 0.0) <= now]
            if not live:
                # todos podados ou no limite diario agora: tenta mesmo assim o que nao foi podado (a pausa expira sozinha)
                live = [u for u in self.endpoints if u not in self.pruned]
            if not live:
                raise RpcError("exhausted", f"{method}: nenhum endpoint com o historico pedido")
            url = live[(self._next + attempt) % len(live)]
            limiter = self.limiters[url]
            try:
                limiter.acquire(max_wait_s=300.0)
            except Exception as exc:  # em pausa de 429: tenta outro endpoint
                last = exc
                wait = limiter.blocked_for()
                if attempt + 1 >= len(self.endpoints):
                    self._sleep(min(wait, 30.0) if wait > 0 else 1.0)
                continue
            self.calls += 1
            try:
                body = self._send(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            except (requests.RequestException, RpcError) as exc:
                self.failures += 1
                last = exc
                code = getattr(exc, "code", None)
                if code == DAILY_LIMIT_CODE:
                    self._pause_daily_limit(url)
                elif code == 429:
                    limiter.on_429()
                else:
                    limiter.on_error_pause(2.0 * (attempt + 1))
                log.debug("rpc %s %s falhou em %s: %s", method, params[:1], host_of(url), type(exc).__name__)
                continue
            if not isinstance(body, dict):
                self.failures += 1
                last = RpcError("transport", "corpo inesperado")
                continue
            error = body.get("error")
            if isinstance(error, dict) and error.get("code") == DAILY_LIMIT_CODE:
                self.failures += 1
                self._pause_daily_limit(url)
                last = RpcError("transport", "limite diario do plano", DAILY_LIMIT_CODE)
                continue
            if isinstance(error, dict) and error.get("code") in (429, -32429):
                self.failures += 1
                limiter.on_429()
                last = RpcError("transport", "rate limited", 429)
                continue
            if isinstance(error, dict) and error.get("code") == PRUNED_CODE and "cleaned up" in str(error.get("message", "")):
                self.failures += 1
                self.pruned.add(url)
                log.warning("rpc: %s nao tem o historico pedido (bloco apagado) — fora do rodizio", host_of(url))
                last = RpcError("transport", "historico apagado no endpoint", PRUNED_CODE)
                continue
            limiter.on_success()
            self._next = (self._next + attempt) % len(live)
            return body
        raise RpcError("exhausted", f"{method}: {self.max_attempts} tentativas sem resposta ({type(last).__name__ if last else '-'})")

    def call(self, method: str, params: list) -> Any:
        """`result` da chamada; erro de aplicacao levanta RpcError('app', code=...)."""
        body = self.call_raw(method, params)
        error = body.get("error")
        if error is not None:
            code = error.get("code") if isinstance(error, dict) else None
            message = error.get("message", "") if isinstance(error, dict) else str(error)
            raise RpcError("app", f"{method}: {message}", code)
        return body.get("result")

    # -- atalhos ------------------------------------------------------------
    def block_time(self, slot: int) -> Optional[int]:
        """None = slot pulado (sem bloco)."""
        try:
            value = self.call("getBlockTime", [slot])
        except RpcError as exc:
            if exc.kind == "app" and exc.code in SKIPPED_SLOT_CODES:
                return None
            raise
        return None if value is None else int(value)

    def signatures(self, address: str, before: Optional[str] = None, until: Optional[str] = None, limit: int = SIGNATURES_PAGE_SIZE) -> list[dict]:
        opts: dict[str, Any] = {"limit": limit}
        if before:
            opts["before"] = before
        if until:
            opts["until"] = until
        return list(self.call("getSignaturesForAddress", [address, opts]) or [])

    def transaction(self, signature: str) -> Optional[dict]:
        return self.call("getTransaction", [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])

    def token_supply(self, mint: str) -> Optional[float]:
        value = (self.call("getTokenSupply", [mint]) or {}).get("value") or {}
        try:
            return float(value.get("uiAmountString"))
        except (TypeError, ValueError):
            return None


# ---------------------------------------------------------------------------
# slot por tempo e ancora (copiado de h2_enumeration_no_helius_v0.py, ver docstring do modulo)
# ---------------------------------------------------------------------------


def _resolve_forward(rpc: SolanaRpc, slot: int) -> tuple[int, int]:
    probe = max(slot, 0)
    for _ in range(MAX_SKIPPED_SLOT_NUDGE + 1):
        block_time = rpc.block_time(probe)
        if block_time is not None:
            return probe, block_time
        probe += 1
    raise SlotTimeUnresolvable(f"sem blockTime resolvivel a partir do slot {slot} (nudge de {MAX_SKIPPED_SLOT_NUDGE} esgotado)")


def _estimate_slot_for_timestamp(rpc: SolanaRpc, target_time: int) -> int:
    current_slot = rpc.call("getSlot", [{"commitment": "confirmed"}])
    ref_slot, ref_time = _resolve_forward(rpc, max(int(current_slot) - MAX_SKIPPED_SLOT_NUDGE, 0))
    return max(ref_slot - int((ref_time - target_time) / AVG_SLOT_SECONDS), 0)


def find_slot_at_or_after(rpc: SolanaRpc, target_time: int, *, slot_hint: Optional[int] = None) -> tuple[int, int]:
    """Menor slot RESOLVIVEL com blockTime >= target_time (nunca por baixo)."""
    estimate = slot_hint if slot_hint is not None else _estimate_slot_for_timestamp(rpc, target_time)
    lo_slot, lo_time = _resolve_forward(rpc, estimate)
    step = max(int(60 / AVG_SLOT_SECONDS), 1)
    if lo_time >= target_time:
        hi_slot, hi_time = lo_slot, lo_time
        for _ in range(MAX_BRACKET_EXPANSIONS):
            probe_slot = max(hi_slot - step, 0) if lo_slot == hi_slot else max(lo_slot - step, 0)
            lo_slot, lo_time = _resolve_forward(rpc, probe_slot)
            if lo_time < target_time or probe_slot == 0:
                break
            step *= 2
        else:
            raise SlotTimeUnresolvable(f"nao conseguiu delimitar por baixo perto de target_time={target_time}")
        if lo_time >= target_time:
            return lo_slot, lo_time
    else:
        hi_slot, hi_time = lo_slot, lo_time
        for _ in range(MAX_BRACKET_EXPANSIONS):
            if hi_time >= target_time:
                break
            hi_slot, hi_time = _resolve_forward(rpc, hi_slot + step)
            step *= 2
        else:
            raise SlotTimeUnresolvable(f"nao conseguiu delimitar por cima perto de target_time={target_time}")
    lo, hi = lo_slot, hi_slot
    for _ in range(MAX_BINARY_SEARCH_ITERATIONS):
        if hi - lo <= 1:
            break
        mid = (lo + hi) // 2
        mid_slot, mid_time = _resolve_forward(rpc, mid)
        if mid_time >= target_time:
            if mid_slot >= hi:
                break
            hi = mid_slot
        else:
            lo = mid_slot
    else:
        raise SlotTimeUnresolvable(f"busca binaria nao convergiu para target_time={target_time}")
    return _resolve_forward(rpc, hi)


def anchor_signature(rpc: SolanaRpc, slot: int) -> str:
    """Uma assinatura qualquer de um bloco >= `slot`: serve de `before` para paginar a partir daquele instante."""
    probe = slot
    for _ in range(MAX_SKIPPED_SLOT_NUDGE + 1):
        try:
            block = rpc.call("getBlock", [probe, {"transactionDetails": "signatures", "maxSupportedTransactionVersion": 0, "rewards": False}])
        except RpcError as exc:
            if exc.kind == "app" and exc.code in SKIPPED_SLOT_CODES:
                block = None
            else:
                raise
        if block is not None:
            signatures = block.get("signatures") or []
            if signatures:
                return signatures[-1]
        probe += 1
    raise SlotTimeUnresolvable(f"nenhuma assinatura resolvivel a partir do slot {slot} (nudge esgotado)")


def anchor_at_or_after(rpc: SolanaRpc, target_time: int) -> tuple[str, int, int]:
    """(assinatura ancora, slot, blockTime) do primeiro bloco com blockTime >= target_time."""
    slot, block_time = find_slot_at_or_after(rpc, target_time)
    return anchor_signature(rpc, slot), slot, block_time
