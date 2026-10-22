"""Testes com dados sinteticos para signals_mvp.analise.simulacao_bloco (PAPER / so leitura)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from signals_mvp.analise.simulacao_bloco import (
    DistribuicaoFrequencia,
    RecusaAmostraInsuficiente,
    TradeRealizado,
    VERSAO_CONGELADA,
    _aplicar_trade,
    _carregar_banca,
    _carregar_sinais_fechados,
    _EstadoLedgerSim,
    _juntar,
    _pesos_dias,
    _preparar_dias,
    _simular_uma_rodada,
    _todas_semanas_observadas,
    calcular_estatisticas,
    calibrar_frequencia,
    executar,
    proporcao_com_ic,
)
from signals_mvp.pos_runner.bankroll_v1 import COLUMNS as BANCA_COLUMNS
from signals_mvp.pos_runner.bankroll_v1 import HEADER_LABELS as BANCA_HEADER_LABELS
from signals_mvp.pos_runner.params_v1 import load_params_v1
from signals_mvp.storage import POS_RUNNER_V1_COLUMNS
from signals_mvp.util import atomic_write_csv

_BASE_TS = 1_760_000_000.0  # 2025-10-09T08:53:20Z -- so uma ancora fixa qualquer


def _trade_fixo(
    *, risco_pct: float = 20.0, lucro_liquido_pct: float = -20.0, tempo_h: float = 2.0,
    dia_offset: int = 0, contrato: str = "CONTRATO1", tf: str = "1h",
) -> TradeRealizado:
    ts = _BASE_TS + dia_offset * 86_400.0
    tamanho = 10.0
    return TradeRealizado(
        contrato=contrato, tf=tf, data_entrada=ts, tamanho_posicao_usd=tamanho,
        resultado_usd=tamanho * (lucro_liquido_pct / 100.0), lucro_liquido_pct=lucro_liquido_pct,
        risco_pct=risco_pct, tempo_no_trade_h=tempo_h,
    )


class TestRMultiplo(unittest.TestCase):
    def test_r_multiplo_e_pnl_sobre_risco(self) -> None:
        t = _trade_fixo(risco_pct=20.0, lucro_liquido_pct=-40.0)
        self.assertAlmostEqual(t.r_multiplo, -2.0, places=9)


class TestRecusaAmostraInsuficiente(unittest.TestCase):
    def test_recusa_com_menos_de_30_trades(self) -> None:
        trades = [_trade_fixo(dia_offset=i) for i in range(29)]
        with self.assertRaises(RecusaAmostraInsuficiente):
            executar(trades=trades)

    def test_roda_com_30_trades_exatos(self) -> None:
        trades = [
            _trade_fixo(dia_offset=i, lucro_liquido_pct=(6.0 if i % 2 == 0 else -6.0))
            for i in range(30)
        ]
        relatorios = executar(trades=trades, n_simulacoes=40, n_semanas=4, n_bootstrap_expectancia=100)
        self.assertEqual(len(relatorios), 2)  # normal + estresse
        for rel in relatorios:
            self.assertEqual(rel.n_trades_historicos, 30)
            self.assertGreater(rel.banca_mediana, 0.0)


class TestAplicarTradeGuardrails(unittest.TestCase):
    """Travas reais de bankroll_v1 (importadas, nunca duplicadas) tem que valer tambem no sorteio."""

    def test_limite_de_posicoes_abertas(self) -> None:
        params = load_params_v1()
        estado = _EstadoLedgerSim.novo(params.banca_inicial_usd)
        amostra = _trade_fixo(lucro_liquido_pct=1.0, risco_pct=20.0, tempo_h=100_000.0)  # nunca fecha
        executados = 0
        for i in range(10):
            ok = _aplicar_trade(estado, _BASE_TS + i, "d0", "s0", amostra, params, params.banca_inicial_usd)
            executados += int(ok)
        self.assertEqual(executados, params.max_posicoes_abertas)
        self.assertEqual(len(estado.open_positions), params.max_posicoes_abertas)

    def test_stop_diario_por_perdas_seguidas(self) -> None:
        params = load_params_v1()
        estado = _EstadoLedgerSim.novo(params.banca_inicial_usd)
        perda = _trade_fixo(lucro_liquido_pct=-5.0, risco_pct=20.0, tempo_h=0.001)
        n_tentativas = params.stop_diario_perdas_seguidas + 2
        resultados = [
            _aplicar_trade(estado, _BASE_TS + i * 10, "d0", "s0", perda, params, params.banca_inicial_usd)
            for i in range(n_tentativas)
        ]
        self.assertTrue(all(resultados[: params.stop_diario_perdas_seguidas]))
        self.assertFalse(any(resultados[params.stop_diario_perdas_seguidas :]))
        self.assertTrue(estado.dia_pausado)

    def test_stop_semanal(self) -> None:
        params = load_params_v1()
        estado = _EstadoLedgerSim.novo(params.banca_inicial_usd)
        perda_grande = _trade_fixo(lucro_liquido_pct=-80.0, risco_pct=100.0, tempo_h=0.001)
        for i in range(5):  # dias DIFERENTES (sem disparar o stop diario), MESMA semana
            _aplicar_trade(estado, _BASE_TS + i * 86_400.0, f"d{i}", "s0", perda_grande, params, params.banca_inicial_usd)
        self.assertTrue(estado.semana_pausada)


class TestBlocoPorDiaPreservaCorrelacao(unittest.TestCase):
    """O mesmo conjunto de 10 perdas identicas produz bancas finais DIFERENTES dependendo de cairem
    no mesmo dia (correlacionadas -> stop diario trava depois da 3a) ou em dias separados
    (decorrelacionadas -> perdas_seguidas reseta e nenhum stop diario dispara)."""

    def test_mesmo_dia_aciona_stop_diario_mais_rapido_que_dias_separados(self) -> None:
        params = load_params_v1()
        agrupado = [_trade_fixo(dia_offset=0, lucro_liquido_pct=-20.0, risco_pct=100.0) for _ in range(10)]
        espalhado = [_trade_fixo(dia_offset=i, lucro_liquido_pct=-20.0, risco_pct=100.0) for i in range(10)]
        dist_fixa = DistribuicaoFrequencia(tipo="fixa", media=10.0)

        stats_agrupado = calcular_estatisticas(agrupado)
        dias_a = _preparar_dias(stats_agrupado.por_dia)
        pesos_a = _pesos_dias(dias_a, stats_agrupado.dias_ruins, 1.0)
        resultado_agrupado = _simular_uma_rodada(
            np.random.default_rng(7), params, stats_agrupado, dist_fixa, 1, dias_a, pesos_a)

        stats_espalhado = calcular_estatisticas(espalhado)
        dias_e = _preparar_dias(stats_espalhado.por_dia)
        pesos_e = _pesos_dias(dias_e, stats_espalhado.dias_ruins, 1.0)
        resultado_espalhado = _simular_uma_rodada(
            np.random.default_rng(7), params, stats_espalhado, dist_fixa, 1, dias_e, pesos_e)

        perda_por_trade = 10.0 * 0.20  # mao_fixa_usd=10 (banca<200) x 20% de perda liquida
        self.assertAlmostEqual(
            resultado_agrupado.banca_final,
            100.0 - params.stop_diario_perdas_seguidas * perda_por_trade, places=6)
        self.assertAlmostEqual(resultado_espalhado.banca_final, 100.0 - 10 * perda_por_trade, places=6)
        self.assertGreater(resultado_agrupado.banca_final, resultado_espalhado.banca_final)


class TestCalibrarFrequencia(unittest.TestCase):
    def test_sem_trades_da_poisson_zero(self) -> None:
        dist = calibrar_frequencia([])
        self.assertEqual(dist.tipo, "poisson")
        self.assertEqual(dist.media, 0.0)

    def test_superdispersao_troca_para_binomial_negativa(self) -> None:
        contagens = [0, 0, 0, 20, 0, 25, 0, 0]  # media baixa, variancia muito alta
        dist = calibrar_frequencia(contagens)
        self.assertEqual(dist.tipo, "binomial_negativa")
        amostra = dist.sortear(np.random.default_rng(1), 1000)
        self.assertGreaterEqual(amostra.min(), 0)

    def test_frequencia_uniforme_fica_poisson(self) -> None:
        contagens = [5, 5, 4, 6, 5, 5]
        dist = calibrar_frequencia(contagens)
        self.assertEqual(dist.tipo, "poisson")


class TestSemanasObservadasIncluiSemanasVazias(unittest.TestCase):
    def test_semana_sem_trade_entra_como_zero(self) -> None:
        trades = [_trade_fixo(dia_offset=0), _trade_fixo(dia_offset=21)]  # 3 semanas de intervalo
        contagens = _todas_semanas_observadas(trades)
        self.assertEqual(sum(contagens), 2)
        self.assertGreaterEqual(len(contagens), 3)
        self.assertIn(0, contagens)


class TestProporcaoComIC(unittest.TestCase):
    def test_ic_contem_a_proporcao_observada(self) -> None:
        p, baixo, alto = proporcao_com_ic(250, 1000)
        self.assertAlmostEqual(p, 0.25)
        self.assertLessEqual(baixo, p)
        self.assertGreaterEqual(alto, p)

    def test_n_zero_nao_quebra(self) -> None:
        self.assertEqual(proporcao_com_ic(0, 0), (0.0, 0.0, 0.0))


class TestCargaCsvReal(unittest.TestCase):
    """Confirma que o loader casa pos_runner_v1.csv com pos_runner_v1_banca.csv usando os MESMOS
    nomes/formatos de coluna que signals_mvp.storage escreve de verdade (inclusive os rotulos
    '_%' da banca)."""

    def test_junta_sinais_e_banca_por_posicao(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            sinais_path = base / "pos_runner_v1.csv"
            banca_path = base / "pos_runner_v1_banca.csv"

            linha_sinal = {c: "" for c in POS_RUNNER_V1_COLUMNS}
            linha_sinal.update(
                data="2026-10-20T10:00:00Z", contrato="ABC", tf="1h",
                risco_pct="18.0", motivo_saida="tp1", versao_config_v1=VERSAO_CONGELADA)
            atomic_write_csv(sinais_path, POS_RUNNER_V1_COLUMNS, [[linha_sinal[c] for c in POS_RUNNER_V1_COLUMNS]])

            header_banca = [BANCA_HEADER_LABELS.get(c, c) for c in BANCA_COLUMNS]
            linha_banca = {c: "" for c in BANCA_COLUMNS}
            linha_banca.update(
                data_entrada="2026-10-20T10:01:00Z", contrato="ABC", tf="1h",
                tamanho_posicao_usd="10.0", resultado_usd="-1.8", lucro_liquido_pct="-18.0",
                tempo_no_trade_h="2.0", motivo_saida="tp1")
            atomic_write_csv(banca_path, header_banca, [[linha_banca[c] for c in BANCA_COLUMNS]])

            sinais = _carregar_sinais_fechados(sinais_path)
            banca = _carregar_banca(banca_path)
            trades = _juntar(sinais, banca, VERSAO_CONGELADA)

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].contrato, "ABC")
        self.assertAlmostEqual(trades[0].r_multiplo, -1.0, places=6)

    def test_versao_diferente_e_descartada(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            sinais_path = base / "pos_runner_v1.csv"
            banca_path = base / "pos_runner_v1_banca.csv"

            linha_sinal = {c: "" for c in POS_RUNNER_V1_COLUMNS}
            linha_sinal.update(
                data="2026-10-20T10:00:00Z", contrato="ABC", tf="1h",
                risco_pct="18.0", motivo_saida="tp1", versao_config_v1="outraversao0001")
            atomic_write_csv(sinais_path, POS_RUNNER_V1_COLUMNS, [[linha_sinal[c] for c in POS_RUNNER_V1_COLUMNS]])

            header_banca = [BANCA_HEADER_LABELS.get(c, c) for c in BANCA_COLUMNS]
            linha_banca = {c: "" for c in BANCA_COLUMNS}
            linha_banca.update(
                data_entrada="2026-10-20T10:01:00Z", contrato="ABC", tf="1h",
                tamanho_posicao_usd="10.0", resultado_usd="-1.8", lucro_liquido_pct="-18.0",
                tempo_no_trade_h="2.0", motivo_saida="tp1")
            atomic_write_csv(banca_path, header_banca, [[linha_banca[c] for c in BANCA_COLUMNS]])

            sinais = _carregar_sinais_fechados(sinais_path)
            banca = _carregar_banca(banca_path)
            trades = _juntar(sinais, banca, VERSAO_CONGELADA)

        self.assertEqual(trades, [])

    def test_recusa_quando_contagens_nao_casam(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            sinais_path = base / "pos_runner_v1.csv"
            banca_path = base / "pos_runner_v1_banca.csv"

            linha_sinal = {c: "" for c in POS_RUNNER_V1_COLUMNS}
            linha_sinal.update(
                data="2026-10-20T10:00:00Z", contrato="ABC", tf="1h",
                risco_pct="18.0", motivo_saida="tp1", versao_config_v1=VERSAO_CONGELADA)
            atomic_write_csv(sinais_path, POS_RUNNER_V1_COLUMNS, [[linha_sinal[c] for c in POS_RUNNER_V1_COLUMNS]])
            # banca.csv vazio -- 1 sinal fechado vs 0 trades de banca = inconsistencia
            banca_path.write_text("", encoding="utf-8")

            sinais = _carregar_sinais_fechados(sinais_path)
            banca = _carregar_banca(banca_path)
            with self.assertRaises(ValueError):
                _juntar(sinais, banca, VERSAO_CONGELADA)


if __name__ == "__main__":
    unittest.main()
