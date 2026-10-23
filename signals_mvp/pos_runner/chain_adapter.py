"""ChainAdapter (PROMPT DEFINITIVO V1, item 3.1): interface comum de descoberta de graduacoes/pools novos,
OHLCV, metadados, holders e links, para a V1 rotear entre chains sem acoplar o bot a detalhes de uma rede so.

`SolanaAdapter` NAO duplica nada do V0: reaproveita literalmente `SOURCES`/`GRAD_DEX`/`LAUNCHPAD_NAME`
(descoberta, ja usados por `live.py`), `verify_lineage`/`LineageVerifier` (linhagem on-chain), `OhlcvStore`
(candles) e `enumerate.LAUNCHPADS` (programas de migracao/AMM de destino, para excluir vaults operacionais do
calculo de holders). `BscAdapter`/`RobinhoodAdapter` sao FASE 2 (prompt, secao 5): aqui so a DETECCAO DE
CAPACIDADE (item 3.1 -- "descobrir os network ids em /networks na inicializacao"; sem a rede listada ou sem
OHLCV o adapter se desabilita com log e aviso, nunca derruba o bot) ja fica pronta, mas `capable()` sempre
devolve False ate a Fase 2 implementar descoberta/candles/holders proprios -- nao e stub silencioso, e
deteccao de capacidade real sobre a rede de verdade.
"""

from __future__ import annotations

import abc
import html
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..geckoterminal import parse_pools_response
from ..http import ApiError, RateLimited
from ..models import ChainCtx, PoolSnap
from .candles import Bar, OhlcvStore
from .enumerate import LAUNCHPADS
from .solana_rpc import RpcError, SolanaRpc

# `GRAD_DEX`/`LAUNCHPAD_NAME`/`SOURCES` vivem em `live.py` (o V0 ja os usa); importados aqui dentro dos
# metodos que precisam deles (nunca no topo do modulo) para nao formar um import circular -- `live.py`
# importa este modulo (`SolanaAdapter`), entao este modulo nunca pode importar `live` no nivel do modulo.

log = logging.getLogger("signals_mvp.pos_runner.chain_adapter")

# contas sempre excluidas do calculo de HOLDER_CONCENTRADO (item 2.7 + INTERPRETACOES.md #5): conta de queima
# padrao Solana/pump.fun e os programas base (nunca um holder humano, sempre custodia operacional).
BURN_ADDRESSES = frozenset({"1nc1nerator11111111111111111111111111111"})
BASE_EXCLUDED_PROGRAMS = frozenset({
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",      # Token Program
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",      # Associated Token Program
    "11111111111111111111111111111111111111111",         # System Program
})
HOLDER_CONCENTRADO_PCT = 1.5


@dataclass
class DiscoveredPool:
    """O que `ChainAdapter.discover` devolve: snaps brutos da fonte (o chamador decide o que entra na fila,
    exatamente como `PosRunnerLive.offer` ja faz para o V0 -- o adapter nunca decide sozinho quem entra)."""

    source: str
    snaps: list[PoolSnap]


@dataclass
class HolderCheck:
    tag: Optional[str] = None            # "HOLDER_CONCENTRADO" | "holders_indisponivel" | None
    top_holder_pct: Optional[float] = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class VampCheck:
    tag: Optional[str] = None            # "VAMP_RISK" | None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthorityCheck:
    """Item 2 da FASE 2 de medicao/UX: mint_authority/freeze_authority revogados ou ainda ativos
    (instrumentacao -- nunca filtra nem descarta sinal). 'indisponivel' explicito em qualquer falha,
    NUNCA promovido a 'revogada'/'ativa' no chute."""

    mint_authority: str = "indisponivel"    # "revogada" | "ativa" | "indisponivel"
    freeze_authority: str = "indisponivel"


@dataclass
class Capability:
    """Resultado da deteccao de capacidade (item 3.1): rede listada no GT E com OHLCV. `motivo` vai pro log/aviso
    do Telegram quando `ok` e False -- nunca uma falha silenciosa."""

    network_id: Optional[str]
    has_ohlcv: bool
    motivo: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.network_id) and self.has_ohlcv


class ChainAdapter(abc.ABC):
    """Interface comum. Links por chain (item 4): `terminal_label`/`terminal_url_template` e
    `dexscreener_url_template` vem do config.yaml (`links.*`), iguais ao que o v0 ja usa em `alerts.build_links`."""

    name: str

    @abc.abstractmethod
    def capable(self) -> bool:
        """False = adapter desabilitado (rede nao listada no GT ou sem OHLCV): nunca derruba o bot."""

    @abc.abstractmethod
    def discover(self, source: str, now: float) -> DiscoveredPool:
        """Uma fonte de descoberta (rotacionada pelo chamador, como `PosRunnerLive._discover` ja faz)."""

    @abc.abstractmethod
    def ohlcv(self, pool: str, tf: str, start_ts: int, end_ts: int, currency: str = "usd", side: str = "base") -> list[Bar]:
        ...

    @abc.abstractmethod
    def link_for(self, kind: str, mint: str, pool: str, gmgn_slug: str, dexscreener_slug: str) -> str:
        """kind: 'terminal' (Axiom/GMGN na Solana, GMGN em BSC/Robinhood -- item 4) ou 'dexscreener'."""

    def holders(self, mint: str, exclude_accounts: frozenset[str] = frozenset()) -> HolderCheck:
        """Melhor esforco (item 2.7): sem dado = `holders_indisponivel`, nunca um 'nao' adivinhado."""
        return HolderCheck(tag="holders_indisponivel", detail={"motivo": f"{self.name}: sem suporte a holders ainda"})

    def authorities(self, mint: str) -> AuthorityCheck:
        """Item 2 da FASE 2 de medicao/UX: melhor esforco, 'indisponivel' explicito sem dado."""
        return AuthorityCheck()

    def vamp_risk(self, symbol: str, mc_usd: Optional[float], search: Callable[[str], list[dict]]) -> VampCheck:
        """Item 2.7 + INTERPRETACOES.md #4: outro token com o MESMO ticker (case-insensitive, igualdade exata),
        mais antigo e com MC atual/de pico maior. `search` busca por ticker (GT `/search/pools`, ja cacheavel
        pelo chamador) e devolve [{symbol, created_ts, mc_usd}, ...]; erro de rede -> tag ausente (nunca "nao")."""
        try:
            candidates = search(symbol)
        except (ApiError, RateLimited, RpcError):
            return VampCheck()
        others = [c for c in candidates if str(c.get("symbol", "")).lower() == symbol.lower()
                  and c.get("mc_usd") is not None and c.get("created_ts") is not None]
        if mc_usd is None or not others:
            return VampCheck()
        older_and_bigger = [c for c in others if c["mc_usd"] > mc_usd]
        if older_and_bigger:
            return VampCheck(tag="VAMP_RISK", detail={"candidatos": older_and_bigger[:3]})
        return VampCheck()


class SolanaAdapter(ChainAdapter):
    name = "solana"

    def __init__(self, http: Any, ctx: ChainCtx, ohlcv_store: OhlcvStore, rpc: Optional[SolanaRpc],
                 links: dict[str, str], terminal: str = "axiom"):
        self.http = http
        self.ctx = ctx
        self.ohlcv_store = ohlcv_store
        self.rpc = rpc
        self.links = links
        self.terminal = terminal
        # item 2 da FASE 2 de medicao/UX: 1 chamada RPC por mint, cacheada em memoria pela vida do
        # processo -- nunca repete a chamada so porque o mesmo token apareceu de novo (outro tf, etc.).
        self._authority_cache: dict[str, AuthorityCheck] = {}

    def capable(self) -> bool:
        return True   # Solana e a rede completa da V1 (item 5, FASE 1)

    def discover(self, source: str, now: float) -> DiscoveredPool:
        from .live import GRAD_DEX, SOURCES   # import tardio: ver nota de import circular no topo do arquivo
        path, query = SOURCES[source]
        data = self.http.get_json(path, query, max_wait_s=15.0)
        snaps = [s for s in parse_pools_response(data, self.ctx, now) if s.dex in GRAD_DEX]
        return DiscoveredPool(source, snaps)

    def ohlcv(self, pool: str, tf: str, start_ts: int, end_ts: int, currency: str = "usd", side: str = "base") -> list[Bar]:
        return self.ohlcv_store.history(pool, tf, start_ts, end_ts, currency=currency, side=side)

    def link_for(self, kind: str, mint: str, pool: str, gmgn_slug: str, dexscreener_slug: str) -> str:
        fields = {"pool": pool, "token": mint, "gmgn_slug": gmgn_slug, "dexscreener_slug": dexscreener_slug}
        key = self.terminal if kind == "terminal" else "dexscreener"
        url = self.links[key].format(**fields)
        assert url.startswith("https://"), f"link_for({kind}) nao produziu uma URL https:// valida: {url!r}"
        return url

    def launchpad_name(self, dex: str) -> str:
        from .live import GRAD_DEX, LAUNCHPAD_NAME   # import tardio: ver nota de import circular no topo do arquivo
        key = GRAD_DEX.get(dex, dex)
        return LAUNCHPAD_NAME.get(key, key)

    # -- holders (item 2.7 + INTERPRETACOES.md #5) ---------------------------------------------------
    def excluded_accounts(self, pool: str, mint: str, launchpad: Optional[str]) -> frozenset[str]:
        """Vaults/programas a excluir do calculo de HOLDER_CONCENTRADO deste pool especifico (quem chama
        passa isto como `exclude_accounts` de `holders()`; a queima e os programas base ja entram sempre,
        dentro de `holders()`)."""
        excluded = set(BASE_EXCLUDED_PROGRAMS) | set(BURN_ADDRESSES)
        spec = LAUNCHPADS.get(launchpad or "")
        if spec is not None:
            excluded.add(spec.program)
            if spec.pool_after_program:
                excluded.add(spec.pool_after_program)
        return frozenset(excluded)

    def holders(self, mint: str, exclude_accounts: frozenset[str] = frozenset()) -> HolderCheck:
        if self.rpc is None:
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": "sem RPC configurado"})
        try:
            largest = self.rpc.call("getTokenLargestAccounts", [mint]) or {}
            supply = self.rpc.token_supply(mint)
        except RpcError as exc:
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": f"RPC: {exc}"})
        # exclusoes do item 2.7/INTERPRETACOES.md #5: queima + programas base SEMPRE, mais o que o chamador
        # passou (vaults do pool/bonding curve especificos deste token, via `_excluded_accounts`)
        exclude_accounts = frozenset(exclude_accounts) | BASE_EXCLUDED_PROGRAMS | BURN_ADDRESSES
        accounts = (largest.get("value") or [])
        if not supply:
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": "supply indisponivel"})
        resolved = 0
        top_pct = 0.0
        for row in accounts:
            address = row.get("address")
            amount = row.get("uiAmount") or row.get("uiAmountString")
            if address is None or amount is None or address in exclude_accounts:
                continue
            try:
                info = self.rpc.call("getAccountInfo", [address, {"encoding": "jsonParsed"}])
                owner = ((info or {}).get("value") or {}).get("owner")
            except RpcError:
                continue   # conta que nao resolve: fora da comparacao, nao derruba o resto
            resolved += 1
            if owner is not None and (owner in exclude_accounts):
                continue
            pct = 100.0 * float(amount) / float(supply)
            top_pct = max(top_pct, pct)
        if resolved == 0 and accounts:
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": "nenhuma conta resolveu o owner"})
        if top_pct >= HOLDER_CONCENTRADO_PCT:
            return HolderCheck(tag="HOLDER_CONCENTRADO", top_holder_pct=top_pct)
        return HolderCheck(top_holder_pct=top_pct)

    # -- mint/freeze authority (item 2 da FASE 2 de medicao/UX) ---------------------------------------
    def authorities(self, mint: str) -> AuthorityCheck:
        """UMA chamada RPC por mint (getAccountInfo, jsonParsed), cacheada -- nunca filtra nem
        descarta sinal, so preenche dado (CSV/SQLite/texto do alerta). Falha ou formato inesperado
        vira 'indisponivel' explicito, nunca 'revogada'/'ativa' adivinhado."""
        cached = self._authority_cache.get(mint)
        if cached is not None:
            return cached
        result = AuthorityCheck()
        if self.rpc is not None:
            try:
                info = self.rpc.call("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
                parsed = (((info or {}).get("value") or {}).get("data") or {}).get("parsed") or {}
                fields = parsed.get("info") or {}
                if "mintAuthority" in fields and "freezeAuthority" in fields:
                    result = AuthorityCheck(
                        mint_authority="revogada" if fields.get("mintAuthority") is None else "ativa",
                        freeze_authority="revogada" if fields.get("freezeAuthority") is None else "ativa",
                    )
            except RpcError:
                pass   # fica 'indisponivel' (valor padrao de AuthorityCheck) -- nunca cai o resto do sinal
        self._authority_cache[mint] = result
        return result


# ---------------------------------------------------------------------------
# BSC / Robinhood -- FASE 2 (prompt, secao 5): so deteccao de capacidade (item 3.1) por agora.
# ---------------------------------------------------------------------------


def detect_capability(http: Any, network_name_candidates: tuple[str, ...]) -> Capability:
    """Consulta `/networks` do GeckoTerminal e procura um id que combine com `network_name_candidates`, depois
    confirma OHLCV de verdade com um pool de amostra real (`/trending_pools` + 1 chamada de `/ohlcv`) -- nunca
    assume. Ate 3 chamadas, 1x no startup (nao por ciclo).

    Medido em 2026-10-22 (pesquisa da revisao da FASE 1 da V1): os ids `bsc` e `robinhood` SAO reais no GT
    (confirmados direto na API publica); `bsc` tambem teve OHLCV real confirmado (pool TartSwap/WBNB,
    `pancakeswap_v2`). Mesmo assim esta funcao refaz a verificacao em tempo real a cada chamada -- a API pode
    mudar, e o resultado nunca deve vir de um valor memorizado."""
    try:
        data = http.get_json("networks", {"page": 1}, max_wait_s=15.0)
    except (ApiError, RateLimited) as exc:
        return Capability(None, False, f"falha ao listar /networks: {exc}")
    ids = {row.get("id") for row in (data or {}).get("data", []) if isinstance(row, dict)}
    match = next((c for c in network_name_candidates if c in ids), None)
    if match is None:
        return Capability(None, False, f"nenhum dos ids candidatos {network_name_candidates} existe no GT ({sorted(ids)[:20]}...)")
    try:
        trending = http.get_json(f"networks/{match}/trending_pools", {"page": 1}, max_wait_s=15.0)
    except (ApiError, RateLimited) as exc:
        return Capability(match, False, f"rede {match} encontrada, mas /trending_pools falhou: {exc}")
    pools = (trending or {}).get("data") or []
    sample = next((p.get("attributes", {}).get("address") for p in pools if isinstance(p, dict) and p.get("attributes", {}).get("address")), None)
    if not sample:
        return Capability(match, False, f"rede {match} encontrada, mas sem pool de amostra para confirmar OHLCV")
    try:
        ohlcv = http.get_json(f"networks/{match}/pools/{sample}/ohlcv/hour", {"aggregate": 1, "limit": 1, "currency": "usd"}, max_wait_s=15.0)
    except (ApiError, RateLimited) as exc:
        return Capability(match, False, f"rede {match} encontrada, mas /ohlcv falhou no pool de amostra: {exc}")
    has_ohlcv = bool(((ohlcv or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list"))
    if not has_ohlcv:
        return Capability(match, False, f"rede {match} encontrada, mas OHLCV veio vazio para o pool de amostra")
    return Capability(match, True, "")


class _DisabledAdapter(ChainAdapter):
    """BscAdapter/RobinhoodAdapter na FASE 2: capacidade real verificada (rede + OHLCV com pool de amostra) e
    OHLCV ja funciona de verdade (mesmo `OhlcvStore` da Solana, so troca a rede) -- mas descoberta/holders
    ainda sao Fase 2 e `capable()` fica sempre False por decisao explicita do operador ("mantendo BSC e
    Robinhood desligadas por padrao"), nao porque a deteccao falhou. Log claro + aviso no Telegram (1x por
    processo) quando a rede nao e encontrada ou nao tem OHLCV -- nunca derruba o bot."""

    def __init__(self, name: str, network_candidates: tuple[str, ...], http: Any, links: Optional[dict[str, str]] = None,
                telegram: Any = None, cache_dir: Any = None):
        self.name = name
        self._network_candidates = network_candidates
        self._http = http
        self._links = links or {}
        self._telegram = telegram
        self._cache_dir = cache_dir
        self._capability: Optional[Capability] = None
        self._ohlcv_store: Optional[OhlcvStore] = None
        self._warned = False

    def check(self) -> Capability:
        if self._capability is None:
            self._capability = detect_capability(self._http, self._network_candidates)
            if not self._capability.ok and not self._warned:
                self._warned = True
                log.warning("POS-RUNNER-V1: chain %s desligada (%s)", self.name, self._capability.motivo)
                if self._telegram is not None:
                    try:
                        self._telegram.notify(f"⚠ POS-RUNNER-V1: chain {self.name} desligada ({self._capability.motivo})")
                    except Exception:  # noqa: BLE001 - aviso e melhor-esforco, nunca derruba o startup
                        log.exception("POS-RUNNER-V1: falha ao avisar no Telegram sobre %s", self.name)
        return self._capability

    def capable(self) -> bool:
        return False   # decisao explicita do operador: BSC/Robinhood ficam desligadas por padrao na Fase 2

    def discover(self, source: str, now: float) -> DiscoveredPool:
        raise NotImplementedError(f"{self.name}: descoberta e Fase 2")

    def ohlcv(self, pool: str, tf: str, start_ts: int, end_ts: int, currency: str = "usd", side: str = "base") -> list[Bar]:
        """Ja funciona de verdade (mesmo `OhlcvStore` da Solana) -- so chega aqui se algum chamador pedir
        candles direto do adapter; nunca e chamado pelo ciclo ao vivo enquanto `capable()` for False."""
        cap = self.check()
        if not cap.ok or cap.network_id is None:
            raise NotImplementedError(f"{self.name}: capacidade nao confirmada ({cap.motivo})")
        if self._ohlcv_store is None:
            import tempfile
            from pathlib import Path
            cache_dir = Path(self._cache_dir) if self._cache_dir is not None else Path(tempfile.mkdtemp(prefix=f"pos_runner_{self.name}_"))
            self._ohlcv_store = OhlcvStore(self._http, cache_dir, network=cap.network_id)
        return self._ohlcv_store.history(pool, tf, start_ts, end_ts, currency=currency, side=side)

    def link_for(self, kind: str, mint: str, pool: str, gmgn_slug: str, dexscreener_slug: str) -> str:
        fields = {"pool": pool, "token": mint, "gmgn_slug": gmgn_slug, "dexscreener_slug": dexscreener_slug}
        key = "gmgn" if kind == "terminal" else "dexscreener"   # item 4: BSC e Robinhood usam GMGN, nunca Axiom
        url = self._links[key].format(**fields)
        assert url.startswith("https://"), f"link_for({kind}) nao produziu uma URL https:// valida: {url!r}"
        return url


class BscAdapter(_DisabledAdapter):
    def __init__(self, http: Any, links: Optional[dict[str, str]] = None, telegram: Any = None, cache_dir: Any = None):
        # "bsc" e o id real confirmado no GT (medido 2026-10-22); os outros ficam so como fallback.
        super().__init__("bsc", ("bsc", "bnb_chain", "binance-smart-chain"), http, links, telegram, cache_dir)


class RobinhoodAdapter(_DisabledAdapter):
    def __init__(self, http: Any, links: Optional[dict[str, str]] = None, telegram: Any = None, cache_dir: Any = None):
        # "robinhood" e o id real confirmado no GT (medido 2026-10-22; OHLCV ainda nao confirmado -- a rede
        # ficou indisponivel por rate limit durante a pesquisa, `check()` confirma isso de verdade no startup).
        super().__init__("robinhood", ("robinhood",), http, links, telegram, cache_dir)


def html_escape_ticker(value: str, limit: int = 20) -> str:
    """Item 4: HTML-escape de ticker/nome antes de qualquer template do Telegram."""
    return html.escape((value or "")[:limit], quote=False)
