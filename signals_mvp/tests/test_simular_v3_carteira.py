"""PEDIDO 2026-11-05 (autorizado, 3a rodada): testes de `scripts/simular_v3_carteira.py` -- tamanho
de posicao em VALOR ABSOLUTO (V10/V25/V50/V_oportunidade, com tetos de supply/volume e motivo de
pulado), impacto de preco, ledger so sobre saldo realizado, ponto de equilibrio, probabilidade de
ruina relativa, correcao de candle corrompido/latencia na entrada, amostra/overlap de tokens, e
smoke end-to-end. EXPLORATORIO -- nunca testa "edge" (isso e H1)."""

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
               risk_frac=0.2, volume_gatilho=None, volume_entrada=None, volume_medio_24h=None,
               n_pavios=None, supply=None,
               status_72h="marcado", r_72h=1.0, r_regra=None, r_7d=None, r_sombra_c=None, r_sombra_d=None)
    base.update(kwargs)
    return svc.TradeV3(**base)


class ValorBaseTests(unittest.TestCase):
    def test_v10_v25_v50_sao_valores_fixos(self) -> None:
        self.assertAlmostEqual(svc._valor_base("V10", _trade_minimo()), 10.0)
        self.assertAlmostEqual(svc._valor_base("V25", _trade_minimo()), 25.0)
        self.assertAlmostEqual(svc._valor_base("V50", _trade_minimo()), 50.0)

    def test_v_oportunidade_usa_volume_do_gatilho_para_qualificar(self) -> None:
        sem_qualidade = _trade_minimo(volume_gatilho=50.0, volume_medio_24h=40.0, n_pavios=3)   # <2x
        self.assertAlmostEqual(svc._valor_base("V_oportunidade", sem_qualidade), 10.0)
        qualidade_fraca = _trade_minimo(volume_gatilho=100.0, volume_medio_24h=40.0, n_pavios=3,
                                        volume_entrada=10.0)   # qualifica mas entrada fraca
        self.assertAlmostEqual(svc._valor_base("V_oportunidade", qualidade_fraca), 25.0)
        qualidade_forte = _trade_minimo(volume_gatilho=100.0, volume_medio_24h=40.0, n_pavios=3,
                                        volume_entrada=25.0)   # entrada >=50% da media (20)
        self.assertAlmostEqual(svc._valor_base("V_oportunidade", qualidade_forte), 50.0)

    def test_v_oportunidade_exige_exatamente_3_pavios(self) -> None:
        trade = _trade_minimo(volume_gatilho=100.0, volume_medio_24h=40.0, n_pavios=2, volume_entrada=25.0)
        self.assertAlmostEqual(svc._valor_base("V_oportunidade", trade), 10.0)


class TamanhoComTetosTests(unittest.TestCase):
    def test_sem_teto_algum_usa_o_valor_desejado(self) -> None:
        tamanho, desejado, motivo = svc._tamanho_com_tetos("V25", 1000.0, _trade_minimo(), svc.MAX_VOLUME_PCT_PADRAO)
        self.assertAlmostEqual(tamanho, 25.0)
        self.assertAlmostEqual(desejado, 25.0)
        self.assertIsNone(motivo)

    def test_sem_banca_livre_suficiente_entra_menor_e_marca_sem_capital(self) -> None:
        tamanho, desejado, motivo = svc._tamanho_com_tetos("V50", 15.0, _trade_minimo(), svc.MAX_VOLUME_PCT_PADRAO)
        self.assertAlmostEqual(tamanho, 15.0)
        self.assertAlmostEqual(desejado, 50.0)
        self.assertEqual(motivo, "sem_capital")

    def test_teto_de_supply_limita_e_marca_o_motivo(self) -> None:
        # 1,5% de 1000 tokens x preco 1.0 = US$15 -- menor que os US$25 pedidos.
        trade = _trade_minimo(entry_price=1.0, supply=1000.0)
        tamanho, _, motivo = svc._tamanho_com_tetos("V25", 1000.0, trade, svc.MAX_VOLUME_PCT_PADRAO)
        self.assertAlmostEqual(tamanho, 15.0)
        self.assertEqual(motivo, "teto_supply")

    def test_sem_supply_conhecido_o_teto_nunca_se_aplica(self) -> None:
        trade = _trade_minimo(entry_price=1.0, supply=None)
        tamanho, desejado, motivo = svc._tamanho_com_tetos("V25", 1000.0, trade, svc.MAX_VOLUME_PCT_PADRAO)
        self.assertAlmostEqual(tamanho, desejado)
        self.assertIsNone(motivo)

    def test_teto_de_volume_limita_e_marca_o_motivo(self) -> None:
        trade = _trade_minimo(volume_entrada=100.0)
        tamanho, _, motivo = svc._tamanho_com_tetos("V25", 1000.0, trade, max_volume_pct=10.0)
        self.assertAlmostEqual(tamanho, 10.0)   # 10% de 100
        self.assertEqual(motivo, "teto_volume")


class ImpactoPrecoTests(unittest.TestCase):
    def test_sem_volume_nunca_inventa_impacto(self) -> None:
        self.assertEqual(svc._impacto_preco_r(25.0, None), 0.0)
        self.assertEqual(svc._impacto_preco_r(25.0, 0.0), 0.0)

    def test_100pct_do_volume_custa_1r_com_coeficiente_padrao(self) -> None:
        self.assertAlmostEqual(svc._impacto_preco_r(50.0, 50.0), svc.IMPACT_COEF_R)

    def test_impacto_e_proporcional_a_posicao_sobre_volume(self) -> None:
        self.assertAlmostEqual(svc._impacto_preco_r(10.0, 100.0), svc.IMPACT_COEF_R * 0.10)


class LedgerRealizadoTests(unittest.TestCase):
    def _rodar(self, trades, regra="V10", banca=250.0, **kwargs):
        return svc.simular_carteira(trades, "ao_vivo", regra, "base", "US$0.05", banca,
                                    calcular_ruina=False, **kwargs)

    def test_banca_debita_no_open_e_credita_so_na_liberacao(self) -> None:
        trades = [
            _trade_minimo(token="A", t_entrada=0.0, r_72h=5.0),
            _trade_minimo(token="B", t_entrada=10.0, r_72h=5.0),   # ainda dentro das 72h de A
        ]
        r = self._rodar(trades, regra="V50", banca=100.0)
        self.assertEqual(r.n_trades, 2)   # 50+50=100 -- exatamente a banca, nunca mais

    def test_pendente_nunca_conta_como_perda_nem_consome_banca(self) -> None:
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

    def test_limite_de_posicoes_simultaneas_pula_e_conta_sem_vaga(self) -> None:
        trades = [_trade_minimo(token=t, t_entrada=0.0, r_72h=1.0) for t in ("A", "B", "C", "D")]
        r = self._rodar(trades, max_posicoes=2)
        self.assertEqual(r.n_trades, 2)
        self.assertEqual(r.pulados_por_motivo.get("sem_vaga"), 2)

    def test_entrada_nunca_fica_abaixo_do_minimo_pula_e_conta(self) -> None:
        # banca=15: V50 nao cabe (15<10 nao, mas apos a 1a entrada de 15 a banca_livre vira 0).
        trades = [_trade_minimo(token=t, t_entrada=0.0, r_72h=0.0) for t in ("A", "B")]
        r = self._rodar(trades, regra="V50", banca=15.0, max_posicoes=10)
        self.assertEqual(r.n_trades, 1)   # A entra reduzido a 15 (banca inteira)
        self.assertEqual(r.n_entradas_reduzidas, 1)
        self.assertEqual(r.pulados_por_motivo.get("sem_capital"), 1)   # B: banca_livre=0 < minimo

    def test_drawdown_e_a_maior_queda_desde_o_pico_realizado(self) -> None:
        trades = [
            _trade_minimo(token="A", t_entrada=0.0, r_72h=2.0),
            _trade_minimo(token="B", t_entrada=svc.HORIZONTES_S["72h"] + 1, r_72h=-2.0),
        ]
        r = self._rodar(trades)
        self.assertGreater(r.max_drawdown_pct, 0.0)
        self.assertGreater(r.max_drawdown_usd, 0.0)

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

    def test_r_medio_sem_top3_exclui_os_3_maiores_resultados(self) -> None:
        passo = svc.HORIZONTES_S["72h"] + 1
        trades = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=float(i)) for i in range(6)]
        r = self._rodar(trades, max_posicoes=10)
        self.assertIsNotNone(r.r_medio_sem_top3)
        self.assertLess(r.r_medio_sem_top3, r.r_medio)   # tira os maiores -- media cai

    def test_ponto_de_equilibrio_e_positivo_quando_r_e_positivo(self) -> None:
        trades = [_trade_minimo(token="A", t_entrada=0.0, r_72h=1.0)]
        r = self._rodar(trades)
        self.assertIsNotNone(r.ponto_equilibrio_custo_fixo_usd)
        self.assertGreater(r.ponto_equilibrio_custo_fixo_usd, 0.0)


class ProbabilidadeRuinaTests(unittest.TestCase):
    def test_sem_trades_devolve_none(self) -> None:
        self.assertIsNone(svc.probabilidade_ruina_bootstrap([], "V10", "base", "US$0.05", 250.0))

    def test_limiar_e_relativo_a_banca_inicial(self) -> None:
        passo = svc.HORIZONTES_S["72h"] + 1
        trades = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=-5.0) for i in range(10)]
        # com banca=10000, uma entrada V10 (US$10) perdendo nunca chega perto de 50% -- com
        # banca=15, a 1a entrada (trava US$10, perde) ja derruba a banca bem abaixo de 50%.
        p_banca_grande = svc.probabilidade_ruina_bootstrap(trades, "V10", "base", "US$0.05", 10_000.0, n_bootstrap=200)
        p_banca_pequena = svc.probabilidade_ruina_bootstrap(trades, "V10", "base", "US$0.05", 15.0, n_bootstrap=200)
        self.assertGreater(p_banca_pequena, p_banca_grande)

    def test_e_deterministico_com_a_mesma_seed(self) -> None:
        passo = svc.HORIZONTES_S["72h"] + 1
        trades = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=-1.0) for i in range(10)]
        p1 = svc.probabilidade_ruina_bootstrap(trades, "V50", "base", "US$0.05", 250.0, n_bootstrap=500)
        p2 = svc.probabilidade_ruina_bootstrap(trades, "V50", "base", "US$0.05", 250.0, n_bootstrap=500)
        self.assertEqual(p1, p2)


class CorrecaoDeEntradaTests(unittest.TestCase):
    def test_candle_de_entrada_corrompido_usa_o_candle_limpo_anterior(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 0.0)])
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


class OverlapTokensTests(unittest.TestCase):
    def test_tokens_em_mais_de_1_origem_sao_contados(self) -> None:
        ao_vivo = [_trade_minimo(token="CAT")]
        retro = [_trade_minimo(token="CAT", origem="retro_lote1")]
        replay = [_trade_minimo(token="DOG", origem="v3_replay")]
        linhas = svc._resumo_overlap_tokens(ao_vivo, retro, replay)
        self.assertIn("tokens em mais de 1 origem: 1", linhas[0])
        self.assertIn("CAT", linhas[0])

    def test_sem_overlap_conta_zero(self) -> None:
        ao_vivo = [_trade_minimo(token="CAT")]
        retro = [_trade_minimo(token="DOG", origem="retro_lote1")]
        linhas = svc._resumo_overlap_tokens(ao_vivo, retro, [])
        self.assertIn("tokens em mais de 1 origem: 0", linhas[0])


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

    def test_sinal_ainda_pendente_mostra_quando_completa_e_nunca_crasha(self) -> None:
        # `executar()` usa o relogio REAL (time.time()) -- t_entrada precisa estar perto de agora
        # (nunca em 1970) pra que o horizonte de 72h ainda nao tenha decorrido de verdade.
        import time as _time
        ts0 = int(_time.time()) - 3_600
        signal_id = self.storage.pr3_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": ts0,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v3": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "aberto", "entry_price": 100.0, "stop": 80.0, "topo": 10_000.0,
            "s_suporte": 50.0, "r_resistencia": 90.0, "n_pavios": 3,
        })
        self.storage.pr_trajetoria_upsert("v3", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                          mint="MINT1", symbol="CAT", t_entrada=float(ts0 + 3_600),
                                          preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0, fonte_candle="gt")
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0)], ts0=ts0, step=3_600)
        self.storage.pr_append_bars("POOL1", "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume,
                                                     int(b.filled)) for b in bars])
        texto = svc.executar(self.storage.paths.db, banca=250.0)
        self.assertIn("pendentes de 72h", texto)
        self.assertIn("1o sinal pendente completa 72h em:", texto)
        self.assertIn("sem trades com desfecho definido ainda", texto)
        self.assertNotIn("Traceback", texto)

    def test_banca_explicita_roda_so_1_cenario(self) -> None:
        texto = svc.executar(self.storage.paths.db, banca=777.0)
        self.assertIn("US$777", texto)
        self.assertNotIn("US$250", texto)

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
