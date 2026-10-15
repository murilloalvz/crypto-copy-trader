"""Historico de candles do GeckoTerminal (5m / 1h / 4h) com cache em disco e retomada.

- Pagina para tras com `before_timestamp` (INCLUSIVO; ate 1000 candles por chamada) ate a criacao do pool.
  Medido em 2026-10-15: cada resposta cobre no maximo ~13,5 dias no 5m, e a API as vezes devolve uma pagina
  VAZIA para um trecho que tem dados (a mesma chamada, repetida, vem cheia). Por isso uma pagina vazia nunca
  e lida como "acabou o historico": repete, desloca um candle e, se seguir vazia, anda para tras em passos
  curtos ate a criacao do pool. A API publica so serve os ultimos 180 dias.
- Cache: um JSON por (pool, timeframe, moeda, lado) com o trecho ja coberto. Uma nova chamada so busca o que
  falta (cauda nova e/ou comeco antigo).
- `missing_windows` confere a serie fina contra uma mais grossa (ex.: 5m contra 1h): hora com volume no 1h
  e nenhum candle de 5m dentro = buraco, que `repair` busca de novo.
- O GeckoTerminal OMITE intervalos sem negociacao. `fill_gaps` insere candles "parados" (OHLC = fechamento
  anterior, volume 0) e marca `filled=True` para o detector contar a duracao em candles de verdade.
- Paciente com o limite de ~30 req/min por IP (compartilhado): em 429 espera a pausa e tenta de novo.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from ..geckoterminal import parse_ohlcv
from ..http import ApiError, HttpClient, RateLimited

log = logging.getLogger("signals_mvp.pos_runner.candles")

# timeframe -> (endpoint, aggregate, segundos)
TIMEFRAMES: dict[str, tuple[str, int, int]] = {
    "5m": ("minute", 5, 300),
    "15m": ("minute", 15, 900),
    "1h": ("hour", 1, 3600),
    "4h": ("hour", 4, 14400),
}
PAGE_LIMIT = 1000
CACHE_VERSION = 2
EMPTY_RETRIES = 2            # pagina vazia: repete a mesma chamada ate isto antes de concluir "sem dados aqui"
EMPTY_STEP_S = 6 * 3600      # sem dados confirmado: anda para tras em passos curtos (nunca pula 13 dias de uma vez)


@dataclass(frozen=True)
class Bar:
    """Candle do detector. `ts` = INICIO do candle (UTC). `filled` = intervalo sem negociacao preenchido."""

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    filled: bool = False

    def end(self, step: int) -> int:
        return self.ts + step


def tf_seconds(tf: str) -> int:
    return TIMEFRAMES[tf][2]


def fill_gaps(bars: list[Bar], step: int, until_ts: Optional[int] = None) -> list[Bar]:
    """Completa intervalos sem negociacao com candles parados (volume 0). `until_ts`: estende ate ali (exclusivo)."""
    if not bars:
        return []
    out: list[Bar] = [bars[0]]
    for bar in bars[1:]:
        prev = out[-1]
        t = prev.ts + step
        while t < bar.ts:
            out.append(Bar(t, prev.close, prev.close, prev.close, prev.close, 0.0, True))
            t += step
        out.append(bar)
    if until_ts is not None:
        prev = out[-1]
        t = prev.ts + step
        while t + step <= until_ts:
            out.append(Bar(t, prev.close, prev.close, prev.close, prev.close, 0.0, True))
            t += step
    return out


def closed_only(bars: list[Bar], step: int, now_ts: float) -> list[Bar]:
    """So candles FECHADOS em `now_ts` (o candle em andamento nunca entra numa decisao)."""
    return [b for b in bars if b.ts + step <= now_ts]


class OhlcvStore:
    """Baixa e guarda o historico de candles de pools do GeckoTerminal."""

    def __init__(
        self,
        http: HttpClient,
        cache_dir: Path,
        network: str = "solana",
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 12,
    ):
        self.http = http
        self.http.headers.setdefault("Accept", "application/json;version=20230302")
        self.cache_dir = Path(cache_dir)
        self.network = network
        self.clock = clock
        self.sleep = sleep
        self.max_retries = max_retries
        self.calls = 0

    # -- cache ------------------------------------------------------------------
    def _path(self, pool: str, tf: str, currency: str, side: str) -> Path:
        return self.cache_dir / f"{pool}_{tf}_{currency}_{side}.json"

    @staticmethod
    def _empty_cache() -> dict[str, Any]:
        return {"v": CACHE_VERSION, "bars": {}, "covered_from": None, "covered_to": None}

    def _load(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return self._empty_cache()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("v") != CACHE_VERSION:
            return self._empty_cache()
        return data

    def _save(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)

    # -- rede -------------------------------------------------------------------
    def _page(self, pool: str, tf: str, before_ts: int, currency: str, side: str) -> list[Bar]:
        endpoint, aggregate, _ = TIMEFRAMES[tf]
        params = {"aggregate": aggregate, "limit": PAGE_LIMIT, "before_timestamp": int(before_ts), "currency": currency, "token": side}
        path = f"networks/{self.network}/pools/{pool}/ohlcv/{endpoint}"
        for attempt in range(self.max_retries):
            try:
                self.calls += 1
                data = self.http.get_json(path, params, max_wait_s=600.0)
                return [Bar(int(c.ts), c.open, c.high, c.low, c.close, c.volume) for c in parse_ohlcv(data)]
            except RateLimited as exc:
                wait = max(exc.wait_s, self.http.limiter.blocked_for(), 5.0)
                log.info("GT 429 em %s %s: aguardando %.0fs", pool[:8], tf, wait)
                self.sleep(wait)
            except ApiError as exc:
                if exc.kind in ("timeout", "network") or (exc.kind == "http" and (exc.status or 0) >= 500):
                    self.sleep(min(60.0, 5.0 * (attempt + 1)))
                    continue
                raise
        raise ApiError("budget", f"OHLCV {pool[:8]} {tf}: {self.max_retries} tentativas sem resposta")

    def _walk(
        self,
        pool: str,
        tf: str,
        cursor: int,
        stop_ts: int,
        bars: dict[str, list],
        currency: str,
        side: str,
        progress: Optional[Callable[[int], None]] = None,
    ) -> None:
        """Pagina de `cursor` (inclusivo) para tras ate passar de `stop_ts`, juntando em `bars`.

        `progress(cursor)` e chamado depois de cada pagina com dados (checkpoint para retomar).
        """
        step = tf_seconds(tf)
        empties = 0
        jump = max(step, EMPTY_STEP_S)
        while cursor >= stop_ts:
            page = [b for b in self._page(pool, tf, cursor, currency, side) if b.ts <= cursor]
            if page:
                for b in page:
                    bars[str(b.ts)] = [b.open, b.high, b.low, b.close, b.volume]
                cursor = page[0].ts - 1
                empties = 0
                jump = max(step, EMPTY_STEP_S)
                if progress is not None:
                    progress(cursor)
                continue
            empties += 1
            if empties <= EMPTY_RETRIES:
                # pagina vazia pode ser falha passageira (ou resposta vazia em cache): repete com outra URL
                cursor -= 1
                self.sleep(2.0 * empties)
                continue
            # vazio confirmado: anda para tras em passos que dobram (6h, 12h, 1d...), sem pular 13 dias de cara;
            # se mesmo assim pular dados por falha da API, `missing_windows` + `repair` acham e buscam de novo
            cursor -= jump
            jump = min(jump * 2, 12 * 86400)
            empties = 0

    def _run_walk(self, path: Path, data: dict[str, Any], pool: str, tf: str, cursor: int, stop: int, currency: str, side: str,
                  set_from: Optional[int], set_to: Optional[int]) -> None:
        """Executa uma caminhada com checkpoint em disco: se o processo cair, a proxima chamada retoma do cursor."""
        data["pending"] = {"cursor": cursor, "stop": stop, "set_from": set_from, "set_to": set_to}
        self._save(path, data)

        def progress(c: int) -> None:
            data["pending"]["cursor"] = c
            self._save(path, data)

        self._walk(pool, tf, cursor, stop, data["bars"], currency, side, progress)
        if set_from is not None:
            data["covered_from"] = set_from if data.get("covered_from") is None else min(int(data["covered_from"]), set_from)
        if set_to is not None:
            data["covered_to"] = set_to if data.get("covered_to") is None else max(int(data["covered_to"]), set_to)
        data.pop("pending", None)
        self._save(path, data)

    def history(
        self,
        pool: str,
        tf: str,
        start_ts: int,
        end_ts: Optional[int] = None,
        currency: str = "usd",
        side: str = "base",
    ) -> list[Bar]:
        """Candles com inicio em [start_ts - step, end_ts) em ordem crescente, SEM preencher lacunas.

        `start_ts` deve ser a criacao do pool (ou o comeco do periodo de interesse).
        """
        step = tf_seconds(tf)
        end = int(end_ts if end_ts is not None else self.clock())
        start = int(start_ts) - step
        path = self._path(pool, tf, currency, side)
        data = self._load(path)
        pending = data.get("pending")
        if pending:   # caminhada interrompida: termina antes de qualquer outra coisa
            self._run_walk(path, data, pool, tf, int(pending["cursor"]), int(pending["stop"]), currency, side,
                           pending.get("set_from"), pending.get("set_to"))
        cov_from, cov_to = data.get("covered_from"), data.get("covered_to")
        if cov_from is None or cov_to is None:
            self._run_walk(path, data, pool, tf, end, start, currency, side, start, end)
        else:
            if cov_to < end:
                # cauda nova (refaz o ultimo candle coberto, que podia estar em andamento)
                self._run_walk(path, data, pool, tf, end, int(cov_to) - step, currency, side, None, end)
            if cov_from > start:
                self._run_walk(path, data, pool, tf, int(cov_from) - 1, start, currency, side, start, None)
        bars: dict[str, list] = data["bars"]
        out = []
        for key in sorted(bars, key=int):
            ts = int(key)
            if start <= ts < end:
                o, h, l, c, v = bars[key]
                out.append(Bar(ts, o, h, l, c, v))
        return out

    def repair(self, pool: str, tf: str, windows: list[tuple[int, int]], currency: str = "usd", side: str = "base") -> int:
        """Busca de novo os trechos [ini, fim) onde faltam candles. Devolve quantos candles novos entraram."""
        path = self._path(pool, tf, currency, side)
        data = self._load(path)
        before = len(data["bars"])
        for lo, hi in windows:
            self._run_walk(path, data, pool, tf, hi - 1, lo, currency, side, None, None)
        return len(data["bars"]) - before


def missing_windows(fine: list[Bar], fine_tf: str, coarse: list[Bar], coarse_tf: str) -> list[tuple[int, int]]:
    """Intervalos do timeframe grosso com volume > 0 sem NENHUM candle do fino dentro (buraco de download)."""
    fstep, cstep = tf_seconds(fine_tf), tf_seconds(coarse_tf)
    have = {b.ts - (b.ts % cstep) for b in fine}
    holes = []
    for c in coarse:
        if c.volume > 0 and not c.filled and c.ts not in have:
            holes.append((c.ts, c.ts + cstep))
    # junta buracos encostados
    merged: list[tuple[int, int]] = []
    for lo, hi in holes:
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], hi)
        else:
            merged.append((lo, hi))
    _ = fstep
    return merged
