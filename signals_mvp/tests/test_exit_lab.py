"""PEDIDO 2026-11-03 (Passo 0e, item 3): testes das 4 variantes de saida (`scripts/exit_lab.py`) com
candles sinteticos deterministicos -- verifica a MECANICA de cada variante (timing de decisao/
execucao, pernas parciais, ratchet causal do stop), nunca a precisao fina do custo (ja testada em
`test_costs.py`)."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.candles import Bar
from ..pos_runner.costs import CostModel
from ..pos_runner.params_v1 import load_params_v1
from ..storage import Storage
from ..scripts import exit_lab


def _bars(spec: list[tuple[float, float, float, float]], ts0: int = 1_000, step: int = 3_600) -> list[Bar]:
    return [Bar(ts0 + i * step, o, h, l, c, 0.0, False) for i, (o, h, l, c) in enumerate(spec)]


class VarianteBTests(unittest.TestCase):
    def test_stop_so_sobe_para_o_breakeven_depois_de_1x_a_altura_da_caixa(self) -> None:
        bars = _bars([
            (100, 108, 99, 107),    # max_high=108, 108-100=8 < altura(10) -- nao move ainda
            (107, 112, 105, 110),   # max_high=112, 112-100=12 >= 10 -- move o stop p/ breakeven (100) DAQUI PRA FRENTE
            (110, 111, 99, 101),    # low=99 <= stop(100) agora -- dispara no breakeven
        ])
        costs = CostModel()
        r = exit_lab._variante_b(bars, 0, entry=100.0, stop0=80.0, s=85.0, r=95.0, costs=costs,
                                 dex="desconhecido", l_bc=None)
        self.assertEqual(r.status, "fechado")
        self.assertEqual(r.reason, "stop_breakeven")
        self.assertEqual(r.bars_held, 3)
        self.assertIsNotNone(r.net_ret)
        self.assertGreater(r.net_ret, -0.10)   # perto do breakeven, so o custo tira um pouco

    def test_sem_altura_de_caixa_conhecida_nunca_move_o_stop(self) -> None:
        bars = _bars([
            (100, 200, 99, 199),   # alta enorme -- sem S/R nao ha "altura" pra comparar
            (199, 199, 79, 80),    # low=79 <= stop original (80) -- so o stop ORIGINAL dispara
        ])
        costs = CostModel()
        r = exit_lab._variante_b(bars, 0, entry=100.0, stop0=80.0, s=None, r=None, costs=costs,
                                 dex="desconhecido", l_bc=None)
        self.assertEqual(r.reason, "stop")   # nunca "stop_breakeven": sem altura, stop nunca moveu


class VarianteCTests(unittest.TestCase):
    def test_sai_no_1o_fechamento_abaixo_do_teto_executado_no_open_seguinte(self) -> None:
        bars = _bars([
            (100, 102, 99, 101),   # fecha acima do teto (R=95) -- continua
            (101, 103, 98, 94),    # fecha abaixo do teto (94<95) -- decide AQUI, executa no open seguinte
            (90, 91, 89, 90),      # execucao: preco = open deste candle = 90
        ])
        costs = CostModel()
        r = exit_lab._variante_c(bars, 0, entry=100.0, stop=80.0, r=95.0, costs=costs, dex="desconhecido", l_bc=None)
        self.assertEqual(r.status, "fechado")
        self.assertEqual(r.reason, "fechamento_1h_abaixo_do_teto")
        self.assertEqual(r.bars_held, 3)
        self.assertLess(r.net_ret, 0.0)   # saiu a 90 de uma entrada a 100 -- perda, mesmo sem custo

    def test_stop_original_tem_prioridade_sobre_o_fechamento_abaixo_do_teto(self) -> None:
        bars = _bars([
            (100, 101, 79, 94),   # low toca o stop (80) NO MESMO candle que fecha sob o teto -- stop decide
        ])
        costs = CostModel()
        r = exit_lab._variante_c(bars, 0, entry=100.0, stop=80.0, r=95.0, costs=costs, dex="desconhecido", l_bc=None)
        self.assertEqual(r.reason, "stop")


class VarianteDTests(unittest.TestCase):
    def test_30pct_no_topo_mais_70pct_no_stop_trailing(self) -> None:
        bars = _bars([
            (100, 110, 95, 108),    # sem toque no topo (120) ainda
            (108, 115, 104, 112),   # sem toque ainda
            (112, 121, 108, 119),   # toca o topo (121>=120) -- decide os 30% AQUI, executa no open seguinte
            (119, 122, 117, 120),   # executa os 30% a 119 (open deste candle); continua com os 70%
            (120, 123, 100, 118),
            (118, 119, 70, 75),     # low(70) <= stop original (80) -- dispara os 70% restantes
        ])
        costs = CostModel()
        params = load_params_v1()
        r = exit_lab._variante_d(bars, 0, entry=100.0, stop0=80.0, topo=120.0, params=params, costs=costs,
                                 dex="desconhecido", l_bc=None)
        self.assertEqual(r.status, "fechado")
        self.assertEqual(r.reason, "trailing_mini_caixa")
        self.assertEqual(r.bars_held, 6)
        self.assertIsNotNone(r.net_ret)
        self.assertLess(r.net_ret, 0.0)   # 30% a 119 (+19%) e 70% a 80 (-20%) -- liquido negativo

    def test_sem_topo_conhecido_nunca_faz_a_saida_parcial(self) -> None:
        bars = _bars([
            (100, 200, 99, 199),   # alta enorme, mas sem TOPO nao ha "toque" pra avaliar
            (199, 199, 79, 80),    # so o stop original dispara, 100% de uma vez
        ])
        costs = CostModel()
        params = load_params_v1()
        r = exit_lab._variante_d(bars, 0, entry=100.0, stop0=80.0, topo=None, params=params, costs=costs,
                                 dex="desconhecido", l_bc=None)
        self.assertEqual(r.reason, "stop")
        self.assertEqual(r.bars_held, 2)


class ExecutarSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="exit_lab_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha(self) -> None:
        texto = exit_lab.executar(self.storage.paths.db)
        self.assertIn(exit_lab.AVISO, texto)
        self.assertNotIn("Traceback", texto)

    def test_sinal_limpo_v1_com_bars_entra_no_relatorio(self) -> None:
        signal_id = self.storage.pr1_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]",
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
            "entry_price": 100.0, "stop": 80.0, "topo": 120.0, "s_suporte": 85.0, "r_resistencia": 95.0,
            "reason": "stop",
        })
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h", mint="MINT1", symbol="CAT",
            t_entrada=4_600.0, preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0, fonte_candle="gt",
            mfe_r=1.0, mfe_h=1.0, fechado=1,
        )
        self.storage.pr_append_bars("POOL1", "1h", [
            (1_000, 100.0, 101.0, 99.0, 100.0, 0.0, 0),
            (4_600, 100.0, 108.0, 95.0, 102.0, 0.0, 0),
            (8_200, 102.0, 103.0, 70.0, 75.0, 0.0, 0),
        ])
        texto = exit_lab.executar(self.storage.paths.db)
        self.assertIn("CAT", texto)
        self.assertNotIn("Traceback", texto)


class LinhasRetroAdmitidoTests(unittest.TestCase):
    """PEDIDO 2026-11-03: a secao da coorte retro (so o subconjunto `admitido_apos_congelamento`
    do lote 1) nunca crasha mesmo sem a tabela `pr_retro_candidatos` (bancos sem congelamento) ou
    sem nenhum candidato admitido (`pr_pools.added_ts` ausente -- fora do alcance offline)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="exit_lab_retro_"))
        storage = Storage(make_paths(self.tmp))
        self.db_path = storage.paths.db
        storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sem_congelamento_lote1_devolve_vazio(self) -> None:
        linhas, n_fora = exit_lab.linhas_retro_admitido(self.db_path)
        self.assertEqual(linhas, [])
        self.assertEqual(n_fora, 0)

    def test_candidato_congelado_mas_nunca_admitido_fica_fora_do_alcance(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "CREATE TABLE IF NOT EXISTS pr_retro_candidatos (pool TEXT PRIMARY KEY, mint TEXT, symbol TEXT, "
            "launchpad TEXT, l_bc REAL, grad_ts REAL, criado_ts REAL, mc_found REAL, lista_hash TEXT NOT NULL, "
            "congelado_em REAL NOT NULL)"
        )
        con.execute(
            "INSERT INTO pr_retro_candidatos (pool, mint, symbol, launchpad, lista_hash, congelado_em) "
            "VALUES ('POOLX', 'MINTX', 'CAT', 'pumpfun', 'hash123', 0.0)"
        )
        con.execute(
            "INSERT INTO pr_pools (pool, symbol, status) VALUES ('POOLX', 'CAT', 'rejeitado')"
        )
        con.commit()
        con.close()
        linhas, n_fora = exit_lab.linhas_retro_admitido(self.db_path)
        self.assertEqual(linhas, [])
        self.assertEqual(n_fora, 1)


if __name__ == "__main__":
    unittest.main()
