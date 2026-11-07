"""PEDIDO 2026-11-03 (Passo 0e, item 3): testes das 4 variantes de saida (`scripts/exit_lab.py`) com
candles sinteticos deterministicos -- verifica a MECANICA de cada variante (timing de decisao/
execucao, pernas parciais, ratchet causal do stop), nunca a precisao fina do custo (ja testada em
`test_costs.py`)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional

from ..config import make_paths
from ..pos_runner.candles import Bar
from ..pos_runner.costs import CostModel
from ..pos_runner.params_v1 import load_params_v1
from ..storage import Storage
from ..scripts import exit_lab
from .test_pos_runner_v1 import CREATED, GRAD, L_BC, textbook_v1


def _bars(spec: list[tuple[float, float, float, float]], ts0: int = 1_000, step: int = 3_600) -> list[Bar]:
    return [Bar(ts0 + i * step, o, h, l, c, 0.0, False) for i, (o, h, l, c) in enumerate(spec)]


def _bars_vol(spec: list[tuple[float, float, float, float, float]], ts0: int = 1_000,
             step: int = 3_600) -> list[Bar]:
    # PEDIDO 2026-11-05 (item 1): `_bars` tem volume=0.0 fixo (todo candle fica `candle_corrompido_
    # provavel`) -- a marcacao a mercado precisa de volume>0 pra achar um candle limpo pra marcar.
    return [Bar(ts0 + i * step, o, h, l, c, v, False) for i, (o, h, l, c, v) in enumerate(spec)]


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


class MarcacaoAMercadoTests(unittest.TestCase):
    """PEDIDO 2026-11-05 (item 1): corrige o vies de selecao de `_mesma_amostra` -- em_aberto nunca
    mais e so excluido; o restante aberto e valorizado no ultimo candle LIMPO."""

    def test_variante_b_em_aberto_e_valorizada_no_ultimo_close_limpo(self) -> None:
        bars = _bars_vol([
            (100, 105, 95, 102, 100.0),   # nunca toca o stop (80) nem a altura da caixa
            (102, 108, 98, 106, 100.0),
            (106, 110, 101, 109, 100.0),  # ULTIMO candle, limpo -- marca aqui (close=109, +9%)
        ])
        costs = CostModel()
        r = exit_lab._variante_b(bars, 0, entry=100.0, stop0=80.0, s=85.0, r=200.0, costs=costs,
                                 dex="desconhecido", l_bc=None)
        self.assertEqual(r.status, "em_aberto")
        self.assertIsNone(r.net_ret)              # visao (i): nunca inventa um fechamento
        self.assertTrue(r.marcado_a_mercado)
        self.assertIsNotNone(r.net_ret_marcado)
        self.assertGreater(r.net_ret_marcado, 0.0)   # marcado no close 109 (+9% bruto) -- positivo
        self.assertEqual(r.candle_marca_ts, bars[-1].ts)

    def test_marcacao_pula_candle_corrompido_e_usa_o_limpo_anterior(self) -> None:
        # sem altura de caixa (s=r=None) -- o stop NUNCA move de 80, e nenhum low aqui toca 80.
        bars = _bars_vol([
            (100, 105, 95, 102, 100.0),
            (102, 110, 98, 106, 0.0),    # volume=0 -- corrompido, NUNCA marca aqui
            (106, 108, 101, 107, 100.0),  # limpo -- e o ultimo LIMPO depois que o 4o candle (abaixo)
        ])
        # 4o candle tambem corrompido (volume=0) -- a busca precisa voltar 2 candles, nao so 1.
        bars_corrompidos_no_fim = bars + [exit_lab.Bar(bars[-1].ts + 3_600, 107, 112, 100, 105, 0.0, False)]
        costs = CostModel()
        r = exit_lab._variante_b(bars_corrompidos_no_fim, 0, entry=100.0, stop0=80.0, s=None, r=None,
                                 costs=costs, dex="desconhecido", l_bc=None)
        self.assertEqual(r.status, "em_aberto")
        self.assertTrue(r.marcado_a_mercado)
        self.assertEqual(r.candle_marca_ts, bars[2].ts)   # o 3o candle (close=107), nunca o corrompido

    def test_sem_nenhum_candle_limpo_na_serie_nunca_marca(self) -> None:
        bars = _bars([(100, 105, 95, 102), (102, 108, 98, 106)])   # _bars = volume 0.0 em todos
        costs = CostModel()
        r = exit_lab._variante_b(bars, 0, entry=100.0, stop0=80.0, s=85.0, r=200.0, costs=costs,
                                 dex="desconhecido", l_bc=None)
        self.assertFalse(r.marcado_a_mercado)
        self.assertIsNone(r.net_ret_marcado)

    def test_variante_d_marca_so_a_fracao_ainda_aberta_mantendo_a_perna_ja_realizada(self) -> None:
        bars = _bars_vol([
            (100, 110, 95, 108, 100.0),
            (108, 115, 104, 112, 100.0),
            (112, 121, 108, 119, 100.0),   # toca o topo (121>=120) -- decide os 30% aqui
            (119, 122, 117, 120, 100.0),   # executa os 30% a 119 (open); restam 70% abertos
            (120, 123, 115, 121, 100.0),   # ULTIMO candle limpo -- marca os 70% restantes aqui (close=121)
        ])
        costs = CostModel()
        params = load_params_v1()
        r = exit_lab._variante_d(bars, 0, entry=100.0, stop0=80.0, topo=120.0, params=params, costs=costs,
                                 dex="desconhecido", l_bc=None)
        self.assertEqual(r.status, "em_aberto")
        self.assertTrue(r.marcado_a_mercado)
        # 30% ja realizado a 119 (+19%) + 70% marcado a 121 (+21%) -- os dois positivos, liquido positivo
        self.assertGreater(r.net_ret_marcado, 0.0)


class VisaoDuplaSemVieseDeSelecaoTests(unittest.TestCase):
    """PEDIDO 2026-11-05 (item 1): reproduz o caso relatado (MOGZ/PEAK em_aberto na A, excluidos da
    "mesma amostra" de hoje) -- a visao (ii) precisa INCLUIR esse trade, a (i) continua sem ele."""

    def test_trade_em_aberto_na_a_e_excluido_da_visao_i_mas_entra_na_visao_ii(self) -> None:
        linhas = [
            _linha_variantes("MOGZ", "v3", "v1v2v3", {
                # A em_aberto (candidato a vencedor ainda correndo), B/C/D ja resolvidas.
                "B_breakeven_1x_caixa": (5.0, 0.25), "C_fechamento_1h_sob_teto": (8.0, 0.4),
                "D_30pct_topo_trailing": (12.0, 0.6),
            }, marcados={"A_atual": (40.0, 2.0)}),   # A marcada a mercado: +40% (ainda correndo, forte)
        ]
        so_resolvidos = exit_lab._mesma_amostra(linhas)
        todos = exit_lab._todos_valorizados(linhas)
        self.assertEqual(so_resolvidos, [])          # visao (i): MOGZ EXCLUIDO -- vies de selecao
        self.assertEqual(len(todos), 1)               # visao (ii): MOGZ ENTRA, valorizado a mercado
        self.assertAlmostEqual(todos[0]["A_atual"]["pct_marcado"], 40.0)

    def test_formatar_bloco_mostra_as_2_visoes_e_a_contagem_de_marcados(self) -> None:
        linhas = [
            _linha_variantes("MOGZ", "v1", "v1v2v3",
                            {"B_breakeven_1x_caixa": (5.0, 0.25), "C_fechamento_1h_sob_teto": (8.0, 0.4),
                             "D_30pct_topo_trailing": (12.0, 0.6)},
                            marcados={"A_atual": (40.0, 2.0)}),
        ]
        texto = exit_lab.formatar(linhas, {}, {}, 0)
        self.assertIn("(i) SO RESOLVIDOS", texto)
        self.assertIn("(ii) TODOS OS TRADES", texto)
        self.assertIn("valorizados a mercado", texto)


class EstatisticasExploratoriasVisaoIITests(unittest.TestCase):
    """PEDIDO 2026-11-05 (PARTE 3, item 2): mediana de R, fracao do R total dos 3 maiores trades e IC
    bootstrap (por token, seed fixa) -- SO na visao (ii), nunca na (i); nunca escolhe variante."""

    def test_fracao_top3_soma_os_3_maiores_sobre_o_total(self) -> None:
        # top3 = 10+8+6=24; total = 10+8+6+1-3 = 22; 24/22 ~= +109%.
        txt = exit_lab._fracao_top3([10.0, 8.0, 6.0, 1.0, -3.0])
        self.assertIsNotNone(txt)
        self.assertIn("+109%", txt)

    def test_fracao_top3_e_s_d_quando_soma_total_e_quase_zero(self) -> None:
        self.assertIsNone(exit_lab._fracao_top3([5.0, -5.0]))

    def test_bootstrap_ic_e_none_sem_nenhum_r_na_variante(self) -> None:
        linhas = [_linha_variantes("CAT", "v1", "v1v2v3", {"B_breakeven_1x_caixa": (5.0, 0.25)})]
        self.assertIsNone(exit_lab._bootstrap_ic_por_token(linhas, "A_atual", "r"))

    def test_bootstrap_ic_e_deterministico_com_a_mesma_seed(self) -> None:
        linhas = [
            _linha_variantes("CAT", "v1", "v1v2v3", {"A_atual": (10.0, 1.0)}),
            _linha_variantes("DOG", "v1", "v1v2v3", {"A_atual": (20.0, 2.0)}),
            _linha_variantes("ELK", "v1", "v1v2v3", {"A_atual": (-5.0, -0.5)}),
        ]
        ic1 = exit_lab._bootstrap_ic_por_token(linhas, "A_atual", "r")
        ic2 = exit_lab._bootstrap_ic_por_token(linhas, "A_atual", "r")
        self.assertIsNotNone(ic1)
        self.assertEqual(ic1, ic2, "mesma seed/entrada -- mesmo IC, sempre reproduzivel")
        self.assertLessEqual(ic1[0], ic1[1])

    def test_visao_ii_mostra_as_3_estatisticas_e_a_i_nunca_mostra(self) -> None:
        linhas = [
            _linha_variantes("CAT", "v1", "v1v2v3",
                            {"B_breakeven_1x_caixa": (5.0, 0.25), "C_fechamento_1h_sob_teto": (8.0, 0.4),
                             "D_30pct_topo_trailing": (12.0, 0.6)},
                            marcados={"A_atual": (40.0, 2.0)}),
            _linha_variantes("DOG", "v1", "v1v2v3", {
                "A_atual": (20.0, 1.0), "B_breakeven_1x_caixa": (15.0, 0.75),
                "C_fechamento_1h_sob_teto": (10.0, 0.5), "D_30pct_topo_trailing": (10.0, 0.5)}),
        ]
        texto = exit_lab.formatar(linhas, {}, {}, 0)
        self.assertIn("EXPLORATORIO (n pequeno, NUNCA decide H1/futilidade/variante vencedora)", texto)
        self.assertIn("mediana R=", texto)
        self.assertIn("IC90% bootstrap=", texto)
        bloco_v1 = texto.split("## ao_vivo / V1")[1].split("## ao_vivo / V2")[0]
        visao_i, visao_ii = bloco_v1.split("(ii) TODOS OS TRADES")
        self.assertNotIn("mediana R=", visao_i)
        self.assertIn("mediana R=", visao_ii)


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

    def test_candidato_admitido_com_historico_real_encontra_a_entrada_corrigido_2026_11_04(self) -> None:
        """CORRECAO 2026-11-04: a versao anterior passava `criado_ts=None` pro `DetectorV1` -- sem
        isso, `in_age_window()` sempre falha e TODA zona emite FORA_DA_IDADE em vez de ENTRADA, e esta
        secao NUNCA achava nenhum sinal, mesmo com historico real que `avaliar_candidatos_retro.py`
        (que sempre passa `criado_ts`) acharia. `criado_ts` agora vem da propria linha congelada."""
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "CREATE TABLE IF NOT EXISTS pr_retro_candidatos (pool TEXT PRIMARY KEY, mint TEXT, symbol TEXT, "
            "launchpad TEXT, l_bc REAL, grad_ts REAL, criado_ts REAL, mc_found REAL, lista_hash TEXT NOT NULL, "
            "congelado_em REAL NOT NULL)"
        )
        con.execute(
            "INSERT INTO pr_retro_candidatos (pool, mint, symbol, launchpad, grad_ts, criado_ts, lista_hash, "
            "congelado_em) VALUES ('POOL1', 'MINT1', 'CAT', 'pumpfun', ?, ?, 'hash123', 0.0)",
            (GRAD, CREATED),
        )
        bars = textbook_v1().bars
        added_ts = max(b.ts for b in bars) + 7_200.0
        con.execute(
            "INSERT INTO pr_pools (pool, symbol, status, l_bc, grad_ts, added_ts) VALUES (?,?,?,?,?,?)",
            ("POOL1", "CAT", "ativo", L_BC, GRAD, added_ts),
        )
        con.executemany(
            "INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES ('POOL1','1h',?,?,?,?,?,?,?)",
            [(b.ts, b.open, b.high, b.low, b.close, b.volume, int(b.filled)) for b in bars],
        )
        con.commit()
        con.close()
        linhas, n_fora = exit_lab.linhas_retro_admitido(self.db_path)
        self.assertEqual(n_fora, 0)
        self.assertGreaterEqual(len(linhas), 1, "com criado_ts correto, a ENTRADA real precisa aparecer")
        for l in linhas:
            self.assertEqual(l["origem"], "retro")


class ResumoPorTokenTests(unittest.TestCase):
    def test_agrega_media_de_pct_e_r_por_token_entre_origens_diferentes(self) -> None:
        linhas = [
            {"token": "CAT", "versao": "v1", "origem": "v1v2v3", "risco_pct": 20.0,
             "A_atual": {"status": "fechado", "pct": 10.0, "r": 0.5, "motivo": "stop"},
             "B_breakeven_1x_caixa": {"status": "fechado", "pct": None, "r": None, "motivo": "s/d"},
             "C_fechamento_1h_sob_teto": {"status": "fechado", "pct": None, "r": None, "motivo": "s/d"},
             "D_30pct_topo_trailing": {"status": "fechado", "pct": None, "r": None, "motivo": "s/d"}},
            {"token": "CAT", "versao": "v3", "origem": "v3_replay", "risco_pct": 20.0,
             "A_atual": {"status": "fechado", "pct": 30.0, "r": 1.5, "motivo": "stop"},
             "B_breakeven_1x_caixa": {"status": "fechado", "pct": None, "r": None, "motivo": "s/d"},
             "C_fechamento_1h_sob_teto": {"status": "fechado", "pct": None, "r": None, "motivo": "s/d"},
             "D_30pct_topo_trailing": {"status": "fechado", "pct": None, "r": None, "motivo": "s/d"}},
        ]
        resumo = exit_lab.resumo_por_token(linhas)
        self.assertEqual(len(resumo), 1)
        self.assertEqual(resumo[0]["token"], "CAT")
        self.assertEqual(resumo[0]["n"], 2)
        self.assertAlmostEqual(resumo[0]["A_atual"]["pct_medio"], 20.0)
        self.assertAlmostEqual(resumo[0]["A_atual"]["r_medio"], 1.0)
        self.assertEqual(resumo[0]["A_atual"]["n"], 2)


class LinhasV3ReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="exit_lab_v3replay_"))
        storage = Storage(make_paths(self.tmp))
        self.db_path = storage.paths.db
        storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_replay_v3_sobre_pool_admitido_real_gera_linhas_com_as_4_variantes(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "INSERT INTO pr_pools (pool, symbol, status, l_bc, grad_ts, info) VALUES (?,?,?,?,?,?)",
            ("POOL1", "CAT", "ativo", L_BC, GRAD, json.dumps({"criado_ts": CREATED})),
        )
        bars = textbook_v1().bars
        con.executemany(
            "INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES ('POOL1','1h',?,?,?,?,?,?,?)",
            [(b.ts, b.open, b.high, b.low, b.close, b.volume, int(b.filled)) for b in bars],
        )
        con.commit()
        con.close()
        linhas = exit_lab.linhas_v3_replay_pools_admitidos(self.db_path)
        self.assertGreaterEqual(len(linhas), 1)
        for l in linhas:
            self.assertEqual(l["versao"], "v3")
            self.assertEqual(l["origem"], "v3_replay")
            for nome in exit_lab.VARIANTES:
                self.assertIn(nome, l)

    def test_integrado_no_relatorio_final(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "INSERT INTO pr_pools (pool, symbol, status, l_bc, grad_ts, info) VALUES (?,?,?,?,?,?)",
            ("POOL1", "CAT", "ativo", L_BC, GRAD, json.dumps({"criado_ts": CREATED})),
        )
        bars = textbook_v1().bars
        con.executemany(
            "INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES ('POOL1','1h',?,?,?,?,?,?,?)",
            [(b.ts, b.open, b.high, b.low, b.close, b.volume, int(b.filled)) for b in bars],
        )
        con.commit()
        con.close()
        texto = exit_lab.executar(self.db_path)
        self.assertIn("## replay_v3 (EXPLORATORIO", texto)
        self.assertIn("MESMA amostra", texto)
        self.assertIn("CAT", texto)


def _linha_variantes(token: str, versao: str, origem: str,
                     resultados: dict[str, Optional[tuple[float, float]]],
                     marcados: Optional[dict[str, tuple[float, float]]] = None) -> dict[str, Any]:
    """PEDIDO 2026-11-05 (PARTE 2/item 1): helper minimo -- `resultados[nome]` e `(pct, r)` ou ausente
    (em_aberto, nenhum resultado definido para essa variante). `marcados[nome]` (opcional) e
    `(pct_marcado, r_marcado)` pra testar a visao (ii) especificamente quando em_aberto; se ausente,
    em_aberto fica sem marcacao (`pct_marcado=None`) -- MESMO fallback de `_marcar_a_mercado` sem
    candle limpo."""
    linha: dict[str, Any] = {"token": token, "versao": versao, "origem": origem, "risco_pct": 20.0}
    for nome in exit_lab.VARIANTES:
        par = resultados.get(nome)
        marcado = (marcados or {}).get(nome)
        if par is None:
            if marcado is None:
                linha[nome] = {"status": "em_aberto", "pct": None, "r": None, "motivo": "",
                               "pct_marcado": None, "r_marcado": None, "marcado_a_mercado": False}
            else:
                pct_m, r_m = marcado
                linha[nome] = {"status": "em_aberto", "pct": None, "r": None, "motivo": "",
                               "pct_marcado": pct_m, "r_marcado": r_m, "marcado_a_mercado": True}
        else:
            pct, r = par
            linha[nome] = {"status": "fechado", "pct": pct, "r": r, "motivo": "stop",
                           "pct_marcado": pct, "r_marcado": r, "marcado_a_mercado": False}
    return linha


class MesmaAmostraTests(unittest.TestCase):
    def test_so_passam_sinais_com_resultado_definido_nas_4_variantes(self) -> None:
        # PEDIDO 2026-11-05 (PARTE 2a): CAT tem as 4 definidas; DOG so tem A e B (C/D em_aberto) --
        # DOG nunca entra na mesma amostra, mesmo contribuindo pro N "cru" de A/B.
        linhas = [
            _linha_variantes("CAT", "v1", "v1v2v3", {
                "A_atual": (10.0, 0.5), "B_breakeven_1x_caixa": (5.0, 0.25),
                "C_fechamento_1h_sob_teto": (8.0, 0.4), "D_30pct_topo_trailing": (12.0, 0.6)}),
            _linha_variantes("DOG", "v1", "v1v2v3", {
                "A_atual": (20.0, 1.0), "B_breakeven_1x_caixa": (15.0, 0.75)}),
        ]
        comum = exit_lab._mesma_amostra(linhas)
        self.assertEqual(len(comum), 1)
        self.assertEqual(comum[0]["token"], "CAT")

    def test_amostra_vazia_quando_nenhum_sinal_tem_as_4_definidas(self) -> None:
        linhas = [_linha_variantes("CAT", "v1", "v1v2v3", {"A_atual": (10.0, 0.5)})]
        self.assertEqual(exit_lab._mesma_amostra(linhas), [])


class MediaEntreTokensTests(unittest.TestCase):
    def test_token_com_muitos_sinais_nao_pesa_mais_que_token_com_1(self) -> None:
        # PEDIDO 2026-11-05 (PARTE 2b): PEAK tem 3 sinais (+30% cada), BIRD tem 1 (-10%) -- a media
        # POR SINAL seria dominada por PEAK (+20% no geral); a media ENTRE TOKENS da peso 1 a cada
        # token: (30 + (-10)) / 2 = +10%, nunca +20%.
        linhas = [_linha_variantes("PEAK", "v1", "v1v2v3", {"A_atual": (30.0, 1.0)}) for _ in range(3)]
        linhas.append(_linha_variantes("BIRD", "v1", "v1v2v3", {"A_atual": (-10.0, -0.5)}))
        resumo_tokens = exit_lab.resumo_por_token(linhas)
        mt = exit_lab.media_entre_tokens(resumo_tokens)
        self.assertAlmostEqual(mt["A_atual"]["pct_medio_entre_tokens"], 10.0)
        self.assertEqual(mt["A_atual"]["n_tokens"], 2)
        self.assertEqual(mt["A_atual"]["n_tokens_positivos"], 1)   # so PEAK (+30%); BIRD e negativo

    def test_variante_sem_nenhum_token_com_media_valida_fica_s_d(self) -> None:
        linhas = [_linha_variantes("CAT", "v1", "v1v2v3", {"A_atual": (10.0, 0.5)})]
        resumo_tokens = exit_lab.resumo_por_token(linhas)
        mt = exit_lab.media_entre_tokens(resumo_tokens)
        self.assertIsNone(mt["B_breakeven_1x_caixa"]["pct_medio_entre_tokens"])
        self.assertEqual(mt["B_breakeven_1x_caixa"]["n_tokens"], 0)


class FormatarOrigemSeparadaTests(unittest.TestCase):
    def test_versao_compartilhada_nunca_mistura_ao_vivo_com_retro_ou_replay(self) -> None:
        # PEDIDO 2026-11-05 (PARTE 2c, bug relatado): retro_lote1/replay_v3 reusam o MESMO rotulo de
        # `versao` ("v1"/"v2"/"v3") que ao_vivo -- a secao "## ao_vivo / V3" NUNCA pode contar URSO
        # (retro) ou PATO (replay), so GATO (origem="v1v2v3"). PEDIDO 2026-11-05 (PARTE 3): token
        # trocado de RATO pra URSO -- "RATO" e substring acidental de "EXPLORATORIO" (label nova da
        # visao ii, sempre presente), o que derrubava este teste por colisao de texto, nunca por
        # mistura real de origem.
        todas_4 = {"A_atual": (10.0, 0.5), "B_breakeven_1x_caixa": (10.0, 0.5),
                  "C_fechamento_1h_sob_teto": (10.0, 0.5), "D_30pct_topo_trailing": (10.0, 0.5)}
        linhas = [
            _linha_variantes("GATO", "v3", "v1v2v3", todas_4),
            _linha_variantes("URSO", "v3", "retro", todas_4),
            _linha_variantes("PATO", "v3", "v3_replay", todas_4),
        ]
        texto = exit_lab.formatar(linhas, {}, {}, 0)
        idx_v3 = texto.index("## ao_vivo / V3")
        idx_retro = texto.index("## retro_lote1")
        bloco_v3 = texto[idx_v3:idx_retro]
        self.assertIn("n no grupo: 1", bloco_v3)   # SO GATO -- nunca URSO/PATO so por compartilhar "v3"
        self.assertNotIn("URSO", bloco_v3)
        self.assertNotIn("PATO", bloco_v3)


if __name__ == "__main__":
    unittest.main()
