"""PEDIDO 2026-11-10 (autorizado, rodada 15, Parte 3): instrumentacao forward de carteiras "pro" para
a V3 -- no MOMENTO de cada sinal real ("sinal") e de K pools de controle/placebo ("placebo") do MESMO
ciclo, grava em `pr3_carteiras_sinal` quantas carteiras/pessoas "pro" estao entre os top holders e
qual % do supply, com cobertura explicita (nunca fabrica zero quando os holders estao indisponiveis).
EXPLORATORIO/infra -- nunca altera detector/sinal/parametros/criterios da V3."""

from __future__ import annotations

import types
import unittest

from ..pos_runner.chain_adapter import HolderCheck
from ..pos_runner.detector import PHASE_RUNNER
from .test_pos_runner_live import LiveHarness, start_tracking


class CapturaSinalRealTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_sinal_real_grava_cobertura_valida_e_cruza_lista_pro(self) -> None:
        self.h.live.adapter.holders = lambda mint, excl: HolderCheck(
            top_holders=[("ProWalletA", 5.0), ("Estranho", 1.0)])
        self.h.live._mapa_carteiras_pro = {"ProWalletA": "dani"}
        start_tracking(self.h)
        self.h.run_hours(17)
        sinal = self.h.storage.pr3_signals()[0]
        linhas = self.h.storage.pr3_carteiras_sinal_para_sinal(sinal["id"])
        sinais = [r for r in linhas if r["tipo"] == "sinal"]
        self.assertEqual(len(sinais), 1)
        row = sinais[0]
        self.assertEqual(row["pool"], sinal["pool"])
        self.assertEqual(row["cobertura_valida"], 1)
        self.assertEqual(row["n_carteiras_pro"], 1)
        self.assertEqual(row["n_pessoas_pro"], 1)
        self.assertAlmostEqual(row["pct_supply"], 5.0)

    def test_sem_rpc_marca_cobertura_invalida_nunca_fabrica_zero(self) -> None:
        # adapter.rpc e None por padrao no harness -- holders_indisponivel, nunca um 0 adivinhado.
        start_tracking(self.h)
        self.h.run_hours(17)
        sinal = self.h.storage.pr3_signals()[0]
        linhas = self.h.storage.pr3_carteiras_sinal_para_sinal(sinal["id"])
        sinais = [r for r in linhas if r["tipo"] == "sinal"]
        self.assertEqual(len(sinais), 1)
        self.assertEqual(sinais[0]["cobertura_valida"], 0)
        self.assertIsNone(sinais[0]["n_carteiras_pro"])
        self.assertIsNone(sinais[0]["n_pessoas_pro"])
        self.assertIsNone(sinais[0]["pct_supply"])

    def test_sem_carteiras_desliga_a_captura_forward(self) -> None:
        h = LiveHarness(sem_carteiras=True)
        try:
            h.live.adapter.holders = lambda mint, excl: HolderCheck(top_holders=[("ProWalletA", 5.0)])
            h.live._mapa_carteiras_pro = {"ProWalletA": "dani"}
            start_tracking(h)
            h.run_hours(17)
            self.assertEqual(h.storage.pr3_carteiras_sinal_all(), [])
        finally:
            h.close()

    def test_captura_nunca_consome_o_orcamento_da_coleta_horaria(self) -> None:
        # Parte 2: orcamento/`pr_carteiras_tentativa` e so da coleta horaria de baixa prioridade --
        # a captura forward da Parte 3 (evento raro, 1x por sinal V3) nunca entra nessa contagem.
        # Chama a captura DIRETO (fora de `run_hours`/`tick`, que tambem roda a coleta horaria por
        # conta propria) para isolar exatamente o que ESTA chamada grava.
        self.h.live.adapter.holders = lambda mint, excl: HolderCheck(top_holders=[])
        start_tracking(self.h)
        self.h.run_hours(17)
        sinal = self.h.storage.pr3_signals()[0]
        row = self.h.storage.pr_pool(sinal["pool"])
        antes = self.h.storage.pr_carteiras_tentativa_count_since(0.0)
        self.h.live._capturar_carteiras_sinal_v3(row, sinal["id"], "1h", self.h.clock())
        depois = self.h.storage.pr_carteiras_tentativa_count_since(0.0)
        self.assertEqual(depois, antes,
                         "a captura por sinal real nunca deveria contar no orcamento da coleta horaria")


class PoolsControleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def _fake_det(self, phase: str) -> types.SimpleNamespace:
        # Teste ISOLADO (nunca chama tick()/_refresh_core aqui, so `_carteiras_pools_controle`/
        # `_fase_label_v1` -- ambos so leem `.phase`, nunca chamam `.update()`), por isso um
        # SimpleNamespace e seguro aqui (ao contrario de um teste que avanca o relogio de verdade).
        return types.SimpleNamespace(phase=phase)

    def test_exclui_gatilho_fase_diferente_e_posicao_aberta_ordem_deterministica(self) -> None:
        self.h.live.dets_v1[("POOLX", "1h")] = self._fake_det(PHASE_RUNNER)
        self.h.live.dets_v1[("POOLB", "1h")] = self._fake_det(PHASE_RUNNER)
        self.h.live.dets_v1[("POOLA", "1h")] = self._fake_det(PHASE_RUNNER)
        self.h.live.dets_v1[("POOLD", "1h")] = self._fake_det("sem_fase")   # fase diferente -- fora
        self.h.live.dets_v1[("POOLC", "1h")] = self._fake_det(PHASE_RUNNER)
        self.h.storage.pr3_insert_signal({
            "chain": "solana", "pool": "POOLC", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 0,
            "mint": "MINTC", "symbol": "CCC", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v3": "abc", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "aberto", "entry_price": 1.0, "stop": 0.8, "topo": 2.0,
            "s_suporte": 0.0,
        })   # POOLC tem posicao aberta -- nunca entra no placebo
        candidatos = self.h.live._carteiras_pools_controle("POOLX", "1h", 5)
        self.assertEqual(candidatos, ["POOLA", "POOLB"])

    def test_k_limita_a_quantidade(self) -> None:
        self.h.live.dets_v1[("POOLX", "1h")] = self._fake_det(PHASE_RUNNER)
        for nome in ("POOLA", "POOLB", "POOLC"):
            self.h.live.dets_v1[(nome, "1h")] = self._fake_det(PHASE_RUNNER)
        candidatos = self.h.live._carteiras_pools_controle("POOLX", "1h", 1)
        self.assertEqual(candidatos, ["POOLA"])

    def test_tf_diferente_nunca_entra(self) -> None:
        self.h.live.dets_v1[("POOLX", "1h")] = self._fake_det(PHASE_RUNNER)
        self.h.live.dets_v1[("POOLA", "4h")] = self._fake_det(PHASE_RUNNER)   # outro tf -- fora
        candidatos = self.h.live._carteiras_pools_controle("POOLX", "1h", 5)
        self.assertEqual(candidatos, [])


class CapturaPlaceboTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_grava_placebo_para_cada_pool_de_controle_elegivel(self) -> None:
        chamadas: dict[str, int] = {}

        def holders_fn(mint: str, excl) -> HolderCheck:
            chamadas[mint] = chamadas.get(mint, 0) + 1
            if mint == "MINTCONTROLE":
                return HolderCheck(top_holders=[("ProWalletA", 3.0)])
            return HolderCheck(top_holders=[])

        self.h.live.adapter.holders = holders_fn
        self.h.live._mapa_carteiras_pro = {"ProWalletA": "dani"}
        start_tracking(self.h)
        self.h.run_hours(17)
        sinal = self.h.storage.pr3_signals()[0]
        pool, tf = sinal["pool"], "1h"

        # Pool de controle: MESMA fase que o pool-gatilho tinha no instante do sinal, sem posicao aberta.
        fase_no_sinal = self.h.live._fase_label_v1(pool, tf)
        self.h.live.dets_v1[("POOLCONTROLE", tf)] = types.SimpleNamespace(phase=self.h.live.dets_v1[(pool, tf)].phase)
        self.assertEqual(self.h.live._fase_label_v1("POOLCONTROLE", tf), fase_no_sinal)
        self.h.storage.pr_upsert_pool("POOLCONTROLE", status="ativo", mint="MINTCONTROLE", launchpad="pumpfun")

        row = self.h.storage.pr_pool(pool)
        chamadas_antes = dict(chamadas)
        self.h.live._capturar_carteiras_sinal_v3(row, sinal["id"], tf, self.h.clock())

        linhas = self.h.storage.pr3_carteiras_sinal_para_sinal(sinal["id"])
        placebo = [r for r in linhas if r["tipo"] == "placebo" and r["pool"] == "POOLCONTROLE"]
        self.assertEqual(len(placebo), 1)
        self.assertEqual(placebo[0]["cobertura_valida"], 1)
        self.assertEqual(placebo[0]["n_carteiras_pro"], 1)
        self.assertEqual(placebo[0]["n_pessoas_pro"], 1)
        self.assertAlmostEqual(placebo[0]["pct_supply"], 3.0)
        self.assertEqual(chamadas.get("MINTCONTROLE", 0), chamadas_antes.get("MINTCONTROLE", 0) + 1)

    def test_pool_de_controle_sem_mint_e_pulado_sem_quebrar(self) -> None:
        self.h.live.adapter.holders = lambda mint, excl: HolderCheck(top_holders=[])
        start_tracking(self.h)
        self.h.run_hours(17)
        sinal = self.h.storage.pr3_signals()[0]
        pool, tf = sinal["pool"], "1h"
        self.h.live.dets_v1[("POOLSEMMINT", tf)] = types.SimpleNamespace(phase=self.h.live.dets_v1[(pool, tf)].phase)
        self.h.storage.pr_upsert_pool("POOLSEMMINT", status="ativo")   # sem mint
        row = self.h.storage.pr_pool(pool)
        # nunca levanta excecao -- so pula o candidato sem mint.
        self.h.live._capturar_carteiras_sinal_v3(row, sinal["id"], tf, self.h.clock())
        linhas = self.h.storage.pr3_carteiras_sinal_para_sinal(sinal["id"])
        self.assertEqual([r for r in linhas if r["pool"] == "POOLSEMMINT"], [])


if __name__ == "__main__":
    unittest.main()
