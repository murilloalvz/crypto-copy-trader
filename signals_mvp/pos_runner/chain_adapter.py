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
from .carteiras_pro import base58_decode
from .enumerate import GET_MULTIPLE_ACCOUNTS_BATCH, LAUNCHPADS
from .solana_pda import PdaNaoEncontradoError, find_program_address
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

# RODADA 21 (2026-11-16, autorizada): correcao do owner usado pela instrumentacao de carteiras "pro"
# -- ver `SolanaAdapter.holders_com_owner` abaixo. `classe` propria (nunca confundida com as de
# `solana_rpc.classificar_erro`, que sao so de falha de TRANSPORTE): aqui a chamada RPC teve sucesso,
# o dado em si e que nao permite nenhuma leitura valida de owner.
CLASSE_OWNER_NAO_RESOLVIDO = "owner_nao_resolvido"
# versao do coletor gravada em CADA linha nova de `pr_carteiras_snapshot`/`pr3_carteiras_sinal` (coluna
# `coletor_versao`, NULL em linhas anteriores a este deploy) -- marca explicita de qual logica gerou a
# linha, pra EMENDA_2026-11-16_CORRECAO_OWNER_CARTEIRAS.md declarar o corte de amostra sem ambiguidade.
# RODADA 22 (2026-11-17, autorizada): subida p/ v2 ANTES de qualquer sinal V3 real sob a v1 (item 1 --
# exclusao do proprio pool + PDA da bonding curve). Linhas v1 ficam como DIAGNOSTICO (nunca apagadas/
# editadas), fora de qualquer contagem de N -- ver emenda, secao da RODADA 22.
CARTEIRAS_COLETOR_VERSAO = "owner_fix_v2_2026-11-17"


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
    # PEDIDO 2026-10-27 (H9, snapshot de carteiras "pro"): os owners resolvidos (ja excluindo queima/
    # programas base/vaults do pool -- MESMA exclusao de `top_holder_pct`), ordenados por % desc, ate
    # o limite que `getTokenLargestAccounts` devolve (20 contas, sem paginacao -- ja e "top 20").
    # Reaproveita a MESMA chamada RPC de `holders()` -- nunca uma chamada extra so por isto.
    top_holders: list[tuple[str, float]] = field(default_factory=list)


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

    def excluded_accounts_carteiras_forward(self, pool: str, mint: str,
                                            launchpad: Optional[str]) -> frozenset[str]:
        """RODADA 22 (2026-11-17, autorizada), item 1: achado na Rodada 21 -- nos 19 snapshots
        novos (ja com owner correto), `contas_excluidas_pool_curva=0` em todos e em 12/19 o 1o
        holder resolvido era o PROPRIO endereco do pool (`pool`, o parametro ja existia aqui mas
        nunca era usado). `excluded_accounts()` acima so exclui o PROGRAMA do launchpad/AMM destino
        (compartilhado por TODOS os pools daquele launchpad) -- nunca a conta ESPECIFICA deste pool,
        que e quem de fato custodia o supply enquanto ele e o maior "holder". Correcao: reusa
        `excluded_accounts()` (nunca duplica a logica) + adiciona o `pool` em si + (quando
        launchpad=='pumpfun') o PDA da bonding-curve do mint (seeds=['bonding-curve', mint],
        programa pump.fun -- `solana_pda.find_program_address`).

        RODADA 22, condicao 1 do operador (confirmado nesta sessao, nunca so por SDK de terceiros):
        o seed `['bonding-curve', mint]` foi testado contra 4 pares (mint, bonding-curve) REAIS,
        observados ao vivo via `getTransaction`/jsonParsed contra api.mainnet-beta.solana.com (conta
        referenciada na mesma instrucao/CPI do programa pump.fun) -- os 4 bateram exatamente,
        incluindo 1 par Token-2022 (`create_v2`), o que descarta a hipotese de uma variante
        'bonding-curve-v2' para esse caso tambem (testado e NAO bate -- ver
        `test_solana_pda.BondingCurveSeedFixtureTests`). raydium_launchlab/meteora_dbc NAO tem PDA de
        curva implementado aqui (so pump.fun foi pesquisado/confirmado) -- `pool_after_program` (ja
        coberto por `excluded_accounts()`) e tudo que cobre os outros launchpads hoje.

        Usada SO pelos call sites que alimentam `holders_com_owner()` (pr_carteiras_snapshot/
        pr3_carteiras_sinal) -- NUNCA pelos que alimentam `holders()` (tags/holders_tag/
        HOLDER_CONCENTRADO/H8, que ficam com `excluded_accounts()` de sempre, intocado)."""
        excluded = set(self.excluded_accounts(pool, mint, launchpad))
        excluded.add(pool)
        if launchpad == "pumpfun":
            spec = LAUNCHPADS.get("pumpfun")
            if spec is not None:
                try:
                    curva = find_program_address([b"bonding-curve", base58_decode(mint)], spec.program)
                    excluded.add(curva)
                except (ValueError, PdaNaoEncontradoError):
                    pass   # mint malformado/PDA nao encontrado: nunca derruba a captura por isto
        return frozenset(excluded)

    def holders(self, mint: str, exclude_accounts: frozenset[str] = frozenset()) -> HolderCheck:
        if self.rpc is None:
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": "sem RPC configurado"})
        try:
            largest = self.rpc.call("getTokenLargestAccounts", [mint]) or {}
            supply = self.rpc.token_supply(mint)
        except RpcError as exc:
            # HANDOFF 2026-11-12/13: `classe` (ver solana_rpc.classificar_erro) rotula a causa REAL
            # (conexao/autenticacao/rate_limit/muitas_contas/generico) -- nunca mais todo erro de RPC
            # virando "RateLimited" no log/saude/heartbeat (achado real na VM: endpoint morto por TLS
            # mascarado assim por 2 dias). `str(exc)` nunca inclui a URL/api-key crua (RpcError.message
            # e sempre construido de componentes controlados -- ver solana_rpc.py).
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": f"RPC: {exc}", "classe": exc.classe})
        # exclusoes do item 2.7/INTERPRETACOES.md #5: queima + programas base SEMPRE, mais o que o chamador
        # passou (vaults do pool/bonding curve especificos deste token, via `_excluded_accounts`)
        exclude_accounts = frozenset(exclude_accounts) | BASE_EXCLUDED_PROGRAMS | BURN_ADDRESSES
        accounts = (largest.get("value") or [])
        if not supply:
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": "supply indisponivel"})
        resolved = 0
        top_pct = 0.0
        owners: list[tuple[str, float]] = []
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
            if owner is not None:
                owners.append((owner, pct))
        if resolved == 0 and accounts:
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": "nenhuma conta resolveu o owner"})
        owners.sort(key=lambda t: t[1], reverse=True)
        if top_pct >= HOLDER_CONCENTRADO_PCT:
            return HolderCheck(tag="HOLDER_CONCENTRADO", top_holder_pct=top_pct, top_holders=owners)
        return HolderCheck(top_holder_pct=top_pct, top_holders=owners)

    # -- RODADA 21 (2026-11-16, autorizada): correcao do owner usado pela instrumentacao de ------------
    # carteiras "pro" (pr_carteiras_snapshot/pr3_carteiras_sinal) -----------------------------------------
    def holders_com_owner(self, mint: str, exclude_accounts: frozenset[str] = frozenset()) -> HolderCheck:
        """RODADA 20, pergunta 3 (achado): `holders()` acima le `value.owner` de `getAccountInfo`, que
        para QUALQUER token account e sempre o Program ID do SPL Token Program (`TokenkegQfe...`,
        JA esta em `BASE_EXCLUDED_PROGRAMS`) -- nunca a wallet que de fato detem os tokens (essa fica
        em `value.data.parsed.info.owner`; confirmado ao vivo contra api.mainnet-beta.solana.com e
        pelo metodo vizinho `authorities()`, que JA faz esse unwrap certo 20 linhas abaixo). Resultado:
        em produção, `owners`/`top_holders` de `holders()` SEMPRE vem vazio e `top_pct` SEMPRE 0.0.

        RODADA 21, item 1 (blast radius): `holders()` alimenta `tags`/`holders_tag`/`holder_top1_pct`
        (HOLDER_CONCENTRADO, `live.py: _entry_v1`/`_entry_v2`) e `carteiras_pro_presentes`/
        `n_pessoas_pro` em `pr1_signals`/`pr2_signals` (hipotese pre-registrada H8,
        `docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md`) -- `holders()` fica BYTE A BYTE IGUAL
        (ver `test_holders_nunca_foi_alterado_por_holders_com_owner`); H8 continua recebendo o MESMO
        dado de sempre (sempre 0, bug conhecido mas FORA desta rodada -- precisa de emenda propria ao
        pre-registro H8, nunca decidida aqui). Esta funcao e usada SO pela instrumentacao
        "carteiras forward" (`pr_carteiras_snapshot`/`pr3_carteiras_sinal`), nunca por sinal/filtro.

        Item 2: `getMultipleAccounts` (jsonParsed) em LOTES de `GET_MULTIPLE_ACCOUNTS_BATCH`=5
        contas (EMENDA 2026-10-16/17, `enumerate._verify_pools_exist_on_chain`: QuickNode no plano
        "discover" free recusa mais de 5 chaves por chamada, HTTP 413 -- ja medido em producao; o
        pedido original queria 1 chamada so, mas reintroduzir esse 413 conhecido custaria mais que
        economizar 3 chamadas), nunca 1 `getAccountInfo` por conta (orcamento/ritmo do RPC dedicado
        de carteiras conta CHAMADAS de verdade via `SolanaRpc.calls` -- isto reduz de ate 21 pra ate
        6 chamadas por snapshot, nunca aumenta).

        Item 3: `detail` sempre traz `contas_totais` (<=20, quantas `getTokenLargestAccounts`
        devolveu), `contas_excluidas_pool_curva` (owner bateu no programa do launchpad/AMM destino/
        Token Program/queima) e `contas_sem_owner` (a conta nao existe mais ou `getMultipleAccounts`
        nao devolveu parsed.info.owner) -- cobertura real = 1 - (excluidas+sem_owner)/totais.

        Item 4: invariante de sanidade -- sucesso aparente (RPC respondeu, supply existe) mas NENHUM
        owner valido sobrou (todas excluidas/sem_owner) OU a soma de pct do top-20 resolvido e 0 nunca
        fica `cobertura_valida=1` por omissao: volta `tag='holders_indisponivel'` com
        `classe=CLASSE_OWNER_NAO_RESOLVIDO`, MESMA chave que os chamadores (`_atualizar_carteiras_horaria`/
        `_capturar_carteiras_sinal_v3_holders`) ja usam para decidir `cobertura_valida`/`erro_classe`."""
        if self.rpc is None:
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": "sem RPC configurado"})
        try:
            largest = self.rpc.call("getTokenLargestAccounts", [mint]) or {}
            supply = self.rpc.token_supply(mint)
        except RpcError as exc:
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": f"RPC: {exc}", "classe": exc.classe})
        exclude_accounts = frozenset(exclude_accounts) | BASE_EXCLUDED_PROGRAMS | BURN_ADDRESSES
        accounts = (largest.get("value") or [])
        if not supply:
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": "supply indisponivel"})
        enderecos = [row.get("address") for row in accounts if row.get("address") is not None]
        contas_totais = len(enderecos)
        if contas_totais == 0:
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": "getTokenLargestAccounts sem contas"})
        # EMENDA 2026-10-16/17 (ja medida em producao, `enumerate._verify_pools_exist_on_chain`):
        # QuickNode no plano "discover" (free) recusa `getMultipleAccounts` com mais de
        # GET_MULTIPLE_ACCOUNTS_BATCH=5 chaves (HTTP 413, codigo -32615). O pedido desta rodada
        # queria 1 chamada so p/ as ate 20 contas; em lotes de 5 fica ate 4 chamadas -- ainda MUITO
        # menor que as ate 20 `getAccountInfo` de antes, e nunca reintroduz um 413 ja conhecido.
        infos: list[Any] = []
        try:
            for i in range(0, len(enderecos), GET_MULTIPLE_ACCOUNTS_BATCH):
                lote = enderecos[i:i + GET_MULTIPLE_ACCOUNTS_BATCH]
                multi = self.rpc.call("getMultipleAccounts", [lote, {"encoding": "jsonParsed"}]) or {}
                infos.extend(multi.get("value") or [None] * len(lote))
        except RpcError as exc:
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": f"RPC: {exc}", "classe": exc.classe})
        owner_por_endereco: dict[str, Optional[str]] = {}
        for endereco, info in zip(enderecos, infos):
            parsed = (((info or {}).get("data") or {}).get("parsed") or {})
            fields = parsed.get("info") or {}
            # `type` != "account" (ex.: a propria mint, ou formato inesperado) nunca fabrica um owner.
            owner_por_endereco[endereco] = fields.get("owner") if parsed.get("type") == "account" else None
        excluidas_pool_curva = 0
        sem_owner = 0
        owners: list[tuple[str, float]] = []
        for row in accounts:
            address = row.get("address")
            amount = row.get("uiAmount") or row.get("uiAmountString")
            if address is None or amount is None or address in exclude_accounts:
                continue
            owner = owner_por_endereco.get(address)
            if owner is None:
                sem_owner += 1
                continue
            if owner in exclude_accounts:
                excluidas_pool_curva += 1
                continue
            pct = 100.0 * float(amount) / float(supply)
            owners.append((owner, pct))
        detail: dict[str, Any] = {
            "contas_totais": contas_totais, "contas_excluidas_pool_curva": excluidas_pool_curva,
            "contas_sem_owner": sem_owner, "coletor_versao": CARTEIRAS_COLETOR_VERSAO,
        }
        soma_pct = sum(pct for _owner, pct in owners)
        if not owners or soma_pct <= 0.0:
            return HolderCheck(tag="holders_indisponivel", detail={
                **detail, "classe": CLASSE_OWNER_NAO_RESOLVIDO,
                "motivo": "nenhum owner valido resolvido (todas excluidas/sem_owner ou soma de pct = 0)",
            })
        owners.sort(key=lambda t: t[1], reverse=True)
        return HolderCheck(top_holder_pct=owners[0][1], top_holders=owners, detail=detail)

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
