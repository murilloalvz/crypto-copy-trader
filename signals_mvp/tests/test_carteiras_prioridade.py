"""PEDIDO 2026-11-10 (autorizado, rodada 15, Parte 2): testes da correcao do RateLimited em
carteiras "pro" -- prioridade alta (posicao aberta, QUALQUER versao) usa o RPC compartilhado de
sempre; prioridade baixa (so fase runner/pullback) usa um RPC DEDICADO (se configurado); o orcamento
diario agora conta TENTATIVAS (sucesso+falha), nunca so sucessos. EXPLORATORIO/infra -- nunca altera
detector/sinal/parametros."""

from __future__ import annotations

import unittest
from typing import Any

from ..pos_runner.chain_adapter import HolderCheck
from ..pos_runner.detector import PHASE_RUNNER
from .test_pos_runner_live import LiveHarness, start_tracking


class CarteirasPrioridadeAltaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_posicao_aberta_v1_e_prioridade_alta(self) -> None:
        start_tracking(self.h)
        self.h.run_hours(17)
        pool = self.h.storage.pr1_signals()[0]["pool"]
        self.assertTrue(self.h.live._carteiras_prioridade_alta(pool))

    def test_sem_posicao_aberta_e_so_fase_nunca_e_prioridade_alta(self) -> None:
        start_tracking(self.h)
        pool = "POOL1"
        self.assertFalse(self.h.live._carteiras_prioridade_alta(pool))

    def test_posicao_aberta_v3_tambem_conta_como_prioridade_alta(self) -> None:
        start_tracking(self.h)
        pool = "POOL1"
        self.h.storage.pr3_insert_signal({
            "chain": "solana", "pool": pool, "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 0,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v3": "abc", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "aberto", "entry_price": 100.0, "stop": 80.0, "topo": 200.0,
            "s_suporte": 0.0,
        })
        self.assertTrue(self.h.live._carteiras_prioridade_alta(pool))


class CarteirasRpcDedicadoTests(unittest.TestCase):
    def test_sem_rpc_carteiras_cai_no_mesmo_adapter_de_sempre(self) -> None:
        h = LiveHarness()
        try:
            self.assertIs(h.live.adapter, h.live.adapter_carteiras)
        finally:
            h.close()

    def test_com_rpc_carteiras_sao_2_adapters_distintos(self) -> None:
        h = LiveHarness(rpc_carteiras=object(), carteiras_rpc_per_min=5.0)
        try:
            self.assertIsNot(h.live.adapter, h.live.adapter_carteiras)
        finally:
            h.close()

    def test_prioridade_alta_usa_o_compartilhado_baixa_usa_o_dedicado(self) -> None:
        h = LiveHarness(rpc_carteiras=object(), carteiras_rpc_per_min=5.0)
        try:
            chamadas = {"compartilhado": 0, "dedicado": 0}

            def holders_compartilhado(mint: str, excl: Any) -> HolderCheck:
                chamadas["compartilhado"] += 1
                return HolderCheck(top_holders=[])

            def holders_dedicado(mint: str, excl: Any) -> HolderCheck:
                chamadas["dedicado"] += 1
                return HolderCheck(top_holders=[])

            h.live.adapter.holders = holders_compartilhado
            h.live.adapter_carteiras.holders = holders_dedicado
            h.live.carteiras_max_chamadas_dia = 1000

            start_tracking(h)
            h.run_hours(17)   # chega na ENTRADA -- antes disso, so fase (RPC dedicado, prioridade
                              # baixa) -- depois da ENTRADA, posicao aberta (RPC compartilhado).
            pool = h.storage.pr1_signals()[0]["pool"]
            self.assertGreater(chamadas["compartilhado"], 0, "posicao aberta precisa usar o RPC compartilhado")
            self.assertGreater(chamadas["dedicado"], 0, "as horas ANTES da entrada (so fase) precisam "
                              "ter usado o RPC dedicado")
            dedicado_na_entrada = chamadas["dedicado"]

            # Depois que a posicao abre, NENHUMA chamada nova pode ir pro RPC dedicado -- so o
            # compartilhado, de agora em diante.
            compartilhado_antes = chamadas["compartilhado"]
            h.clock.advance(3600)
            h.tick()
            self.assertEqual(chamadas["dedicado"], dedicado_na_entrada,
                            "com posicao aberta, nenhuma chamada nova pode ir pro RPC dedicado")
            self.assertGreater(chamadas["compartilhado"], compartilhado_antes)

            # Agora sem posicao aberta, so fase "runner" (fake detector, sem rodar o replay inteiro de
            # novo) -- prioridade BAIXA, volta a usar o RPC dedicado.
            for s in h.storage.pr1_signals(status="aberto", pool=pool):
                h.storage.pr1_update_signal(s["id"], status="cancelado")
            for s in h.storage.pr2_signals(status="aberto", pool=pool):
                h.storage.pr2_update_signal(s["id"], status="cancelado")
            for s in h.storage.pr3_signals(status="aberto", pool=pool):
                h.storage.pr3_update_signal(s["id"], status="cancelado")
            h.live.dets_v1[(pool, "1h")].phase = PHASE_RUNNER   # muta o detector REAL, nunca o troca
            h.live._carteiras_horaria_ultima.pop(pool, None)
            compartilhado_antes = chamadas["compartilhado"]
            h.clock.advance(3600)
            h.tick()
            self.assertEqual(chamadas["compartilhado"], compartilhado_antes,
                            "sem posicao aberta, nenhuma chamada nova pode ir pro RPC compartilhado")
            self.assertGreater(chamadas["dedicado"], dedicado_na_entrada,
                              "so fase runner precisa voltar a usar o RPC dedicado")
        finally:
            h.close()


class CarteirasTentativaOrcamentoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_orcamento_conta_tentativas_mesmo_quando_todas_falham(self) -> None:
        start_tracking(self.h)
        self.h.live.carteiras_max_chamadas_dia = 3

        def holders_falha(mint: str, excl: Any) -> HolderCheck:
            return HolderCheck(tag="holders_indisponivel", detail={"motivo": "teste"})

        self.h.live.adapter.holders = holders_falha
        self.h.run_hours(17)
        inicio_do_dia = self.h.clock() - (self.h.clock() % 86400.0)
        tentativas = self.h.storage.pr_carteiras_tentativa_count_since(inicio_do_dia, "horaria")
        sucessos = self.h.storage.pr_carteiras_tentativa_count_since(inicio_do_dia, "horaria", sucesso=True)
        self.assertEqual(sucessos, 0, "todas as tentativas falharam de proposito")
        self.assertLessEqual(tentativas, self.h.live.carteiras_max_chamadas_dia,
                             "o orcamento precisa se autolimitar mesmo com 100% de falha")
        self.assertGreater(tentativas, 0)
        # ZERO sucessos nunca grava em pr_carteiras_snapshot (dado ausente nunca vira linha fabricada).
        self.assertEqual(
            [r for r in self.h.storage.pr_carteiras_snapshot_all() if r["momento"] == "horaria"], [])


if __name__ == "__main__":
    unittest.main()
