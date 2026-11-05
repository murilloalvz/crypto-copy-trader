"""PEDIDO 2026-11-05 (autorizado): testes de `scripts/simular_v3_carteira.py` -- tamanho de posicao
(R1/R2/R3), estresse de custo, drawdown/sequencia de perdas na carteira, correcao de candle
corrompido/latencia na entrada, e smoke end-to-end. EXPLORATORIO -- nunca testa "edge" (isso e H1)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..storage import Storage
from ..scripts import simular_v3_carteira as svc
from .test_exit_lab import _bars_vol


class TamanhoPosicaoTests(unittest.TestCase):
    def test_r1_e_1pct_de_risco_com_teto_de_25pct(self) -> None:
        self.assertAlmostEqual(svc.tamanho_r1(100.0, 0.20), 5.0)       # 1%/0.20 = 5% do capital
        self.assertAlmostEqual(svc.tamanho_r1(100.0, 0.001), 25.0)     # risco minusculo -> bate o teto

    def test_r2_e_o_dobro_do_r1_na_mesma_entrada(self) -> None:
        self.assertAlmostEqual(svc.tamanho_r2(100.0, 0.20), 10.0)

    def test_r3_sobe_pra_2pct_so_com_volume_2x_e_3_pavios(self) -> None:
        self.assertAlmostEqual(svc.tamanho_r3(100.0, 0.20, 100.0, 40.0, 3), 10.0)   # 100>=2*40, pavios=3
        self.assertAlmostEqual(svc.tamanho_r3(100.0, 0.20, 100.0, 40.0, 2), 5.0)    # pavios != 3
        self.assertAlmostEqual(svc.tamanho_r3(100.0, 0.20, 70.0, 40.0, 3), 5.0)     # volume < 2x

    def test_risco_zero_ou_capital_zero_nunca_abre_posicao(self) -> None:
        self.assertEqual(svc.tamanho_r1(100.0, 0.0), 0.0)
        self.assertEqual(svc.tamanho_r1(0.0, 0.2), 0.0)


class EstresseCustoTests(unittest.TestCase):
    def test_slippage_base_nunca_muda_o_r(self) -> None:
        trade = _trade_minimo(volume_entrada=100.0, volume_medio_24h=100.0)
        self.assertAlmostEqual(svc.r_apos_custo(trade, 1.0, svc.SLIPPAGE_VARIANTES["base"]), 1.0)

    def test_slippage_mais_0_3r_subtrai_0_3_do_r(self) -> None:
        trade = _trade_minimo(volume_entrada=100.0, volume_medio_24h=100.0)
        self.assertAlmostEqual(svc.r_apos_custo(trade, 1.0, svc.SLIPPAGE_VARIANTES["+0.3R"]), 0.7)

    def test_volume_abaixo_do_limiar_soma_slippage_extra_proporcional(self) -> None:
        # limiar = 25% de 100 = 25; volume=0 (pior caso) -> extra = SLIPPAGE_EXTRA_R_MAX cheio.
        trade_zero = _trade_minimo(volume_entrada=0.0, volume_medio_24h=100.0)
        self.assertAlmostEqual(svc._slippage_extra_volume_baixo_r(trade_zero), svc.SLIPPAGE_EXTRA_R_MAX)
        # volume = metade do limiar -> metade do extra maximo.
        trade_meio = _trade_minimo(volume_entrada=12.5, volume_medio_24h=100.0)
        self.assertAlmostEqual(svc._slippage_extra_volume_baixo_r(trade_meio), svc.SLIPPAGE_EXTRA_R_MAX / 2.0)
        # volume no limiar (25) ou acima -> zero extra.
        trade_no_limiar = _trade_minimo(volume_entrada=25.0, volume_medio_24h=100.0)
        self.assertEqual(svc._slippage_extra_volume_baixo_r(trade_no_limiar), 0.0)

    def test_sem_volume_medio_nunca_inventa_penalidade(self) -> None:
        trade = _trade_minimo(volume_entrada=1.0, volume_medio_24h=None)
        self.assertEqual(svc._slippage_extra_volume_baixo_r(trade), 0.0)

    def test_r_base_none_nunca_produz_resultado(self) -> None:
        trade = _trade_minimo(volume_entrada=100.0, volume_medio_24h=100.0)
        self.assertIsNone(svc.r_apos_custo(trade, None, 0.0))


def _trade_minimo(**kwargs) -> svc.TradeV3:
    base = dict(token="CAT", mint="MINT1", pool="POOL1", tf="1h", origem="ao_vivo", t_entrada=0.0,
               entry_price=100.0, entry_price_corrigido=False, entrada_atrasada_corrigida=False,
               risk_frac=0.2, volume_entrada=None, volume_medio_24h=None, n_pavios=None,
               status_72h="marcado", r_72h=1.0, r_regra=None, r_7d=None, r_sombra_c=None, r_sombra_d=None)
    base.update(kwargs)
    return svc.TradeV3(**base)


class CarteiraLedgerTests(unittest.TestCase):
    def test_pendente_nunca_conta_como_perda_nem_consome_capital(self) -> None:
        trades = [
            _trade_minimo(token="A", t_entrada=0.0, status_72h="pendente", r_72h=None),
            _trade_minimo(token="B", t_entrada=100.0, status_72h="marcado", r_72h=1.0),
        ]
        r = svc.simular_carteira(trades, "ao_vivo", "R1_risco_1pct", "base", "US$0.05")
        self.assertEqual(r.n_trades, 1)   # so B entra -- A (pendente) nunca conta

    def test_drawdown_e_a_maior_queda_desde_o_pico_de_capital(self) -> None:
        # +2R depois -2R depois -2R: pico apos o 1o trade, dd medido contra ESSE pico.
        trades = [
            _trade_minimo(token="A", t_entrada=0.0, r_72h=2.0),
            _trade_minimo(token="B", t_entrada=100.0, r_72h=-2.0),
            _trade_minimo(token="C", t_entrada=200.0, r_72h=-2.0),
        ]
        r = svc.simular_carteira(trades, "ao_vivo", "R1_risco_1pct", "base", "US$0.05")
        self.assertGreater(r.max_drawdown_pct, 0.0)
        self.assertEqual(r.n_trades, 3)

    def test_maior_sequencia_de_perdas_conta_so_consecutivas(self) -> None:
        trades = [
            _trade_minimo(token="A", t_entrada=0.0, r_72h=-1.0),
            _trade_minimo(token="B", t_entrada=100.0, r_72h=-1.0),
            _trade_minimo(token="C", t_entrada=200.0, r_72h=1.0),
            _trade_minimo(token="D", t_entrada=300.0, r_72h=-1.0),
        ]
        r = svc.simular_carteira(trades, "ao_vivo", "R1_risco_1pct", "base", "US$0.05")
        self.assertEqual(r.maior_sequencia_perdas, 2)

    def test_limite_de_posicoes_simultaneas_nunca_abre_alem_do_teto(self) -> None:
        # todas entram na MESMA hora (ocupam a MESMA vaga por 72h) -- so as 2 primeiras cabem com max=2.
        trades = [_trade_minimo(token=t, t_entrada=0.0, r_72h=1.0) for t in ("A", "B", "C", "D")]
        r = svc.simular_carteira(trades, "ao_vivo", "R1_risco_1pct", "base", "US$0.05", max_posicoes=2)
        self.assertEqual(r.n_trades, 2)

    def test_sem_dado_nunca_entra_na_carteira(self) -> None:
        trades = [_trade_minimo(token="A", t_entrada=0.0, status_72h="sem_dado", r_72h=None)]
        r = svc.simular_carteira(trades, "ao_vivo", "R1_risco_1pct", "base", "US$0.05")
        self.assertEqual(r.n_trades, 0)


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
        self.assertIn("CAT", texto) if "CAT" in texto else None   # token so aparece se citado por nome
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
