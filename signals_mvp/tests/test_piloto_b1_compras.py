"""RODADA 25: `scripts/piloto_b1_compras.py` -- nunca abre banco (sqlite3.connect bloqueado), nunca chama
GT/Jupiter (urlopen bloqueado; so o RPC injetado), so os 2 metodos autorizados, medidor de creditos,
classificacao compra/venda/curva/liquidez a partir de tx sinteticos e aborto no 429."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ..scripts import piloto_b1_compras as pb

W1 = "1" * 32
W2 = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
POOL = "PoolAuthority1111111111111111111111111111111"
MINT_A, MINT_B = "MintA111111111111111111111111111111111111111", "MintB111111111111111111111111111111111111111"
T = pb.CONGELAMENTO_TS + 86400


def _bal(owner: str, mint: str, ui: float) -> dict:
    return {"owner": owner, "mint": mint, "uiTokenAmount": {"uiAmount": ui}}


def _tx(wallet: str, pre_tb: list, post_tb: list, lam: tuple[int, int], logs: list[str] = ()) -> dict:
    return {"transaction": {"message": {"accountKeys": [{"pubkey": wallet}]}},
            "meta": {"err": None, "preBalances": [lam[0]], "postBalances": [lam[1]],
                     "preTokenBalances": pre_tb, "postTokenBalances": post_tb, "logMessages": list(logs)}}


COMPRA_GRADUADA = _tx(W1, [_bal(POOL, MINT_A, 1e9), _bal(POOL, pb.WSOL, 100.0)],
                      [_bal(POOL, MINT_A, 9e8), _bal(POOL, pb.WSOL, 100.5), _bal(W1, MINT_A, 1e8)], (10**9, 5 * 10**8))
COMPRA_CURVA = _tx(W1, [], [_bal(W1, MINT_B, 5e6)], (10**9, 9 * 10**8),
                   ["Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke [2]"])
VENDA = _tx(W2, [_bal(W2, MINT_A, 100.0)], [_bal(W2, MINT_A, 40.0)], (10**9, 2 * 10**9))


class ClassificarTests(unittest.TestCase):
    def test_compra_graduada_mede_liquidez_pelos_cofres(self) -> None:
        k = pb.classificar_tx(COMPRA_GRADUADA, W1, sol_usd=70.0)
        self.assertEqual((k.tipo, k.mint, k.novo, k.curva), ("compra", MINT_A, True, None))
        self.assertAlmostEqual(k.liq_usd, 2 * 100.0 * 70.0)   # 14k USD >= 5k

    def test_compra_na_curva(self) -> None:
        k = pb.classificar_tx(COMPRA_CURVA, W1, sol_usd=70.0)
        self.assertEqual((k.tipo, k.curva, k.liq_usd), ("compra", "pumpfun", None))

    def test_venda_e_fracao_vendida(self) -> None:
        k = pb.classificar_tx(VENDA, W2, sol_usd=70.0)
        self.assertEqual(k.tipo, "venda")
        self.assertAlmostEqual(k.fracao_vendida, 0.6)

    def test_decisao_regra_b4(self) -> None:
        fr = {k: (0.5, 0.4, 0.6) for k in ("f_compra", "f_novo")}
        fr.update({k: (0.0, 0.0, 0.1) for k in ("f_curva", "f_sem_dado", "f_liq_menor_5k", "sobreposicao")})
        self.assertTrue(pb.decidir(10.0, fr)["decisao"].startswith("SEGUE"))        # 10*.25*.87*180=391; pess=10*.16*.6*.729*180=126
        self.assertTrue(pb.decidir(1.0, fr)["decisao"].startswith("NAO_RODA"))      # 39 < 104
        self.assertTrue(pb.decidir(3.0, fr)["decisao"].startswith("ZONA_CINZENTA")) # 117 >= 104 > 38


class ExecutarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.lista = self.tmp / "lista.json"
        self.lista.write_text(json.dumps([{"trackedWalletAddress": W1, "name": "aloh1"},
                                          {"trackedWalletAddress": W2, "name": "dani2"}]))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _post(self, urls: list[str]):
        def post(url: str, corpo: bytes):
            urls.append(url)
            req = json.loads(corpo)
            if req["method"] == "getSignaturesForAddress":
                w = req["params"][0]
                sigs = [{"signature": f"{w[:4]}-{i}", "blockTime": T + i, "err": None} for i in range(3)]
                return 200, {"result": sigs + [{"signature": f"{w[:4]}-old", "blockTime": pb.CONGELAMENTO_TS - 10, "err": None}]}
            sig = req["params"][0]
            return 200, {"result": COMPRA_GRADUADA if sig.startswith(W1[:4]) else VENDA}
        return post

    def test_nao_abre_banco_nem_gt_e_mede_creditos(self) -> None:
        urls: list[str] = []
        rpc = pb.RpcMedido("https://rpc.exemplo.invalid/?api-key=SEGREDO", 50, intervalo_s=0.0, post=self._post(urls))
        with mock.patch.object(sqlite3, "connect", side_effect=AssertionError("abriu banco")), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("rede fora do RPC")):
            texto = pb.executar(rpc, self.lista, sol_usd=70.0, amostra=4, semente=1, max_paginas=1, agora=T + 86400)
        self.assertTrue(urls and all(u == "https://rpc.exemplo.invalid/?api-key=SEGREDO" for u in urls))
        self.assertNotIn("SEGREDO", texto)                      # chave nunca impressa
        self.assertNotIn("geckoterminal", texto.lower())
        self.assertEqual(set(rpc.chamadas), {"getSignaturesForAddress", "getTransaction"})
        self.assertEqual(rpc.creditos, 2 + 4)                   # 2 paginas + 4 tx
        self.assertIn("creditos gastos (contagem x tabela Helius): 6", texto)
        self.assertIn("DECISAO (regra B4):", texto)
        self.assertIn("f_compra", texto)

    def test_metodo_nao_autorizado_e_429(self) -> None:
        rpc = pb.RpcMedido("https://x.invalid", 10, intervalo_s=0.0, post=lambda u, c: (429, None))
        with self.assertRaises(ValueError):
            rpc.call("getAccountInfo", [])
        with self.assertRaises(pb.Abortar):
            rpc.call("getTransaction", ["s"])

    def test_teto_de_creditos(self) -> None:
        rpc = pb.RpcMedido("https://x.invalid", 1, intervalo_s=0.0, post=lambda u, c: (200, {"result": []}))
        rpc.call("getSignaturesForAddress", ["a", {}])
        with self.assertRaises(pb.Abortar):
            rpc.call("getSignaturesForAddress", ["b", {}])


if __name__ == "__main__":
    unittest.main()
