"""Cliente do GeckoTerminal (API publica v2) + parsers puros.

Os parsers foram escritos contra respostas REAIS capturadas em 2026-10-13
(ver tests/fixtures). Campo ausente/invalido vira None, nunca zero.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Iterable, Optional

from .http import ApiError, HttpClient
from .models import (
    WINDOWS,
    Candle,
    ChainCtx,
    PoolSnap,
    TokenInfo,
    TradesSummary,
    WindowTx,
    norm_addr,
)
from .util import clean_text, parse_iso, to_float, to_int, utc_now

log = logging.getLogger("signals_mvp.gt")

ACCEPT = "application/json;version=20230302"
INCLUDE = "base_token,quote_token,dex"
MULTI_MAX = 30
PATIENT_WAIT_S = 30.0  # chamadas de alto valor (enriquecer candidato, fechar acompanhamento) esperam o limitador ate isto


# ---------------------------------------------------------------------------
# parsers de pool
# ---------------------------------------------------------------------------


def _token_from(included: dict, token_id: str, platform: str) -> tuple[str, str, str]:
    """(endereco normalizado, simbolo, nome) de um token do bloco `included`."""
    attrs = (included.get(token_id) or {}).get("attributes") or {}
    address = attrs.get("address") or (token_id.split("_", 1)[1] if "_" in token_id else token_id)
    return norm_addr(platform, address), clean_text(attrs.get("symbol"), 40), clean_text(attrs.get("name"), 80)


def _window_tx(raw: Any, swap: bool) -> WindowTx:
    if not isinstance(raw, dict):
        return WindowTx()
    buys, sells = to_int(raw.get("buys")), to_int(raw.get("sells"))
    buyers, sellers = to_int(raw.get("buyers")), to_int(raw.get("sellers"))
    if swap:  # alvo e o token "quote": compra do alvo = venda do base
        return WindowTx(buys=sells, sells=buys, buyers=sellers, sellers=buyers)
    return WindowTx(buys=buys, sells=sells, buyers=buyers, sellers=sellers)


def parse_pool(item: dict, included: dict, ctx: ChainCtx, observed_ts: float) -> Optional[PoolSnap]:
    attrs = item.get("attributes") or {}
    rel = item.get("relationships") or {}
    pool = attrs.get("address") or (item.get("id", "").split("_", 1)[1] if "_" in item.get("id", "") else "")
    if not pool:
        return None
    pool = norm_addr(ctx.platform, pool)
    base_id = ((rel.get("base_token") or {}).get("data") or {}).get("id")
    quote_id = ((rel.get("quote_token") or {}).get("data") or {}).get("id")
    dex = ((rel.get("dex") or {}).get("data") or {}).get("id") or ""
    if not base_id or not quote_id:
        return None
    base_addr, base_sym, base_name = _token_from(included, base_id, ctx.platform)
    quote_addr, quote_sym, quote_name = _token_from(included, quote_id, ctx.platform)
    base_ref = base_addr in ctx.reference
    quote_ref = quote_addr in ctx.reference
    both_ref = base_ref and quote_ref
    # papel normalizado: o alvo e o lado que NAO e ativo de referencia (padrao: base)
    target_is_quote = base_ref and not quote_ref
    if target_is_quote:
        token, symbol, token_name = quote_addr, quote_sym, quote_name
        other, other_sym, other_ref = base_addr, base_sym, base_ref
        price = to_float(attrs.get("quote_token_price_usd"))
    else:
        token, symbol, token_name = base_addr, base_sym, base_name
        other, other_sym, other_ref = quote_addr, quote_sym, quote_ref
        price = to_float(attrs.get("base_token_price_usd"))

    liq = to_float(attrs.get("reserve_in_usd"))
    unreliable = bool(dex in ctx.liq_unreliable_dex and (liq is None or liq <= 0))
    if unreliable:
        liq = None

    tx_raw = attrs.get("transactions") or {}
    vol_raw = attrs.get("volume_usd") or {}
    chg_raw = attrs.get("price_change_percentage") or {}
    launchpad = attrs.get("launchpad_details")
    return PoolSnap(
        chain=ctx.name,
        pool=pool,
        dex=dex,
        name=clean_text(attrs.get("name"), 80),
        created_ts=parse_iso(attrs.get("pool_created_at")),
        observed_ts=observed_ts,
        token=token,
        symbol=symbol,
        token_name=token_name,
        target_side="quote" if target_is_quote else "base",
        other_token=other,
        other_symbol=other_sym,
        other_is_reference=other_ref,
        both_reference=both_ref,
        price_usd=price,
        fdv_usd=to_float(attrs.get("fdv_usd")),
        mcap_usd=to_float(attrs.get("market_cap_usd")),
        liq_usd=liq,
        liq_unreliable=unreliable,
        vol={w: to_float(vol_raw.get(w)) for w in WINDOWS},
        tx={w: _window_tx(tx_raw.get(w), target_is_quote) for w in WINDOWS},
        price_change={w: to_float(chg_raw.get(w)) for w in WINDOWS},
        locked_liq_pct=to_float(attrs.get("locked_liquidity_percentage")),
        launchpad=launchpad if isinstance(launchpad, dict) else None,
        fee_pct=to_float(attrs.get("pool_fee_percentage")),
    )


def parse_pools_response(data: Any, ctx: ChainCtx, observed_ts: float) -> list[PoolSnap]:
    if not isinstance(data, dict):
        raise ApiError("bad_json", "resposta de pools nao e um objeto")
    items = data.get("data")
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise ApiError("bad_json", "resposta de pools sem `data`")
    included = {i.get("id"): i for i in data.get("included", []) if isinstance(i, dict)}
    pools: list[PoolSnap] = []
    for item in items:
        try:
            snap = parse_pool(item, included, ctx, observed_ts)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            log.debug("pool ignorado (parse): %s", exc)
            continue
        if snap is not None:
            pools.append(snap)
    return pools


# ---------------------------------------------------------------------------
# parsers de OHLCV, token info, trades, redes
# ---------------------------------------------------------------------------


def parse_ohlcv(data: Any) -> list[Candle]:
    """`ohlcv_list` vem do mais novo para o mais antigo: devolvemos em ordem CRESCENTE de tempo."""
    try:
        raw = data["data"]["attributes"]["ohlcv_list"]
    except (KeyError, TypeError):
        raise ApiError("bad_json", "OHLCV sem ohlcv_list") from None
    candles: dict[float, Candle] = {}
    for row in raw or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        values = [to_float(x) for x in row[:6]]
        if any(v is None for v in values):
            continue
        ts, o, h, l, c, v = values  # type: ignore[misc]
        if min(o, h, l, c) <= 0 or h < l:
            continue
        candles[ts] = Candle(ts=ts, open=o, high=h, low=l, close=c, volume=v)
    return [candles[k] for k in sorted(candles)]


def parse_token_info(data: Any, address: str = "") -> TokenInfo:
    try:
        attrs = data["data"]["attributes"]
    except (KeyError, TypeError):
        raise ApiError("bad_json", "token info sem attributes") from None
    holders = attrs.get("holders") if isinstance(attrs.get("holders"), dict) else {}
    dist = holders.get("distribution_percentage") if isinstance(holders.get("distribution_percentage"), dict) else {}
    websites = attrs.get("websites") if isinstance(attrs.get("websites"), list) else []

    def auth(value: Any) -> Optional[str]:
        return value.strip().lower() if isinstance(value, str) and value.strip() else None

    return TokenInfo(
        address=attrs.get("address") or address,
        name=clean_text(attrs.get("name"), 80),
        symbol=clean_text(attrs.get("symbol"), 40),
        description=clean_text(attrs.get("description"), 1200),
        mint_authority=auth(attrs.get("mint_authority")),
        freeze_authority=auth(attrs.get("freeze_authority")),
        is_honeypot=auth(attrs.get("is_honeypot")),
        holders_count=to_int(holders.get("count")),
        top10_pct_gt=to_float(dist.get("top_10")),
        dev_holding_pct=to_float(attrs.get("developer_holding_percentage")),
        websites=[clean_text(w, 200) for w in websites if isinstance(w, str)][:5],
        twitter=clean_text(attrs.get("twitter_handle"), 60),
        telegram=clean_text(attrs.get("telegram_handle"), 60),
        gt_score=to_float(attrs.get("gt_score")),
    )


def summarize_trades(data: Any, target_token: str, platform: str, now_ts: float, window_s: float = 300.0) -> TradesSummary:
    """Valor (USD) de compras/vendas do token ALVO nas ultimas `window_s` segundos.

    A trade e "compra" quando o alvo e o token recebido (`to_token_address`) e "venda" quando
    e o token entregue (`from_token_address`) — independe de o alvo ser base ou quote do pool.
    O endpoint devolve no maximo ~300 trades; em pool muito ativo isso encurta a janela e
    `complete` fica False (o valor passa a ser uma amostra dos ultimos instantes).
    """
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ApiError("bad_json", "trades sem `data`")
    target = norm_addr(platform, target_token)
    rows: list[tuple[float, str, float, str]] = []
    for item in items:
        a = (item or {}).get("attributes") or {}
        ts = parse_iso(a.get("block_timestamp"))
        usd = to_float(a.get("volume_in_usd"))
        if ts is None or usd is None or usd < 0:
            continue
        if norm_addr(platform, a.get("to_token_address")) == target:
            kind = "buy"
        elif norm_addr(platform, a.get("from_token_address")) == target:
            kind = "sell"
        else:
            continue
        rows.append((ts, kind, usd, str(a.get("tx_from_address") or "")))
    start = now_ts - window_s
    inside = [r for r in rows if start <= r[0] <= now_ts]
    oldest = min((r[0] for r in rows), default=None)
    # janela completa se ha trade mais antiga que o inicio da janela OU a lista nao bateu no teto de ~300
    complete = (oldest is not None and oldest <= start) or len(items) < 300
    covered = window_s if complete else max(0.0, now_ts - (oldest if oldest is not None else now_ts))
    buy = sum(r[2] for r in inside if r[1] == "buy")
    sell = sum(r[2] for r in inside if r[1] == "sell")
    return TradesSummary(
        window_s=window_s,
        n_trades=len(inside),
        buy_usd=buy,
        sell_usd=sell,
        unique_buy_wallets=len({r[3] for r in inside if r[1] == "buy" and r[3]}),
        unique_sell_wallets=len({r[3] for r in inside if r[1] == "sell" and r[3]}),
        complete=complete,
        covered_s=covered,
    )


def parse_network_ids(data: Any) -> set[str]:
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ApiError("bad_json", "lista de redes sem `data`")
    return {str(i.get("id")) for i in items if isinstance(i, dict) and i.get("id")}


# ---------------------------------------------------------------------------
# cliente
# ---------------------------------------------------------------------------


class GtClient:
    """Chamadas ao GeckoTerminal. Levanta ApiError; quem chama decide o que fazer."""

    def __init__(self, http: HttpClient, clock: Callable[[], float] = utc_now, wait_s: float = 5.0):
        self.http = http
        self.clock = clock
        self.wait_s = wait_s   # quanto uma chamada comum espera por uma ficha do limitador (as de alto valor esperam mais)
        self.http.headers.setdefault("Accept", ACCEPT)

    def new_pools(self, ctx: ChainCtx, page: int) -> list[PoolSnap]:
        """`observed_ts` das fotos = relogio no instante em que a resposta chegou."""
        data = self.http.get_json(f"networks/{ctx.gt_network}/new_pools", {"page": page, "include": INCLUDE}, max_wait_s=self.wait_s)
        return parse_pools_response(data, ctx, self.clock())

    def pools_multi(self, ctx: ChainCtx, pools: Iterable[str]) -> list[PoolSnap]:
        batch = list(pools)[:MULTI_MAX]
        if not batch:
            return []
        data = self.http.get_json(f"networks/{ctx.gt_network}/pools/multi/{','.join(batch)}", {"include": INCLUDE}, max_wait_s=self.wait_s)
        return parse_pools_response(data, ctx, self.clock())

    def ohlcv(self, ctx: ChainCtx, pool: str, target_side: str, start_ts: float, end_ts: float) -> list[Candle]:
        """Candles de 1 min em [start_ts, end_ts], em ordem crescente (inclui o candle em andamento)."""
        limit = int(math.ceil((end_ts - start_ts) / 60.0)) + 3
        params = {
            "aggregate": 1,
            "limit": max(5, min(1000, limit)),
            "before_timestamp": int(end_ts) + 60,
            "currency": "usd",
            "token": "quote" if target_side == "quote" else "base",
        }
        data = self.http.get_json(f"networks/{ctx.gt_network}/pools/{pool}/ohlcv/minute", params, max_wait_s=PATIENT_WAIT_S)
        candles = parse_ohlcv(data)
        return [c for c in candles if start_ts - 60 <= c.ts <= end_ts]

    def token_info(self, ctx: ChainCtx, token: str) -> TokenInfo:
        data = self.http.get_json(f"networks/{ctx.gt_network}/tokens/{token}/info", max_wait_s=PATIENT_WAIT_S)
        return parse_token_info(data, token)

    def trades(self, ctx: ChainCtx, pool: str, target_token: str, now_ts: float, window_s: float = 300.0) -> TradesSummary:
        data = self.http.get_json(f"networks/{ctx.gt_network}/pools/{pool}/trades", max_wait_s=PATIENT_WAIT_S)
        return summarize_trades(data, target_token, ctx.platform, now_ts, window_s)

    def network_ids(self, max_pages: int = 4) -> set[str]:
        """Todos os ids de rede do GeckoTerminal (as paginas acabam com HTTP 400)."""
        ids: set[str] = set()
        for page in range(1, max_pages + 1):
            try:
                ids |= parse_network_ids(self.http.get_json("networks", {"page": page}))
            except ApiError as exc:
                if exc.kind == "http" and exc.status == 400 and page > 1:
                    break  # passou da ultima pagina
                raise
        return ids
