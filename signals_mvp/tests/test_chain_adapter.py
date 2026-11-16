"""ChainAdapter (item 3.1 do PROMPT DEFINITIVO V1): SolanaAdapter (descoberta/OHLCV/links/holders/VAMP_RISK)
e deteccao de capacidade do BscAdapter/RobinhoodAdapter. Sem rede real."""

from __future__ import annotations

import unittest
from typing import Any, Optional
from unittest import mock

from ..http import ApiError
from ..models import ChainCtx
from ..pos_runner.candles import Bar
from ..pos_runner.chain_adapter import (
    AuthorityCheck, BscAdapter, CLASSE_OWNER_NAO_RESOLVIDO, HOLDER_CONCENTRADO_PCT, RobinhoodAdapter,
    SolanaAdapter, VampCheck, detect_capability,
)
from ..pos_runner.solana_rpc import RpcError

CTX = ChainCtx(name="solana", platform="solana", gt_network="solana", reference=frozenset())
LINKS = {
    "axiom": "https://axiom.trade/t/{pool}",
    "gmgn": "https://gmgn.ai/sol/token/{token}",
    "dexscreener": "https://dexscreener.com/solana/{pool}",
}


def _token(addr: str, symbol: str, name: str) -> dict:
    return {"attributes": {"address": addr, "symbol": symbol, "name": name}}


def _pool_item(pool: str, dex: str, base_id: str, quote_id: str) -> dict:
    return {
        "id": f"solana_{pool}",
        "attributes": {"address": pool, "name": f"{pool} pool", "base_token_price_usd": "1.0", "market_cap_usd": "500000"},
        "relationships": {
            "base_token": {"data": {"id": base_id}},
            "quote_token": {"data": {"id": quote_id}},
            "dex": {"data": {"id": dex}},
        },
    }


def gt_pools_response() -> dict:
    return {
        "data": [
            _pool_item("poolA", "pumpswap", "solana_mintA", "solana_SOL"),
            _pool_item("poolB", "meteora-damm-v2", "solana_mintB", "solana_SOL"),
            _pool_item("poolC", "raydium_clmm_other", "solana_mintC", "solana_SOL"),   # fora de GRAD_DEX
        ],
        "included": [
            {"id": "solana_mintA", **_token("mintA", "AAA", "Token A")},
            {"id": "solana_mintB", **_token("mintB", "BBB", "Token B")},
            {"id": "solana_mintC", **_token("mintC", "CCC", "Token C")},
            {"id": "solana_SOL", **_token("SOL", "SOL", "Solana")},
        ],
    }


class _FakeHttp:
    def __init__(self, responses: dict[str, Any]):
        self.responses = responses
        self.calls: list[tuple[str, Any]] = []

    def get_json(self, path: str, params: Any = None, max_wait_s: float = 5.0) -> Any:
        self.calls.append((path, params))
        if path not in self.responses:
            raise ApiError("http", f"sem resposta fake para {path}")
        return self.responses[path]


class _FakeOhlcv:
    def __init__(self, bars: list[Bar]):
        self.bars = bars
        self.calls: list[tuple] = []

    def history(self, pool, tf, start_ts, end_ts, currency="usd", side="base"):
        self.calls.append((pool, tf, start_ts, end_ts, currency, side))
        return self.bars


class _FakeRpc:
    def __init__(self, largest: dict, supply: float, owners: dict[str, str], fail_accounts: frozenset = frozenset()):
        self.largest = largest
        self.supply = supply
        self.owners = owners
        self.fail_accounts = fail_accounts

    def call(self, method: str, params: list) -> Any:
        if method == "getTokenLargestAccounts":
            return self.largest
        if method == "getAccountInfo":
            address = params[0]
            if address in self.fail_accounts:
                raise RpcError("transport", "timeout")
            return {"value": {"owner": self.owners.get(address)}}
        raise AssertionError(f"metodo inesperado: {method}")

    def token_supply(self, mint: str) -> float:
        return self.supply


class SolanaAdapterTests(unittest.TestCase):
    def test_discover_filters_by_graduation_dex(self):
        http = _FakeHttp({"networks/solana/trending_pools": gt_pools_response()})
        adapter = SolanaAdapter(http, CTX, _FakeOhlcv([]), None, LINKS)
        found = adapter.discover("trending", 1_000.0)
        self.assertEqual(found.source, "trending")
        self.assertEqual({s.pool for s in found.snaps}, {"poolA", "poolB"})

    def test_capable_is_always_true(self):
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), None, LINKS)
        self.assertTrue(adapter.capable())

    def test_ohlcv_delegates_to_the_store(self):
        bars = [Bar(0, 1, 1, 1, 1, 1)]
        store = _FakeOhlcv(bars)
        adapter = SolanaAdapter(_FakeHttp({}), CTX, store, None, LINKS)
        out = adapter.ohlcv("poolA", "1h", 0, 3600)
        self.assertEqual(out, bars)
        self.assertEqual(store.calls, [("poolA", "1h", 0, 3600, "usd", "base")])

    def test_link_for_terminal_and_dexscreener(self):
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), None, LINKS, terminal="axiom")
        self.assertEqual(adapter.link_for("terminal", "mintA", "poolA", "", ""), "https://axiom.trade/t/poolA")
        self.assertEqual(adapter.link_for("dexscreener", "mintA", "poolA", "", ""), "https://dexscreener.com/solana/poolA")

    def test_link_for_rejects_a_non_https_template(self):
        bad_links = dict(LINKS, axiom="http://axiom.trade/t/{pool}")
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), None, bad_links, terminal="axiom")
        with self.assertRaises(AssertionError):
            adapter.link_for("terminal", "mintA", "poolA", "", "")

    def test_holders_excludes_known_programs_and_flags_above_threshold(self):
        largest = {"value": [
            {"address": "wallet_big", "uiAmount": 2.0},     # 2% -- holder humano
            {"address": "token_program_vault", "uiAmount": 50.0},   # 50% -- mas owner e o Token Program
        ]}
        owners = {"wallet_big": "SomeOwnerNotExcluded", "token_program_vault": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}
        rpc = _FakeRpc(largest, supply=100.0, owners=owners)
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        result = adapter.holders("mintA")
        self.assertEqual(result.tag, "HOLDER_CONCENTRADO")
        self.assertAlmostEqual(result.top_holder_pct, 2.0)   # a conta do Token Program nunca conta

    def test_holders_top_holders_excludes_programs_and_sorts_by_pct_desc(self):
        # PEDIDO 2026-10-27 (H9): `top_holders` reusa a MESMA resolucao de owner que `top_holder_pct`
        # ja usa -- so devolve a lista inteira (ordenada desc), em vez de so o maximo.
        largest = {"value": [
            {"address": "wallet_small", "uiAmount": 1.0},      # 1%
            {"address": "wallet_big", "uiAmount": 2.0},        # 2%
            {"address": "token_program_vault", "uiAmount": 50.0},   # excluido (owner = Token Program)
        ]}
        owners = {"wallet_small": "OwnerPequeno", "wallet_big": "OwnerGrande",
                 "token_program_vault": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}
        rpc = _FakeRpc(largest, supply=100.0, owners=owners)
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        result = adapter.holders("mintA")
        self.assertEqual([o for o, _pct in result.top_holders], ["OwnerGrande", "OwnerPequeno"])

    def test_holders_below_threshold_has_no_tag(self):
        largest = {"value": [{"address": "wallet_small", "uiAmount": 1.0}]}
        rpc = _FakeRpc(largest, supply=100.0, owners={"wallet_small": "SomeOwner"})
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        result = adapter.holders("mintA")
        self.assertIsNone(result.tag)
        self.assertLess(result.top_holder_pct, HOLDER_CONCENTRADO_PCT)

    def test_holders_unavailable_without_rpc(self):
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), None, LINKS)
        self.assertEqual(adapter.holders("mintA").tag, "holders_indisponivel")

    def test_holders_propagates_a_classe_do_erro_rpc(self) -> None:
        """HANDOFF 2026-11-12/13: `holders()` repassa `exc.classe` (classificar_erro, ver
        solana_rpc.py) pro `HolderCheck.detail` -- nunca so `motivo` em texto livre, pra
        saude/heartbeat poderem distinguir endpoint morto de rate limit real."""
        from ..pos_runner.solana_rpc import CLASSE_AUTENTICACAO

        class _FakeRpcFalhaAuth:
            def call(self, method: str, params: list) -> Any:
                raise RpcError("transport", "HTTP 401", 401, classe=CLASSE_AUTENTICACAO)

            def token_supply(self, mint: str) -> float:
                return 100.0

        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), _FakeRpcFalhaAuth(), LINKS)
        result = adapter.holders("mintA")
        self.assertEqual(result.tag, "holders_indisponivel")
        self.assertEqual(result.detail.get("classe"), CLASSE_AUTENTICACAO)

    def test_holders_nunca_foi_alterado_por_holders_com_owner(self) -> None:
        """RODADA 21 (2026-11-16), item 1: `holders()` alimenta tags/holders_tag/holder_top1_pct
        (HOLDER_CONCENTRADO) e carteiras_pro_presentes/n_pessoas_pro em pr1_signals/pr2_signals
        (hipotese pre-registrada H8, `docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md`) -- fica
        BYTE A BYTE IGUAL. Hash do source travado AGORA (antes da rodada 21 tocar em qualquer coisa
        neste arquivo) -- se este teste falhar, `holders()` mudou e precisa de autorizacao/emenda
        propria ao H8, nunca um ajuste silencioso."""
        import hashlib
        import inspect

        src = inspect.getsource(SolanaAdapter.holders)
        self.assertEqual(hashlib.sha256(src.encode()).hexdigest()[:16], "1a8afc13aa675b92",
                         "holders() mudou -- isso afeta tags/HOLDER_CONCENTRADO/H8, nunca so carteiras")

    def test_vamp_risk_flags_an_older_bigger_same_ticker(self):
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), None, LINKS)
        search = lambda symbol: [{"symbol": "AAA", "created_ts": 1.0, "mc_usd": 9_000_000.0}]
        result = adapter.vamp_risk("AAA", mc_usd=500_000.0, search=search)
        self.assertEqual(result.tag, "VAMP_RISK")

    def test_vamp_risk_absent_without_a_bigger_older_match(self):
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), None, LINKS)
        result = adapter.vamp_risk("AAA", mc_usd=500_000.0, search=lambda s: [])
        self.assertEqual(result, VampCheck())

    def test_vamp_risk_search_failure_never_guesses_a_tag(self):
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), None, LINKS)

        def broken(symbol: str):
            raise ApiError("http", "falhou")

        result = adapter.vamp_risk("AAA", mc_usd=500_000.0, search=broken)
        self.assertIsNone(result.tag)


# RODADA 21 (2026-11-16): TOKEN_PROGRAM_ID aqui so pra deixar explicito, no proprio payload do fake,
# que o `owner` de NIVEL DE CIMA (qualquer conta gerenciada pelo SPL Token Program -- toda token
# account real) e DIFERENTE do owner REAL (`data.parsed.info.owner`) -- exatamente o que
# `holders_com_owner` tem que ler. Confirmado ao vivo contra api.mainnet-beta.solana.com
# (getAccountInfo/getMultipleAccounts, encoding jsonParsed) na sessao que encontrou o bug.
_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


class _FakeRpcMultiAccounts:
    """RODADA 21 (2026-11-16): formato REAL de `getMultipleAccounts`/jsonParsed -- `value` e uma
    LISTA alinhada por indice aos enderecos pedidos (`None` = conta inexistente); cada item presente
    tem a MESMA forma de `getAccountInfo` -- `owner` de nivel de cima e SEMPRE o Program ID da conta
    (pra token account, SEMPRE o SPL Token Program), a wallet REAL fica em
    `data.parsed.info.owner`. NUNCA o formato simplificado `{"value": {"owner": X}}` do `_FakeRpc`
    acima (que so serve pra `holders()`, intocado por esta rodada)."""

    def __init__(self, largest: dict, supply: float, contas: dict[str, Optional[dict]],
                 lote_max: Optional[int] = None):
        self.largest = largest
        self.supply = supply
        self.contas = contas   # endereco -> {"owner_real": str, "tipo": "account"} ou None (conta nao existe)
        self.lote_max = lote_max
        self.chamadas_multi: list[list[str]] = []

    def call(self, method: str, params: list) -> Any:
        if method == "getTokenLargestAccounts":
            return self.largest
        if method == "getMultipleAccounts":
            enderecos, _opts = params
            if self.lote_max is not None and len(enderecos) > self.lote_max:
                raise RpcError("transport", "HTTP 413", 413)
            self.chamadas_multi.append(list(enderecos))
            value = []
            for endereco in enderecos:
                conta = self.contas.get(endereco)
                if conta is None:
                    value.append(None)
                    continue
                value.append({
                    "data": {"parsed": {"type": conta.get("tipo", "account"), "info": {
                        "owner": conta["owner_real"], "mint": "MINTX", "state": "initialized",
                        "tokenAmount": {"amount": "0", "decimals": 0, "uiAmount": 0.0, "uiAmountString": "0"},
                    }}, "program": "spl-token"},
                    "executable": False, "lamports": 2039280,
                    "owner": _TOKEN_PROGRAM_ID,   # SEMPRE o Token Program -- NUNCA a wallet real
                    "rentEpoch": 0, "space": 165,
                })
            return {"value": value}
        raise AssertionError(f"metodo inesperado: {method}")

    def token_supply(self, mint: str) -> float:
        return self.supply


class HoldersComOwnerTests(unittest.TestCase):
    """RODADA 21 (2026-11-16, autorizada): `holders_com_owner()` -- correcao do owner usado pela
    instrumentacao de carteiras "pro" (RODADA 20, pergunta 3). `holders()` em si fica intocado (ver
    `test_holders_nunca_foi_alterado_por_holders_com_owner` acima)."""

    def test_le_o_owner_real_do_jsonparsed_nunca_o_token_program_da_conta(self) -> None:
        largest = {"value": [{"address": "contaA", "uiAmount": 5.0}, {"address": "contaB", "uiAmount": 3.0}]}
        rpc = _FakeRpcMultiAccounts(largest, supply=100.0, contas={
            "contaA": {"owner_real": "WalletHumanaA"}, "contaB": {"owner_real": "WalletHumanaB"},
        })
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        result = adapter.holders_com_owner("mintA")
        owners = {o for o, _pct in result.top_holders}
        self.assertEqual(owners, {"WalletHumanaA", "WalletHumanaB"})
        self.assertNotIn(_TOKEN_PROGRAM_ID, owners,
                         "nunca pode devolver o Program ID da conta como se fosse a wallet real")
        self.assertAlmostEqual(result.top_holder_pct, 5.0)
        self.assertEqual(result.detail["contas_totais"], 2)
        self.assertEqual(result.detail["contas_excluidas_pool_curva"], 0)
        self.assertEqual(result.detail["contas_sem_owner"], 0)

    def test_exclui_pool_curva_pelo_owner_real_resolvido(self) -> None:
        # "contaPool" tem um owner_real que e um PROGRAMA conhecido (launchpad/AMM) -- tem que ser
        # excluido pelo OWNER, nunca pelo endereco da conta em si (que e so uma ATA qualquer).
        largest = {"value": [
            {"address": "contaHumana", "uiAmount": 2.0},
            {"address": "contaPool", "uiAmount": 90.0},
        ]}
        rpc = _FakeRpcMultiAccounts(largest, supply=100.0, contas={
            "contaHumana": {"owner_real": "WalletHumana"},
            "contaPool": {"owner_real": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"},   # programa pumpfun
        })
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        excluded = adapter.excluded_accounts("poolA", "mintA", "pumpfun")
        result = adapter.holders_com_owner("mintA", excluded)
        owners = {o for o, _pct in result.top_holders}
        self.assertEqual(owners, {"WalletHumana"})
        self.assertEqual(result.detail["contas_excluidas_pool_curva"], 1)

    def test_conta_sem_owner_e_contada_e_nunca_quebra(self) -> None:
        largest = {"value": [
            {"address": "contaViva", "uiAmount": 2.0},
            {"address": "contaFechada", "uiAmount": 1.0},   # getMultipleAccounts devolve None p/ ela
        ]}
        rpc = _FakeRpcMultiAccounts(largest, supply=100.0, contas={
            "contaViva": {"owner_real": "WalletHumana"}, "contaFechada": None,
        })
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        result = adapter.holders_com_owner("mintA")
        self.assertEqual({o for o, _pct in result.top_holders}, {"WalletHumana"})
        self.assertEqual(result.detail["contas_sem_owner"], 1)

    def test_invariante_de_sanidade_sem_nenhum_owner_valido_nunca_fica_cobertura_valida(self) -> None:
        # item 4 da RODADA 21: RPC respondeu (sem excecao), supply existe, mas NENHUM owner valido
        # sobra (tudo excluido/sem_owner) -- nunca pode parecer sucesso (cobertura_valida=1 por
        # omissao); tem que virar holders_indisponivel com a classe PROPRIA (nunca confundida com
        # falha de transporte).
        largest = {"value": [
            {"address": "contaPool", "uiAmount": 90.0},
            {"address": "contaFechada", "uiAmount": 1.0},
        ]}
        rpc = _FakeRpcMultiAccounts(largest, supply=100.0, contas={
            "contaPool": {"owner_real": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"},
            "contaFechada": None,
        })
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        excluded = adapter.excluded_accounts("poolA", "mintA", "pumpfun")
        result = adapter.holders_com_owner("mintA", excluded)
        self.assertEqual(result.tag, "holders_indisponivel")
        self.assertEqual(result.detail.get("classe"), CLASSE_OWNER_NAO_RESOLVIDO)
        self.assertEqual(result.top_holders, [])

    def test_faz_lotes_de_ate_5_contas_nunca_1_chamada_so_com_mais_de_5(self) -> None:
        # EMENDA 2026-10-16/17 (enumerate.GET_MULTIPLE_ACCOUNTS_BATCH): QuickNode no plano "discover"
        # free recusa getMultipleAccounts com mais de 5 chaves (HTTP 413) -- nunca reintroduzir isso.
        enderecos = [f"conta{i}" for i in range(12)]
        largest = {"value": [{"address": e, "uiAmount": 1.0} for e in enderecos]}
        contas = {e: {"owner_real": f"Wallet{i}"} for i, e in enumerate(enderecos)}
        rpc = _FakeRpcMultiAccounts(largest, supply=100.0, contas=contas, lote_max=5)
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        result = adapter.holders_com_owner("mintA")
        self.assertEqual(len(result.top_holders), 12)
        self.assertEqual([len(lote) for lote in rpc.chamadas_multi], [5, 5, 2])

    def test_coletor_versao_vai_no_detail(self) -> None:
        from ..pos_runner.chain_adapter import CARTEIRAS_COLETOR_VERSAO
        largest = {"value": [{"address": "contaA", "uiAmount": 5.0}]}
        rpc = _FakeRpcMultiAccounts(largest, supply=100.0, contas={"contaA": {"owner_real": "WalletA"}})
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        result = adapter.holders_com_owner("mintA")
        self.assertEqual(result.detail["coletor_versao"], CARTEIRAS_COLETOR_VERSAO)

    def test_sem_rpc_e_indisponivel(self) -> None:
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), None, LINKS)
        self.assertEqual(adapter.holders_com_owner("mintA").tag, "holders_indisponivel")

    def test_propaga_a_classe_do_erro_rpc_na_falha_de_getmultipleaccounts(self) -> None:
        from ..pos_runner.solana_rpc import CLASSE_CONEXAO

        class _FakeRpcFalhaNoMulti:
            def call(self, method: str, params: list) -> Any:
                if method == "getTokenLargestAccounts":
                    return {"value": [{"address": "contaA", "uiAmount": 5.0}]}
                if method == "getMultipleAccounts":
                    raise RpcError("transport", "timeout", classe=CLASSE_CONEXAO)
                raise AssertionError(f"metodo inesperado: {method}")

            def token_supply(self, mint: str) -> float:
                return 100.0

        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), _FakeRpcFalhaNoMulti(), LINKS)
        result = adapter.holders_com_owner("mintA")
        self.assertEqual(result.tag, "holders_indisponivel")
        self.assertEqual(result.detail.get("classe"), CLASSE_CONEXAO)


class _FakeMintRpc:
    """So pra `authorities()` (item 2 da FASE 2 de medicao/UX) -- formato de resposta diferente do
    `_FakeRpc` acima (que simula so o fluxo de holders/owner)."""

    def __init__(self, mint_info: Optional[dict[str, dict]] = None, fail: bool = False):
        self.mint_info = mint_info or {}
        self.fail = fail
        self.calls = 0

    def call(self, method: str, params: list) -> Any:
        assert method == "getAccountInfo"
        self.calls += 1
        if self.fail:
            raise RpcError("transport", "timeout")
        info = self.mint_info.get(params[0])
        if info is None:
            return {"value": None}
        return {"value": {"data": {"parsed": {"info": info}}}}

    def token_supply(self, mint: str) -> float:
        raise AssertionError("authorities() nunca deveria chamar token_supply")


class AuthoritiesTests(unittest.TestCase):
    def test_both_authorities_revoked(self):
        rpc = _FakeMintRpc({"mintA": {"mintAuthority": None, "freezeAuthority": None}})
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        result = adapter.authorities("mintA")
        self.assertEqual(result, AuthorityCheck("revogada", "revogada"))

    def test_both_authorities_still_active(self):
        rpc = _FakeMintRpc({"mintA": {"mintAuthority": "SomeAuthority111", "freezeAuthority": "SomeAuthority222"}})
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        result = adapter.authorities("mintA")
        self.assertEqual(result, AuthorityCheck("ativa", "ativa"))

    def test_mixed_authorities(self):
        rpc = _FakeMintRpc({"mintA": {"mintAuthority": None, "freezeAuthority": "SomeAuthority222"}})
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        result = adapter.authorities("mintA")
        self.assertEqual(result, AuthorityCheck("revogada", "ativa"))

    def test_rpc_failure_never_guesses_a_value(self):
        rpc = _FakeMintRpc(fail=True)
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        self.assertEqual(adapter.authorities("mintA"), AuthorityCheck("indisponivel", "indisponivel"))

    def test_unexpected_response_shape_never_guesses_a_value(self):
        rpc = _FakeMintRpc({"mintA": {"someOtherField": 1}})   # sem mintAuthority/freezeAuthority
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        self.assertEqual(adapter.authorities("mintA"), AuthorityCheck("indisponivel", "indisponivel"))

    def test_no_rpc_configured_is_indisponivel(self):
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), None, LINKS)
        self.assertEqual(adapter.authorities("mintA"), AuthorityCheck("indisponivel", "indisponivel"))

    def test_result_is_cached_one_rpc_call_per_mint(self):
        rpc = _FakeMintRpc({"mintA": {"mintAuthority": None, "freezeAuthority": None}})
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        adapter.authorities("mintA")
        adapter.authorities("mintA")
        adapter.authorities("mintA")
        self.assertEqual(rpc.calls, 1, "tem que cachear -- nunca repete a chamada RPC pro mesmo mint")

    def test_different_mints_each_get_their_own_call(self):
        rpc = _FakeMintRpc({
            "mintA": {"mintAuthority": None, "freezeAuthority": None},
            "mintB": {"mintAuthority": "x", "freezeAuthority": "x"},
        })
        adapter = SolanaAdapter(_FakeHttp({}), CTX, _FakeOhlcv([]), rpc, LINKS)
        a = adapter.authorities("mintA")
        b = adapter.authorities("mintB")
        self.assertEqual(rpc.calls, 2)
        self.assertNotEqual(a, b)


class _FakeTelegram:
    def __init__(self):
        self.messages: list[str] = []

    def notify(self, text: str) -> None:
        self.messages.append(text)


def _trending_with_sample(address: str = "0xsample") -> dict:
    return {"data": [{"attributes": {"address": address}}]}


def _ohlcv_with_bars(rows: list[list[Any]]) -> dict:
    return {"data": {"attributes": {"ohlcv_list": rows}}}


class CapabilityTests(unittest.TestCase):
    def test_detect_capability_finds_a_matching_network_id(self):
        http = _FakeHttp({"networks": {"data": [{"id": "bsc"}, {"id": "solana"}]}})
        cap = detect_capability(http, ("bsc", "bnb_chain"))
        self.assertEqual(cap.network_id, "bsc")
        self.assertFalse(cap.ok)   # /trending_pools nao foi mockado -- falha explicita, nunca assume OHLCV

    def test_detect_capability_explicit_reason_when_the_network_is_not_listed(self):
        http = _FakeHttp({"networks": {"data": [{"id": "solana"}]}})
        cap = detect_capability(http, ("robinhood",))
        self.assertIsNone(cap.network_id)
        self.assertIn("robinhood", cap.motivo)

    def test_detect_capability_confirms_real_ohlcv_end_to_end(self):
        http = _FakeHttp({
            "networks": {"data": [{"id": "bsc"}]},
            "networks/bsc/trending_pools": _trending_with_sample(),
            "networks/bsc/pools/0xsample/ohlcv/hour": _ohlcv_with_bars([[3600, 1, 2, 0.5, 1.5, 100]]),
        })
        cap = detect_capability(http, ("bsc",))
        self.assertEqual(cap.network_id, "bsc")
        self.assertTrue(cap.ok)
        self.assertEqual(cap.motivo, "")

    def test_detect_capability_explicit_reason_when_there_is_no_sample_pool(self):
        http = _FakeHttp({
            "networks": {"data": [{"id": "bsc"}]},
            "networks/bsc/trending_pools": {"data": []},
        })
        cap = detect_capability(http, ("bsc",))
        self.assertFalse(cap.ok)
        self.assertIn("amostra", cap.motivo)

    def test_detect_capability_explicit_reason_when_ohlcv_comes_back_empty(self):
        http = _FakeHttp({
            "networks": {"data": [{"id": "bsc"}]},
            "networks/bsc/trending_pools": _trending_with_sample(),
            "networks/bsc/pools/0xsample/ohlcv/hour": _ohlcv_with_bars([]),
        })
        cap = detect_capability(http, ("bsc",))
        self.assertFalse(cap.ok)
        self.assertIn("vazio", cap.motivo)

    def test_bsc_and_robinhood_adapters_are_disabled_by_default(self):
        http = _FakeHttp({"networks": {"data": [{"id": "bsc"}]}})
        self.assertFalse(BscAdapter(http).capable())
        self.assertFalse(RobinhoodAdapter(http).capable())

    def test_disabled_adapter_link_for_still_asserts_https_and_uses_gmgn(self):
        adapter = BscAdapter(_FakeHttp({}), links=LINKS)
        url = adapter.link_for("terminal", "0xabc", "0xpool", "", "")
        self.assertTrue(url.startswith("https://gmgn.ai"))

    def test_check_notifies_telegram_once_when_capability_is_not_confirmed(self):
        http = _FakeHttp({"networks": {"data": [{"id": "solana"}]}})   # bsc nao existe
        telegram = _FakeTelegram()
        adapter = BscAdapter(http, telegram=telegram)
        adapter.check()
        adapter.check()   # repetir nao pode mandar um 2o aviso
        self.assertEqual(len(telegram.messages), 1)
        self.assertIn("bsc", telegram.messages[0])

    def test_check_never_notifies_when_capability_is_confirmed(self):
        http = _FakeHttp({
            "networks": {"data": [{"id": "bsc"}]},
            "networks/bsc/trending_pools": _trending_with_sample(),
            "networks/bsc/pools/0xsample/ohlcv/hour": _ohlcv_with_bars([[3600, 1, 2, 0.5, 1.5, 100]]),
        })
        telegram = _FakeTelegram()
        adapter = BscAdapter(http, telegram=telegram)
        cap = adapter.check()
        self.assertTrue(cap.ok)
        self.assertEqual(telegram.messages, [])

    def test_check_survives_a_broken_telegram_client(self):
        http = _FakeHttp({"networks": {"data": [{"id": "solana"}]}})

        class _BrokenTelegram:
            def notify(self, text: str) -> None:
                raise RuntimeError("rede fora")

        adapter = BscAdapter(http, telegram=_BrokenTelegram())
        cap = adapter.check()   # nunca derruba o startup
        self.assertFalse(cap.ok)

    def test_ohlcv_raises_a_clear_error_when_capability_is_not_confirmed(self):
        http = _FakeHttp({"networks": {"data": [{"id": "solana"}]}})
        adapter = BscAdapter(http)
        with self.assertRaises(NotImplementedError):
            adapter.ohlcv("0xpool", "1h", 0, 3600)

    def test_ohlcv_builds_the_store_for_the_confirmed_network_once_capability_is_ok(self):
        http = _FakeHttp({
            "networks": {"data": [{"id": "bsc"}]},
            "networks/bsc/trending_pools": _trending_with_sample(),
            "networks/bsc/pools/0xsample/ohlcv/hour": _ohlcv_with_bars([[3600, 1, 2, 0.5, 1.5, 100]]),
        })
        bars = [Bar(0, 1, 1, 1, 1, 1)]
        fake_store = _FakeOhlcv(bars)
        with mock.patch("signals_mvp.pos_runner.chain_adapter.OhlcvStore", return_value=fake_store) as ctor:
            adapter = BscAdapter(http)
            out = adapter.ohlcv("0xpool", "1h", 0, 3600)
        self.assertEqual(out, bars)
        ctor.assert_called_once_with(http, mock.ANY, network="bsc")
        self.assertEqual(fake_store.calls, [("0xpool", "1h", 0, 3600, "usd", "base")])

    def test_ohlcv_reuses_the_same_store_across_calls(self):
        http = _FakeHttp({
            "networks": {"data": [{"id": "bsc"}]},
            "networks/bsc/trending_pools": _trending_with_sample(),
            "networks/bsc/pools/0xsample/ohlcv/hour": _ohlcv_with_bars([[3600, 1, 2, 0.5, 1.5, 100]]),
        })
        fake_store = _FakeOhlcv([])
        with mock.patch("signals_mvp.pos_runner.chain_adapter.OhlcvStore", return_value=fake_store) as ctor:
            adapter = BscAdapter(http)
            adapter.ohlcv("0xpool", "1h", 0, 3600)
            adapter.ohlcv("0xpool", "4h", 0, 3600)
        ctor.assert_called_once()   # /networks + /trending_pools + /ohlcv so uma vez no processo, nunca por ciclo


if __name__ == "__main__":
    unittest.main()
