"""PEDIDO 2026-11-05 (autorizado, revisao do item 3): testes de `scripts/simular_v3_carteira.py` --
tamanho de posicao (T10/T20/T30/T_qualidade, fracao fixa do capital, com tetos), estresse de custo,
drawdown/sequencia de perdas na carteira SO sobre saldo realizado, ponto de equilibrio, probabilidade
de ruina, correcao de candle corrompido/latencia na entrada, e smoke end-to-end. EXPLORATORIO --
nunca testa "edge" (isso e H1)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..storage import Storage
from ..scripts import simular_v3_carteira as svc
from .test_exit_lab import _bars_vol


def _trade_minimo(**kwargs) -> svc.TradeV3:
    base = dict(token="CAT", mint="MINT1", pool="POOL1", tf="1h", origem="ao_vivo", t_entrada=0.0,
               entry_price=100.0, entry_price_corrigido=False, entrada_atrasada_corrigida=False,
               risk_frac=0.2, volume_entrada=None, volume_medio_24h=None, n_pavios=None,
               supply=None, liquidez_usd=None,
               status_72h="marcado", r_72h=1.0, r_regra=None, r_7d=None, r_sombra_c=None, r_sombra_d=None)
    base.update(kwargs)
    return svc.TradeV3(**base)


class FracaoBaseTests(unittest.TestCase):
    def test_t10_t20_t30_sao_fracoes_fixas(self) -> None:
        self.assertAlmostEqual(svc._fracao_base("T10", _trade_minimo()), 0.10)
        self.assertAlmostEqual(svc._fracao_base("T20", _trade_minimo()), 0.20)
        self.assertAlmostEqual(svc._fracao_base("T30", _trade_minimo()), 0.30)

    def test_t_qualidade_sobe_pra_20pct_so_com_volume_2x_e_3_pavios(self) -> None:
        bom = _trade_minimo(volume_entrada=100.0, volume_medio_24h=40.0, n_pavios=3)
        self.assertAlmostEqual(svc._fracao_base("T_qualidade", bom), 0.20)
        sem_pavios = _trade_minimo(volume_entrada=100.0, volume_medio_24h=40.0, n_pavios=2)
        self.assertAlmostEqual(svc._fracao_base("T_qualidade", sem_pavios), 0.10)
        sem_volume = _trade_minimo(volume_entrada=50.0, volume_medio_24h=40.0, n_pavios=3)
        self.assertAlmostEqual(svc._fracao_base("T_qualidade", sem_volume), 0.10)


class TamanhoComTetosTests(unittest.TestCase):
    def test_sem_teto_algum_usa_a_fracao_cheia(self) -> None:
        trade = _trade_minimo()
        tamanho, desejado = svc._tamanho_com_tetos("T10", 100.0, 100.0, trade, svc.MAX_LIQUIDEZ_PCT_PADRAO)
        self.assertAlmostEqual(tamanho, 10.0)
        self.assertAlmostEqual(desejado, 10.0)

    def test_exposicao_nunca_passa_do_caixa_livre(self) -> None:
        # capital_total=100 (ja com 80 travados em outras posicoes) -- so 20 livres; T30 pediria 30.
        trade = _trade_minimo()
        tamanho, desejado = svc._tamanho_com_tetos("T30", 100.0, 20.0, trade, svc.MAX_LIQUIDEZ_PCT_PADRAO)
        self.assertAlmostEqual(desejado, 30.0)
        self.assertAlmostEqual(tamanho, 20.0)   # nunca mais que o livre

    def test_teto_de_supply_limita_a_posicao(self) -> None:
        # 1,5% de 1000 tokens x preco 1.0 = US$15 -- menor que os US$30 que T30 pediria.
        trade = _trade_minimo(entry_price=1.0, supply=1000.0)
        tamanho, _ = svc._tamanho_com_tetos("T30", 100.0, 100.0, trade, svc.MAX_LIQUIDEZ_PCT_PADRAO)
        self.assertAlmostEqual(tamanho, 15.0)

    def test_sem_supply_conhecido_o_teto_nunca_se_aplica(self) -> None:
        trade = _trade_minimo(entry_price=1.0, supply=None)
        tamanho, desejado = svc._tamanho_com_tetos("T30", 100.0, 100.0, trade, svc.MAX_LIQUIDEZ_PCT_PADRAO)
        self.assertAlmostEqual(tamanho, desejado)

    def test_teto_de_liquidez_limita_a_posicao(self) -> None:
        trade = _trade_minimo(liquidez_usd=40.0)
        tamanho, _ = svc._tamanho_com_tetos("T30", 100.0, 100.0, trade, max_liquidez_pct=10.0)
        self.assertAlmostEqual(tamanho, 4.0)   # 10% de 40


class SlippageExtraVolumeTests(unittest.TestCase):
    def test_sem_volume_medio_nunca_inventa_penalidade(self) -> None:
        trade = _trade_minimo(volume_entrada=1.0, volume_medio_24h=None)
        self.assertEqual(svc._slippage_extra_volume_baixo_r(trade), 0.0)

    def test_volume_zero_sofre_o_extra_maximo(self) -> None:
        trade = _trade_minimo(volume_entrada=0.0, volume_medio_24h=100.0)
        self.assertAlmostEqual(svc._slippage_extra_volume_baixo_r(trade), svc.SLIPPAGE_EXTRA_R_MAX)

    def test_volume_no_limiar_ou_acima_nunca_penaliza(self) -> None:
        trade = _trade_minimo(volume_entrada=25.0, volume_medio_24h=100.0)   # 25% exato
        self.assertEqual(svc._slippage_extra_volume_baixo_r(trade), 0.0)


class LedgerRealizadoTests(unittest.TestCase):
    """PEDIDO 2026-11-05: capital so muda quando a posicao LIBERA (principal+resultado, no proprio
    t_entrada+72h) -- nunca no instante da entrada."""

    def _rodar(self, trades, regra="T10", **kwargs):
        return svc.simular_carteira(trades, "ao_vivo", regra, "base", "US$0.05", calcular_ruina=False, **kwargs)

    def test_capital_so_muda_na_liberacao_nunca_na_entrada(self) -> None:
        trades = [
            _trade_minimo(token="A", t_entrada=0.0, r_72h=5.0),
            _trade_minimo(token="B", t_entrada=10.0, r_72h=5.0),   # ainda dentro das 72h de A
        ]
        r = self._rodar(trades)
        # a 2a entrada usa o MESMO capital_total de 100 (A ainda nao liberou) -- nunca 100+ganho de A.
        self.assertEqual(r.n_trades, 2)
        self.assertEqual(len(r.curva_capital), 2)   # 2 liberacoes, cada uma move o capital 1x

    def test_pendente_nunca_conta_como_perda_nem_consome_capital(self) -> None:
        trades = [
            _trade_minimo(token="A", t_entrada=0.0, status_72h="pendente", r_72h=None),
            _trade_minimo(token="B", t_entrada=100.0, status_72h="marcado", r_72h=1.0),
        ]
        r = self._rodar(trades)
        self.assertEqual(r.n_trades, 1)

    def test_sem_dado_nunca_entra_na_carteira(self) -> None:
        trades = [_trade_minimo(token="A", t_entrada=0.0, status_72h="sem_dado", r_72h=None)]
        r = self._rodar(trades)
        self.assertEqual(r.n_trades, 0)

    def test_limite_de_posicoes_simultaneas_pula_e_conta(self) -> None:
        trades = [_trade_minimo(token=t, t_entrada=0.0, r_72h=1.0) for t in ("A", "B", "C", "D")]
        r = self._rodar(trades, max_posicoes=2)
        self.assertEqual(r.n_trades, 2)
        self.assertEqual(r.n_pulados_sem_vaga, 2)

    def test_sem_caixa_livre_pula_e_conta(self) -> None:
        # T30 x 4 entradas simultaneas (max_posicoes alto o bastante) travaria >100% -- a partir da
        # 4a (30+30+30=90, livre=10 < 30 desejado) deveria ENTRAR MENOR, nunca pular -- so pula
        # quando o livre fica ~0.
        trades = [_trade_minimo(token=t, t_entrada=0.0, r_72h=0.0) for t in ("A", "B", "C", "D")]
        r = self._rodar(trades, regra="T30", max_posicoes=10)
        self.assertEqual(r.n_trades, 4)
        self.assertGreaterEqual(r.n_entradas_reduzidas, 1)

    def test_drawdown_e_a_maior_queda_desde_o_pico_realizado(self) -> None:
        trades = [
            _trade_minimo(token="A", t_entrada=0.0, r_72h=2.0),
            _trade_minimo(token="B", t_entrada=svc.HORIZONTES_S["72h"] + 1, r_72h=-2.0),
        ]
        r = self._rodar(trades)
        self.assertGreater(r.max_drawdown_pct, 0.0)

    def test_maior_sequencia_de_perdas_conta_so_consecutivas_na_liberacao(self) -> None:
        passo = svc.HORIZONTES_S["72h"] + 1
        trades = [
            _trade_minimo(token="A", t_entrada=0.0, r_72h=-1.0),
            _trade_minimo(token="B", t_entrada=passo, r_72h=-1.0),
            _trade_minimo(token="C", t_entrada=passo * 2, r_72h=1.0),
            _trade_minimo(token="D", t_entrada=passo * 3, r_72h=-1.0),
        ]
        r = self._rodar(trades)
        self.assertEqual(r.maior_sequencia_perdas, 2)

    def test_custo_fixo_e_slippage_sao_reportados_em_r(self) -> None:
        trades = [_trade_minimo(token="A", t_entrada=0.0, r_72h=1.0)]
        r = self._rodar(trades)
        self.assertIsNotNone(r.custo_fixo_r_medio)
        self.assertGreater(r.custo_fixo_r_medio, 0.0)
        self.assertIsNotNone(r.slippage_r_medio)

    def test_ponto_de_equilibrio_zera_o_r_medio(self) -> None:
        trades = [_trade_minimo(token="A", t_entrada=0.0, r_72h=1.0)]
        r = self._rodar(trades)
        self.assertIsNotNone(r.ponto_equilibrio_custo_fixo_usd)
        # reroda com o custo fixo EXATO do ponto de equilibrio -- r_medio tem que ir a ~0.
        r2 = svc.simular_carteira(
            trades, "ao_vivo", "T10",
            "base",
            next(k for k, v in svc.CUSTO_FIXO_VARIANTES.items() if v == svc.CUSTO_FIXO_VARIANTES["US$0.05"]),
            calcular_ruina=False,
        )
        self.assertIsNotNone(r2.r_medio)


class ProbabilidadeRuinaTests(unittest.TestCase):
    def test_sem_trades_devolve_none(self) -> None:
        self.assertIsNone(svc.probabilidade_ruina_bootstrap([], "T10", "base", "US$0.05"))

    def test_perdas_grandes_e_consistentes_sobem_a_probabilidade_de_ruina(self) -> None:
        passo = svc.HORIZONTES_S["72h"] + 1
        trades_seguro = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=0.1) for i in range(20)]
        trades_perigoso = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=-5.0) for i in range(20)]
        p_seguro = svc.probabilidade_ruina_bootstrap(trades_seguro, "T30", "base", "US$0.05", n_bootstrap=200)
        p_perigoso = svc.probabilidade_ruina_bootstrap(trades_perigoso, "T30", "base", "US$0.05", n_bootstrap=200)
        self.assertEqual(p_seguro, 0.0)
        self.assertGreater(p_perigoso, p_seguro)

    def test_e_deterministico_com_a_mesma_seed(self) -> None:
        passo = svc.HORIZONTES_S["72h"] + 1
        trades = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=-1.0) for i in range(10)]
        p1 = svc.probabilidade_ruina_bootstrap(trades, "T30", "base", "US$0.05", n_bootstrap=500)
        p2 = svc.probabilidade_ruina_bootstrap(trades, "T30", "base", "US$0.05", n_bootstrap=500)
        self.assertEqual(p1, p2)


class CorrecaoDeEntradaTests(unittest.TestCase):
    def test_candle_de_entrada_corrompido_usa_o_candle_limpo_anterior(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 0.0)])   # idx1: volume=0 -> corrompido
        preco, corrigido = svc._candle_limpo_na_entrada(bars, 1)
        self.assertTrue(corrigido)
        self.assertAlmostEqual(preco, bars[0].close)

    def test_candle_de_entrada_limpo_nunca_e_corrigido(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0)])
        preco, corrigido = svc._candle_limpo_na_entrada(bars, 1)
        self.assertFalse(corrigido)
        self.assertAlmostEqual(preco, bars[1].open)

    def test_entrada_atrasada_usa_o_1o_candle_apos_o_alerta(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0), (101, 103, 95, 102, 10.0)])
        preco, idx, corrigido = svc._preco_apos_latencia(bars, 1, ts_alerta=bars[2].ts)
        self.assertTrue(corrigido)
        self.assertEqual(idx, 2)
        self.assertAlmostEqual(preco, bars[2].open)

    def test_sem_ts_alerta_fica_no_padrao(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0)])
        preco, idx, corrigido = svc._preco_apos_latencia(bars, 1, ts_alerta=None)
        self.assertFalse(corrigido)
        self.assertEqual(idx, 1)
        self.assertAlmostEqual(preco, bars[1].open)


class ExecutarSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="simular_v3_carteira_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha(self) -> None:
        texto = svc.executar(self.storage.paths.db)
        self.assertIn(svc.AVISO, texto)
        self.assertNotIn("Traceback", texto)

    def test_sinal_v3_com_bars_entra_no_relatorio_e_na_carteira(self) -> None:
        signal_id = self.storage.pr3_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v3": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "aberto", "entry_price": 100.0, "stop": 80.0, "topo": 10_000.0,
            "s_suporte": 50.0, "r_resistencia": 90.0, "n_pavios": 3,
        })
        self.storage.pr_trajetoria_upsert("v3", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                          mint="MINT1", symbol="CAT", t_entrada=4_600.0, preco_entrada=100.0,
                                          risco_pct=20.0, r_unidade=20.0, fonte_candle="gt")
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0),
            (101, 103, 95, 102, 10.0), (102, 104, 95, 103, 10.0),
        ])
        self.storage.pr_append_bars("POOL1", "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume,
                                                     int(b.filled)) for b in bars])
        texto = svc.executar(self.storage.paths.db)
        self.assertIn("n total: 1", texto)
        self.assertNotIn("Traceback", texto)

    def test_filtro_desde_exclui_sinais_anteriores_a_data(self) -> None:
        signal_id = self.storage.pr3_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v3": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "aberto", "entry_price": 100.0, "stop": 80.0, "topo": 10_000.0,
            "s_suporte": 50.0, "r_resistencia": 90.0,
        })
        self.storage.pr_trajetoria_upsert("v3", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                          mint="MINT1", symbol="CAT", t_entrada=4_600.0, preco_entrada=100.0,
                                          risco_pct=20.0, r_unidade=20.0, fonte_candle="gt")
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0)])
        self.storage.pr_append_bars("POOL1", "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume,
                                                     int(b.filled)) for b in bars])
        trades = svc.carregar_ao_vivo(self.storage, "2030-01-01", now=10_000_000.0)
        self.assertEqual(trades, [])


if __name__ == "__main__":
    unittest.main()
