"""Dubles de teste: relogio, sessao HTTP, GeckoTerminal/GoPlus/Telegram falsos e um 'mundo' de pools simulado."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..http import ApiError, RateLimited
from ..models import Candle, ChainCtx, PoolSnap, TokenInfo, TradesSummary, WindowTx
from ..telegram import TelegramError

FIXTURES = Path(__file__).resolve().parent / "fixtures"
T0 = 1_791_900_000.0  # 2026-10-13T14:00:00Z (inicio do mundo simulado)
SOL_TOKEN = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"  # formato de endereco Solana valido
EVM_TOKEN = "0x" + "ab" * 20


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeClock:
    def __init__(self, start: float = T0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# ---------------------------------------------------------------------------
# HTTP falso (exercita HttpClient/GtClient/GoPlusClient de verdade)
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int = 200, payload: Any = None, raw: Optional[str] = None, headers: Optional[dict] = None):
        self.status_code = status
        self._payload = payload
        self._raw = raw
        self.headers = headers or {}

    def json(self) -> Any:
        if self._raw is not None:
            raise ValueError("nao e json")
        return self._payload


class FakeSession:
    """routes: lista de (substring_da_url, resposta|excecao|callable(url, params)->resposta)."""

    def __init__(self, routes: list[tuple[str, Any]]):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None, timeout: Any = None) -> FakeResponse:
        self.calls.append((url, dict(params or {})))
        for needle, answer in self.routes:
            if needle in url:
                if callable(answer):
                    answer = answer(url, params or {})
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return FakeResponse(404, {})


# ---------------------------------------------------------------------------
# mundo simulado
# ---------------------------------------------------------------------------


@dataclass
class SimPool:
    chain: str
    pool: str
    token: str
    symbol: str
    created_ts: float
    dex: str = "pump-fun"
    name: str = ""
    price0: float = 1e-5
    supply: float = 1e9
    liq: Callable[[float], Optional[float]] = lambda age: 20000.0
    vol_m5: Callable[[float], float] = lambda age: 4000.0
    buys: Callable[[float], int] = lambda age: 30
    sells: Callable[[float], int] = lambda age: 12
    buyers: Callable[[float], int] = lambda age: 25
    price: Callable[[float], float] = lambda age: 1.0  # multiplo de price0 em funcao da idade (s)
    target_side: str = "base"
    token_name: str = ""
    other_is_reference: bool = True
    both_reference: bool = False

    def snapshot(self, now: float) -> PoolSnap:
        age = now - self.created_ts
        px = self.price0 * self.price(age)
        m5 = WindowTx(self.buys(age), self.sells(age), self.buyers(age), max(1, self.buyers(age) // 2))
        vol5 = self.vol_m5(age)
        vol_h1 = vol5 * min(12.0, max(1.0, age / 300.0))
        liq = self.liq(age)
        unreliable = self.dex == "meteora-dbc" and not liq  # o parser real faz o mesmo (DEX de curva reporta 0)
        if unreliable:
            liq = None
        return PoolSnap(
            chain=self.chain, pool=self.pool, dex=self.dex, name=self.name or f"{self.symbol} / SOL",
            created_ts=self.created_ts, observed_ts=now, token=self.token, symbol=self.symbol,
            token_name=self.token_name or self.symbol, target_side=self.target_side, other_token="ref", other_symbol="SOL",
            other_is_reference=self.other_is_reference, both_reference=self.both_reference, price_usd=px, fdv_usd=px * self.supply,
            mcap_usd=None, liq_usd=liq, liq_unreliable=unreliable, vol={"m5": vol5, "h1": vol_h1, "m15": vol5, "m30": vol5, "h6": vol_h1, "h24": vol_h1},
            tx={"m5": m5, "h1": m5, "m15": m5, "m30": m5, "h6": m5, "h24": m5}, price_change={"m5": 0.0},
        )

    def candles(self, start_ts: float, end_ts: float) -> list[Candle]:
        out: list[Candle] = []
        ts = math.floor(max(start_ts, self.created_ts) / 60.0) * 60.0
        while ts <= end_ts:
            samples = [self.price0 * self.price(ts + k * 10.0 - self.created_ts) for k in range(7)]
            out.append(Candle(ts=ts, open=samples[0], high=max(samples), low=min(samples), close=samples[-1], volume=1000.0))
            ts += 60.0
        return out


class FakeGt:
    """Mesmo contrato do GtClient, alimentado por SimPools."""

    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.sims: dict[tuple[str, str], SimPool] = {}
        self.calls: Counter = Counter()
        self.log: list[str] = []          # ordem das chamadas (testa prioridades)
        self.fail: dict[str, Exception] = {}
        self.infos: dict[str, TokenInfo] = {}
        self.trades_by_pool: dict[str, TradesSummary] = {}
        self.new_page_size = 20

    def add(self, sim: SimPool) -> SimPool:
        self.sims[(sim.chain, sim.pool)] = sim
        return sim

    def _maybe_fail(self, method: str) -> None:
        self.log.append(method)
        if method in self.fail:
            raise self.fail[method]

    def new_pools(self, ctx: ChainCtx, page: int) -> list[PoolSnap]:
        self.calls["new_pools"] += 1
        self._maybe_fail("new_pools")
        now = self.clock()
        sims = [s for (c, _), s in self.sims.items() if c == ctx.name and s.created_ts <= now]
        sims.sort(key=lambda s: -s.created_ts)
        start = (page - 1) * self.new_page_size
        return [s.snapshot(now) for s in sims[start : start + self.new_page_size]]

    def pools_multi(self, ctx: ChainCtx, pools: Any) -> list[PoolSnap]:
        self.calls["pools_multi"] += 1
        self._maybe_fail("pools_multi")
        now = self.clock()
        return [self.sims[(ctx.name, p)].snapshot(now) for p in pools if (ctx.name, p) in self.sims]

    def ohlcv(self, ctx: ChainCtx, pool: str, side: str, start_ts: float, end_ts: float) -> list[Candle]:
        self.calls["ohlcv"] += 1
        self._maybe_fail("ohlcv")
        sim = self.sims[(ctx.name, pool)]
        return sim.candles(start_ts, min(end_ts, self.clock()))

    def token_info(self, ctx: ChainCtx, token: str) -> TokenInfo:
        self.calls["token_info"] += 1
        self._maybe_fail("token_info")
        return self.infos.get(token, TokenInfo(address=token, mint_authority="no", freeze_authority="no"))

    def trades(self, ctx: ChainCtx, pool: str, target_token: str, now_ts: float, window_s: float = 300.0) -> TradesSummary:
        self.calls["trades"] += 1
        self._maybe_fail("trades")
        return self.trades_by_pool.get(pool) or TradesSummary(window_s, 40, 3000.0, 1200.0, 20, 9, True, window_s)

    def network_ids(self, max_pages: int = 4) -> set[str]:
        return {"solana", "bsc", "robinhood"}


class FakeGoPlus:
    """security(platform, chain_id, tokens) -> (resultados, erro). `records[token]` = registro cru ou None."""

    def __init__(self) -> None:
        self.records: dict[str, Optional[dict]] = {}
        self.error: Optional[ApiError] = None
        self.calls: list[tuple[str, str, list[str]]] = []

    def security(self, platform: str, chain_id: str, tokens: Any) -> tuple[dict, Optional[ApiError]]:
        tokens = list(tokens)
        self.calls.append((platform, chain_id, tokens))
        if self.error is not None:
            return {}, self.error
        return {t: self.records.get(t) for t in tokens}, None


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Optional[dict]]] = []
        self.notified: list[str] = []
        self.answers: list[tuple[str, str]] = []
        self.edits: list[tuple[int, dict]] = []
        self.fail_next = 0
        self._next_id = 100
        self.chat_id = "42"

    def send_message(self, text: str, reply_markup: Optional[dict] = None) -> int:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise TelegramError("falha simulada")
        self._next_id += 1
        self.sent.append((text, reply_markup))
        return self._next_id

    def notify(self, text: str) -> None:
        self.notified.append(text)

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self.answers.append((callback_id, text))

    def edit_reply_markup(self, message_id: int, reply_markup: dict) -> None:
        self.edits.append((message_id, reply_markup))


def evm_ok_record(**overrides: Any) -> dict:
    """Registro GoPlus EVM 'completo e saudavel' (para testar caminhos felizes)."""
    record = {
        "is_honeypot": "0", "buy_tax": "0.01", "sell_tax": "0.01", "is_open_source": "1", "owner_address": "0x" + "0" * 40,
        "holder_count": "250", "cannot_buy": "0", "cannot_sell_all": "0", "hidden_owner": "0", "is_mintable": "0",
        "holders": [{"address": f"0x{i:040x}", "tag": "", "percent": "0.02", "is_contract": 0, "is_locked": 0} for i in range(1, 11)],
        "lp_holders": [{"address": "0x" + "0" * 40, "tag": "Null Address", "percent": "0.95", "is_locked": 1}],
        "dex": [{"name": "PancakeV2", "pair": "0xpair"}],
    }
    record.update(overrides)
    return record


def solana_ok_record(**overrides: Any) -> dict:
    record = {
        "mintable": {"status": "0", "authority": []}, "freezable": {"status": "0", "authority": []},
        "closable": {"status": "0", "authority": []}, "balance_mutable_authority": {"status": "0", "authority": []},
        "non_transferable": "0", "transfer_fee": {}, "transfer_hook": [], "default_account_state": "1",
        "metadata": {"name": "X", "symbol": "X", "description": ""},
    }
    record.update(overrides)
    return record
