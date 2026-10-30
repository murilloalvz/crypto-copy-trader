"""PEDIDO (PARTE 1 de 2) FASE 2c: analise/condicional.py -- H1 (primaria) e H2-H7 (exploratorias,
Holm), plano pre-registrado (hash travado), e carga real via Storage. Dados sinteticos de efeito
conhecido (H1 detecta edge plantado, nao detecta ruido)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..analise import condicional as cond
from ..config import make_paths
from ..storage import Storage


def _sinal(mint: str, dif: float, dia_ts: float, gatilho=(), risco_pct=20.0, liquidez_usd=100_000.0,
          holders_tag=None, tags=(), janela_ouro="janela_ouro", entry_id: int = 0,
          result_net: float = 1.0, ticket_medio_usd=None, token_signal_seq=None,
          tempo_pico_caixa_s=None) -> cond.SinalResolvido:
    # EMENDA 1 (2026-10-29): `result_net` default != None (so o GATE de presenca de dado em
    # `media_custo_conservador` importa nos testes que nao mencionam custo -- o VALOR de result_net
    # nunca entra na formula, so o risco_pct, ver `media_custo_conservador`).
    return cond.SinalResolvido(
        entry_id=entry_id, mint=mint, symbol=mint, t_entrada=dia_ts, dif_pareada=dif, gatilho=tuple(gatilho),
        risco_pct=risco_pct, liquidez_usd=liquidez_usd, holders_tag=holders_tag, tags=tuple(tags),
        janela_ouro=janela_ouro, result_net=result_net, ticket_medio_usd=ticket_medio_usd,
        token_signal_seq=token_signal_seq, tempo_pico_caixa_s=tempo_pico_caixa_s,
    )


DIA = 86_400.0


class HolmBonferroniTests(unittest.TestCase):
    def test_classic_step_down_example(self) -> None:
        # p ordenados: 0.005, 0.01, 0.03, 0.04 (m=4); limiares 0.0125, 0.01667, 0.025, 0.05
        p = [0.04, 0.01, 0.03, 0.005]
        sig = cond.holm_bonferroni(p)
        self.assertEqual(sig, [False, True, False, True])

    def test_all_pass_when_every_p_is_tiny(self) -> None:
        self.assertEqual(cond.holm_bonferroni([0.0001, 0.0002, 0.0003]), [True, True, True])

    def test_none_pass_when_every_p_is_large(self) -> None:
        self.assertEqual(cond.holm_bonferroni([0.9, 0.8, 0.95]), [False, False, False])


class BootstrapTests(unittest.TestCase):
    def test_constant_positive_effect_always_has_a_positive_lower_bound(self) -> None:
        sinais = [_sinal(f"mint{i}", 2.0, i * DIA) for i in range(30)]
        media, limite = cond.bootstrap_media_e_limite_inferior(sinais, lambda s: s.dia_utc)
        self.assertAlmostEqual(media, 2.0)
        self.assertAlmostEqual(limite, 2.0)

    def test_constant_zero_effect_never_has_a_positive_lower_bound(self) -> None:
        sinais = [_sinal(f"mint{i}", 0.0, i * DIA) for i in range(30)]
        _media, limite = cond.bootstrap_media_e_limite_inferior(sinais, lambda s: s.dia_utc)
        self.assertLessEqual(limite, 0.0)

    def test_p_value_is_near_zero_for_a_strong_planted_effect(self) -> None:
        sinais = [_sinal(f"mint{i}", 3.0, i * DIA) for i in range(20)]
        p = cond.bootstrap_p_valor_unilateral(sinais)
        self.assertLess(p, 0.01)

    def test_p_value_is_near_one_for_a_strong_negative_effect(self) -> None:
        sinais = [_sinal(f"mint{i}", -3.0, i * DIA) for i in range(20)]
        p = cond.bootstrap_p_valor_unilateral(sinais)
        self.assertGreater(p, 0.99)


class RodarH1Tests(unittest.TestCase):
    def test_fewer_than_15_tokens_is_always_insufficient(self) -> None:
        sinais = [_sinal(f"m{i}", 5.0, i * DIA) for i in range(10)]
        self.assertEqual(cond.rodar_h1(sinais).status, "AMOSTRA_INSUFICIENTE")

    def test_futility_stops_early_at_15_tokens(self) -> None:
        sinais = [_sinal(f"m{i}", -1.0, i * DIA) for i in range(15)]  # media -1.0 < -0.5
        r = cond.rodar_h1(sinais)
        self.assertEqual(r.status, "FUTIL")
        self.assertEqual(r.n_tokens, 15)

    def test_between_15_and_30_without_futility_is_still_insufficient(self) -> None:
        sinais = [_sinal(f"m{i}", 0.1, i * DIA) for i in range(20)]  # media positiva, mas n < 30
        self.assertEqual(cond.rodar_h1(sinais).status, "AMOSTRA_INSUFICIENTE")

    def test_30_tokens_with_a_strong_distributed_planted_edge_is_edge_provisorio(self) -> None:
        # EMENDA 1 (2026-10-29, com AJUSTE): edge PLANTADO e DISTRIBUIDO (todo mundo em +2.0, nenhum
        # outlier isolado) -- os 4 criterios (a)-(d) devem passar e o desfecho e EDGE_PROVISORIO.
        sinais = [_sinal(f"m{i}", 2.0, i * DIA) for i in range(30)]
        r = cond.rodar_h1(sinais)
        self.assertEqual(r.status, "EDGE_PROVISORIO")
        self.assertIsNotNone(r.limite_inferior_dia)
        self.assertIsNotNone(r.limite_inferior_token)
        self.assertGreater(r.limite_inferior_dia, 0.0)
        self.assertGreater(r.limite_inferior_token, 0.0)
        self.assertTrue(r.criterio_a_bootstrap)
        self.assertTrue(r.criterio_b_sem_maior_ganho)
        self.assertTrue(r.criterio_c_permutacao)
        self.assertTrue(r.criterio_d_custo_conservador)
        self.assertEqual(r.n_diferencas_positivas, 30)
        self.assertEqual(r.n_diferencas_total, 30)

    def test_a_single_huge_outlier_never_creates_edge_criterio_b(self) -> None:
        # EMENDA 1 item 4: "um outlier de +50R nao pode gerar 'edge'" -- 29 sinais SEM edge nenhum
        # (dif=0.0) + 1 outlier de +50R. A media bruta fica positiva so por causa do outlier, mas o
        # criterio (b) (leave-one-out do MAIOR ganho) deve reprovar (resta media=0.0, nao >0),
        # levando a INCONCLUSIVO (nunca "refutado").
        sinais = [_sinal(f"m{i}", 0.0, i * DIA) for i in range(29)] + [_sinal("outlier", 50.0, 29 * DIA)]
        r = cond.rodar_h1(sinais)
        self.assertEqual(r.status, "INCONCLUSIVO")
        self.assertFalse(r.criterio_b_sem_maior_ganho)
        self.assertAlmostEqual(r.media_sem_maior_ganho, 0.0, places=6)

    def test_30_tokens_with_pure_noise_around_zero_is_inconclusivo_never_refutado(self) -> None:
        valores = [1.0, -1.0] * 15
        sinais = [_sinal(f"m{i}", v, i * DIA) for i, v in enumerate(valores)]
        r = cond.rodar_h1(sinais)
        self.assertEqual(r.status, "INCONCLUSIVO")

    def test_futility_checked_before_the_full_bootstrap_even_at_n_30(self) -> None:
        sinais = [_sinal(f"m{i}", -1.0, i * DIA) for i in range(30)]
        r = cond.rodar_h1(sinais)
        self.assertEqual(r.status, "FUTIL")
        self.assertIsNone(r.limite_inferior_dia, "futilidade nunca chega a rodar o bootstrap completo")

    def test_scaling_up_requires_100_tokens_or_p_below_0_01(self) -> None:
        # EMENDA 1 item 2 (texto do AJUSTE): "escalar mao so com >=100 tokens distintos fechados OU
        # p < 0.01 no teste de permutacao" -- com n=30 e edge forte (p de permutacao bem pequeno),
        # escalar_liberado fica True so pela clausula do p-valor.
        sinais = [_sinal(f"m{i}", 2.0, i * DIA) for i in range(30)]
        r = cond.rodar_h1(sinais)
        self.assertLess(r.p_valor_permutacao, 0.01)
        self.assertTrue(r.escalar_liberado)

    def test_custo_conservador_can_flip_an_edge_that_is_too_thin_to_survive_it(self) -> None:
        # criterio (d): +3%/perna x 2 pernas = 6% extra, equivalente a 100*0.06/risco_pct em R. Com
        # risco_pct=20 isso e 0.30R -- um edge de +0.2R (menor que 0.30R) nao sobrevive.
        sinais = [_sinal(f"m{i}", 0.2, i * DIA, risco_pct=20.0) for i in range(30)]
        r = cond.rodar_h1(sinais)
        self.assertFalse(r.criterio_d_custo_conservador)
        self.assertAlmostEqual(r.media_custo_conservador, 0.2 - 0.30, places=6)


class RobustezH1FuncoesTests(unittest.TestCase):
    """EMENDA 1 (2026-10-29, com AJUSTE do mesmo dia): funcoes puras dos criterios (b)-(d) + relatorio."""

    def test_media_sem_maior_ganho_removes_only_the_single_largest_value(self) -> None:
        sinais = [_sinal("a", 1.0, 0.0), _sinal("b", 1.0, 0.0), _sinal("c", 10.0, 0.0)]
        self.assertAlmostEqual(cond.media_sem_maior_ganho(sinais), 1.0)

    def test_media_aparada_matches_plain_mean_without_outliers(self) -> None:
        self.assertAlmostEqual(cond.media_aparada([1.0, 2.0, 3.0, 4.0, 5.0]), 3.0)

    def test_media_aparada_is_robust_to_a_single_extreme_outlier(self) -> None:
        valores = [1.0] * 19 + [1000.0]  # n=20 -> k=1 de cada ponta, o outlier sai no corte superior
        aparada = cond.media_aparada(valores)
        self.assertLess(aparada, 2.0)

    def test_permutation_test_p_is_tiny_for_a_strong_consistent_effect(self) -> None:
        sinais = [_sinal(f"m{i}", 3.0, i * DIA) for i in range(25)]  # n=25 > 20 -> Monte Carlo
        p = cond.teste_permutacao_sinais(sinais)
        self.assertLess(p, 0.01)

    def test_permutation_test_p_is_large_for_pure_noise(self) -> None:
        valores = [1.0, -1.0] * 10  # n=20 -> exato (enumera 2^20)
        sinais = [_sinal(f"m{i}", v, i * DIA) for i, v in enumerate(valores)]
        p = cond.teste_permutacao_sinais(sinais)
        self.assertGreater(p, 0.3)

    def test_custo_conservador_ignores_signals_without_result_net_missingness_explicit(self) -> None:
        com_dado = _sinal("a", 1.0, 0.0, risco_pct=20.0, result_net=1.0)
        sem_dado = _sinal("b", 1.0, 0.0, risco_pct=20.0, result_net=None)
        so_com_dado = cond.media_custo_conservador([com_dado])
        self.assertAlmostEqual(cond.media_custo_conservador([com_dado, sem_dado]), so_com_dado)

    def test_spearman_is_strongly_positive_for_a_monotonic_relationship(self) -> None:
        xs = list(range(20))
        ys = [float(x) * 2.0 for x in xs]
        rho, p = cond.spearman(xs, ys)
        self.assertGreater(rho, 0.99)
        self.assertLess(p, 0.01)

    def test_spearman_is_near_zero_for_unrelated_data(self) -> None:
        xs = [0, 1, 2, 3, 4, 5, 6, 7]
        ys = [3, 1, 4, 1, 5, 9, 2, 6]
        rho, _p = cond.spearman(xs, ys)
        self.assertLess(abs(rho), 0.6)

    def test_mann_whitney_detects_a_clear_shift_between_two_groups(self) -> None:
        a = [1.0] * 10
        b = [10.0] * 10
        _u, p = cond.mann_whitney_u(a, b)
        self.assertLess(p, 0.01)

    def test_mann_whitney_sees_no_difference_for_identical_distributions(self) -> None:
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [1.0, 2.0, 3.0, 4.0, 5.0]
        _u, p = cond.mann_whitney_u(a, b)
        self.assertGreater(p, 0.5)


class H10H11H12Tests(unittest.TestCase):
    """EMENDA 1 (2026-10-29, com AJUSTE): H10 (Spearman, continuo, R realizado) / H11 (Mann-Whitney,
    mediana exata de ticket) / H12 (1o sinal do token vs 2o+, bootstrap por token) -- geracao de
    hipoteses, nunca confirmatorias."""

    def test_h10_is_none_below_10_tokens_with_both_fields_present(self) -> None:
        sinais = [_sinal(f"m{i}", 1.0, i * DIA, tempo_pico_caixa_s=float(i)) for i in range(5)]
        self.assertIsNone(cond.h10_velocidade_queda(sinais))

    def test_h10_detects_a_planted_monotonic_relationship(self) -> None:
        sinais = [_sinal(f"m{i}", 0.6, i * DIA, risco_pct=20.0, result_net=0.2 * (i + 1),
                         tempo_pico_caixa_s=float(i) * 3600.0) for i in range(15)]
        g = cond.h10_velocidade_queda(sinais)
        self.assertIsNotNone(g)
        self.assertIn("rho=", g.estatistica)
        self.assertTrue(g.p_valor < 0.05)

    def test_h11_is_none_below_10_tokens_per_side(self) -> None:
        sinais = [_sinal(f"m{i}", 1.0, i * DIA, ticket_medio_usd=float(i)) for i in range(10)]
        self.assertIsNone(cond.h11_ticket_medio(sinais))

    def test_h11_detects_a_clear_shift_between_below_and_above_median_tickets(self) -> None:
        abaixo = [_sinal(f"low{i}", 0.1, i * DIA, ticket_medio_usd=100.0) for i in range(12)]
        acima = [_sinal(f"high{i}", 5.0, i * DIA, ticket_medio_usd=10_000.0) for i in range(12)]
        g = cond.h11_ticket_medio(abaixo + acima)
        self.assertIsNotNone(g)
        self.assertLess(g.p_valor, 0.01)

    def test_h12_splits_by_token_signal_seq_and_blocks_the_bootstrap_by_token(self) -> None:
        primeiros = [_sinal(f"m{i}", 2.0, i * DIA, token_signal_seq=1) for i in range(12)]
        # mesmo TOKEN repetido 3x no grupo "2o ou posterior" -- bloco por token evita que isso infle
        # artificialmente a significancia (pseudo-replicacao de um unico token hiperativo).
        posteriores = [_sinal("hiperativo", 2.0, i * DIA, token_signal_seq=2, entry_id=i) for i in range(30)]
        resultado = cond.h12_ordem_sinal_token(primeiros + posteriores)
        nomes = {g.grupo for g in resultado}
        self.assertIn("1o sinal do token", nomes)
        # "2o ou posterior" tem n_tokens=1 (um unico mint hiperativo) -- nunca atinge o minimo de 10.
        self.assertNotIn("2o ou posterior", nomes)


class RodarExploratoriasTests(unittest.TestCase):
    def test_groups_below_10_tokens_are_never_reported(self) -> None:
        sinais = [_sinal(f"m{i}", 1.0, i * DIA, gatilho=("reacao_suporte",)) for i in range(5)]
        self.assertEqual(cond.rodar_exploratorias(sinais), [])

    def test_a_group_with_a_strong_planted_edge_becomes_a_holm_candidate(self) -> None:
        fortes = [_sinal(f"forte{i}", 3.0, i * DIA, gatilho=("power_candle_rompimento",)) for i in range(12)]
        fracos_a = [_sinal(f"fraco_a{i}", 0.0, i * DIA, gatilho=("reacao_suporte",)) for i in range(12)]
        fracos_b = [_sinal(f"fraco_b{i}", 0.0, i * DIA, gatilho=("rompimento_volume",)) for i in range(12)]
        resultado = cond.rodar_exploratorias(fortes + fracos_a + fracos_b)
        candidato = next(g for g in resultado if g.grupo == "power_candle_rompimento")
        self.assertTrue(candidato.significativo_holm)
        # os outros gatilhos (mesma hipotese H2, grupos mutuamente exclusivos de verdade -- os sinais
        # "fracos" nunca disparam power_candle_rompimento) ficam sem o efeito plantado.
        outros_gatilhos = [g for g in resultado if g.hipotese == "H2 tipo de gatilho" and g.grupo != "power_candle_rompimento"]
        self.assertTrue(outros_gatilhos)
        self.assertTrue(all(not g.significativo_holm for g in outros_gatilhos))

    def test_holders_indisponivel_never_counts_in_either_h5_group(self) -> None:
        sinais = (
            [_sinal(f"concentrado{i}", 1.0, i * DIA, holders_tag="HOLDER_CONCENTRADO") for i in range(10)]
            + [_sinal(f"limpo{i}", 1.0, i * DIA, holders_tag=None) for i in range(10)]
            + [_sinal(f"indisp{i}", 1.0, i * DIA, holders_tag="holders_indisponivel") for i in range(10)]
        )
        resultado = cond.rodar_exploratorias(sinais)
        grupos_h5 = {g.grupo: g.n_tokens for g in resultado if g.hipotese == "H5 holder concentrado"}
        self.assertEqual(grupos_h5.get("sim"), 10)
        self.assertEqual(grupos_h5.get("nao"), 10)


class CarregarSinaisResolvidosTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="condicional_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _inserir_sinal_v1(self, entry_id_esperado: int = 1) -> int:
        signal_id = self.storage.pr1_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": '["reacao_suporte"]', "tags": '["base_ge_2d"]',
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
            "entry_price": 100.0, "stop": 80.0, "liquidez_usd": 50_000.0, "holders_tag": None,
        })
        self.assertIsNotNone(signal_id)
        return signal_id

    def test_only_rows_with_dif_pareada_already_computed_are_loaded(self) -> None:
        signal_id = self._inserir_sinal_v1()
        self.storage.pr_trajetoria_upsert("v1", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                          mint="MINT1", symbol="CAT", t_entrada=5_000.0, preco_entrada=100.0,
                                          risco_pct=20.0, r_unidade=20.0, fonte_candle="gt")
        self.storage.pr_baseline_upsert("v1", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                        mint="MINT1", symbol="CAT", n_controles=5, controles_json="[]")
        # ainda sem dif_pareada: nao entra
        self.assertEqual(cond.carregar_sinais_resolvidos(self.storage, "v1"), [])
        self.storage.pr_baseline_upsert("v1", signal_id, 1.0, dif_pareada=0.7, r_controle_medio=0.3, r_sinal=1.0)
        sinais = cond.carregar_sinais_resolvidos(self.storage, "v1")
        self.assertEqual(len(sinais), 1)
        s = sinais[0]
        self.assertEqual(s.mint, "MINT1")
        self.assertAlmostEqual(s.dif_pareada, 0.7)
        self.assertAlmostEqual(s.t_entrada, 5_000.0)
        self.assertAlmostEqual(s.risco_pct, 20.0)
        self.assertIn("reacao_suporte", s.gatilho)
        self.assertIn("base_ge_2d", s.tags)

    def _resolver(self, signal_id: int, dif: float = 0.7) -> None:
        self.storage.pr_trajetoria_upsert("v1", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                          mint="MINT1", symbol="CAT", t_entrada=5_000.0, preco_entrada=100.0,
                                          risco_pct=20.0, r_unidade=20.0, fonte_candle="gt")
        self.storage.pr_baseline_upsert("v1", signal_id, dif, chain="solana", pool="POOL1", tf="1h",
                                        mint="MINT1", symbol="CAT", n_controles=5, controles_json="[]",
                                        dif_pareada=dif, r_controle_medio=0.3, r_sinal=dif + 0.3)

    def test_a_signal_whose_alert_price_diverges_from_the_recorded_one_is_excluded_with_reason(self) -> None:
        # DIAGNOSTICO 2026-10-27 (McRib): entry_price_alerta (preco do alerta) != entry_price (gravado
        # depois do fill real) em mais de 1% -- regra de exclusao pre-declarada
        # (PLANO_ANALISE_PREREGISTRADO.md "Exclusao pre-declarada").
        signal_id = self.storage.pr1_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "fechado", "entry_price": 440_000.0, "stop": 440_000.0,
            "entry_price_alerta": 44_100_000.0,  # McRib: alerta mostrou 44,1M, gravado 440k
        })
        self._resolver(signal_id)
        sinais, excluidos = cond.carregar_sinais_e_excluidos(self.storage, "v1")
        self.assertEqual(sinais, [])
        self.assertEqual(len(excluidos), 1)
        self.assertEqual(excluidos[0].motivo, "preco_entrada_divergente")
        self.assertEqual(excluidos[0].mint, "MINT1")
        # compat: carregar_sinais_resolvidos tambem reflete a exclusao
        self.assertEqual(cond.carregar_sinais_resolvidos(self.storage, "v1"), [])

    def test_a_signal_whose_alert_price_matches_the_recorded_one_within_tolerance_is_not_excluded(self) -> None:
        signal_id = self.storage.pr1_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "fechado", "entry_price": 100.5, "stop": 80.0,
            "entry_price_alerta": 100.0,  # 0,5% de diferenca -- dentro da tolerancia de 1%
        })
        self._resolver(signal_id)
        sinais, excluidos = cond.carregar_sinais_e_excluidos(self.storage, "v1")
        self.assertEqual(len(sinais), 1)
        self.assertEqual(excluidos, [])

    def test_a_signal_with_no_entry_price_alerta_recorded_is_never_excluded_for_missing_data(self) -> None:
        signal_id = self._inserir_sinal_v1()  # sem entry_price_alerta (sinal "antigo", coluna NULL)
        self._resolver(signal_id)
        sinais, excluidos = cond.carregar_sinais_e_excluidos(self.storage, "v1")
        self.assertEqual(len(sinais), 1)
        self.assertEqual(excluidos, [])

    def test_a_signal_with_a_confirmed_dexpaprika_divergence_on_the_trigger_candle_is_excluded(self) -> None:
        # DIAGNOSTICO 2026-10-27 (yagi): qualquer linha confirmada em pr1_dexpaprika_divergencias no
        # candle do gatilho (ts_fechamento) exclui o sinal, mesmo sem divergencia de preco de entrada.
        signal_id = self._inserir_sinal_v1()
        self.storage.pr1_dexpaprika_divergencia_insert(
            0.0, "solana", "POOL1", "MINT1", "CAT", "1h", 1_000, "high", 2_600_000.0, 227_000.0, 91.3,
            "abc123")
        self._resolver(signal_id)
        sinais, excluidos = cond.carregar_sinais_e_excluidos(self.storage, "v1")
        self.assertEqual(sinais, [])
        self.assertEqual(len(excluidos), 1)
        self.assertEqual(excluidos[0].motivo, "candle_divergente")

    def test_a_signal_tagged_risco_irrealista_is_excluded_with_reason(self) -> None:
        # PATCH 2026-10-27 (item 3 do pedido): risco real < 3% (live.py: _confirmar_entrada) e tagueado
        # `risco_irrealista` -- nunca bloqueia o paper, so fica fora de H1-H8.
        signal_id = self.storage.pr1_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": '["risco_irrealista"]',
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "aberto",
            "entry_price": 441_000.0, "stop": 440_000.0,
        })
        self._resolver(signal_id)
        sinais, excluidos = cond.carregar_sinais_e_excluidos(self.storage, "v1")
        self.assertEqual(sinais, [])
        self.assertEqual(len(excluidos), 1)
        self.assertEqual(excluidos[0].motivo, "risco_irrealista")

    def test_a_signal_tagged_contaminado_candle_is_excluded_with_reason(self) -> None:
        # PATCH 2026-10-27 (item 2, pos-auditoria): marcacao retroativa explicita
        # (scripts/marcar_contaminados.py), independente de onde no ciclo de vida o candle corrompido
        # apareceu (nao so gatilho/entrada -- os outros 3 criterios).
        signal_id = self.storage.pr1_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": '["contaminado_candle"]',
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
            "entry_price": 100.0, "stop": 80.0,
        })
        self._resolver(signal_id)
        sinais, excluidos = cond.carregar_sinais_e_excluidos(self.storage, "v1")
        self.assertEqual(sinais, [])
        self.assertEqual(len(excluidos), 1)
        self.assertEqual(excluidos[0].motivo, "contaminado_candle")

    def test_a_signal_tagged_entrada_atrasada_is_excluded_by_default_but_kept_for_sensitivity(self) -> None:
        """PEDIDO 2026-10-30 (FASE 1c): mesma exclusao de risco_irrealista/contaminado_candle por
        padrao; `excluir_entrada_atrasada=False` devolve o sinal, so pra medir sensibilidade de H1."""
        signal_id = self.storage.pr1_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": '["entrada_atrasada"]',
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
            "entry_price": 100.0, "stop": 80.0,
        })
        self._resolver(signal_id)
        sinais, excluidos = cond.carregar_sinais_e_excluidos(self.storage, "v1")
        self.assertEqual(sinais, [])
        self.assertEqual(len(excluidos), 1)
        self.assertEqual(excluidos[0].motivo, "entrada_atrasada")
        sinais_sens, excluidos_sens = cond.carregar_sinais_e_excluidos(self.storage, "v1",
                                                                       excluir_entrada_atrasada=False)
        self.assertEqual(len(sinais_sens), 1)
        self.assertEqual(excluidos_sens, [])

    def test_v2_is_never_excluded_by_the_dexpaprika_criterion_since_it_has_no_cross_check_of_its_own(self) -> None:
        signal_id = self.storage.pr2_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v2": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "fechado", "entry_price": 100.0, "stop": 80.0, "so_v2": 0,
        })
        self.storage.pr1_dexpaprika_divergencia_insert(
            0.0, "solana", "POOL1", "MINT1", "CAT", "1h", 1_000, "high", 2_600_000.0, 227_000.0, 91.3,
            "abc123")
        self.storage.pr_trajetoria_upsert("v2", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                          mint="MINT1", symbol="CAT", t_entrada=5_000.0, preco_entrada=100.0,
                                          risco_pct=20.0, r_unidade=20.0, fonte_candle="gt")
        self.storage.pr_baseline_upsert("v2", signal_id, 0.7, chain="solana", pool="POOL1", tf="1h",
                                        mint="MINT1", symbol="CAT", n_controles=5, controles_json="[]",
                                        dif_pareada=0.7, r_controle_medio=0.3, r_sinal=1.0)
        sinais, excluidos = cond.carregar_sinais_e_excluidos(self.storage, "v2")
        self.assertEqual(len(sinais), 1)
        self.assertEqual(excluidos, [])


class GarantirPlanoRegistradoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="plano_"))
        self.storage = Storage(make_paths(self.tmp))
        self.plano = self.tmp / "PLANO_TESTE.md"
        self.plano.write_text("# plano v1\nconteudo original\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_call_registers_the_hash(self) -> None:
        self.assertIsNone(self.storage.get_meta(cond.META_KEY_HASH))
        h = cond.garantir_plano_registrado(self.storage, self.plano)
        self.assertEqual(self.storage.get_meta(cond.META_KEY_HASH), h)

    def test_unchanged_file_never_raises_on_later_calls(self) -> None:
        cond.garantir_plano_registrado(self.storage, self.plano)
        cond.garantir_plano_registrado(self.storage, self.plano)  # nao levanta

    def test_editing_the_file_after_registration_raises(self) -> None:
        cond.garantir_plano_registrado(self.storage, self.plano)
        self.plano.write_text("# plano v1\nconteudo EDITADO depois de registrado\n", encoding="utf-8")
        with self.assertRaises(cond.PlanoAlteradoError):
            cond.garantir_plano_registrado(self.storage, self.plano)

    def test_registrar_emenda_updates_the_hash_and_keeps_an_append_only_history(self) -> None:
        # EMENDA 1 (2026-10-29): re-registro EXPLICITO -- nunca automatico dentro de `executar`/
        # `garantir_plano_registrado` (que so recusaria o mismatch). So `--registrar-emenda` chama isto.
        h_original = cond.garantir_plano_registrado(self.storage, self.plano)
        self.plano.write_text("# plano v1\nEMENDA 1 (2026-10-29)\n", encoding="utf-8")
        with self.assertRaises(cond.PlanoAlteradoError):
            cond.garantir_plano_registrado(self.storage, self.plano)
        anterior, novo = cond.registrar_emenda(self.storage, self.plano)
        self.assertEqual(anterior, h_original)
        self.assertNotEqual(novo, h_original)
        cond.garantir_plano_registrado(self.storage, self.plano)  # nao levanta mais
        import json as _json
        historico = _json.loads(self.storage.get_meta("plano_analise_emendas"))
        self.assertEqual(len(historico), 1)
        self.assertEqual(historico[0]["hash_anterior"], h_original)
        self.assertEqual(historico[0]["hash_novo"], novo)


class FormatarTelegramTests(unittest.TestCase):
    def test_insufficient_sample_message_is_exactly_n_over_30(self) -> None:
        rel = cond.RelatorioCondicional(versao="v1", h1=cond.ResultadoH1("AMOSTRA_INSUFICIENTE", 7))
        self.assertEqual(cond.formatar_telegram(rel), "amostra insuficiente (7/30)")

    def test_edge_provisorio_message_mentions_the_mean_and_candidates(self) -> None:
        h1 = cond.ResultadoH1("EDGE_PROVISORIO", 30, media_dif_pareada=1.2, limite_inferior_dia=0.5,
                              limite_inferior_token=0.4)
        grupo = cond.GrupoExploratorio("H2 tipo de gatilho", "power_candle_rompimento", 12, 2.0, 0.001, True)
        rel = cond.RelatorioCondicional(versao="v1", h1=h1, exploratorias=[grupo])
        texto = cond.formatar_telegram(rel)
        self.assertIn("EDGE_PROVISORIO", texto)
        self.assertIn("1.20", texto)
        self.assertIn("H2 tipo de gatilho/power_candle_rompimento", texto)

    def test_telegram_mentions_the_exclusion_count_when_there_is_at_least_one(self) -> None:
        h1 = cond.ResultadoH1("EDGE_PROVISORIO", 30, media_dif_pareada=1.2, limite_inferior_dia=0.5,
                              limite_inferior_token=0.4)
        excluido = cond.Excluido(entry_id=9, mint="MINTX", symbol="X", motivo="preco_entrada_divergente")
        rel = cond.RelatorioCondicional(versao="v1", h1=h1, excluidos=[excluido])
        self.assertIn("1 excluído", cond.formatar_telegram(rel))

    def test_markdown_lists_each_excluded_signal_with_its_reason(self) -> None:
        h1 = cond.ResultadoH1("AMOSTRA_INSUFICIENTE", 7)
        excluido = cond.Excluido(entry_id=9, mint="MINTX", symbol="X", motivo="candle_divergente")
        rel = cond.RelatorioCondicional(versao="v1", h1=h1, excluidos=[excluido])
        texto = cond.formatar_markdown(rel)
        self.assertIn("entry_id=9 X (MINTX): candle_divergente", texto)


class H13FuncoesTests(unittest.TestCase):
    """PEDIDO 2026-10-29 (auditoria+sensibilidade+sombra+radar), item 3: funcoes puras de H13 --
    `_faixas_h13`/`_spearman_bootstrap_p_por_token` (bootstrap/breakdown por token, sem storage)."""

    def test_faixas_h13_groups_by_range_and_respects_the_n10_gate(self) -> None:
        pares = ([(5, 1.0, f"a{i}") for i in range(12)] + [(9, 2.0, f"b{i}") for i in range(3)]
                + [(15, 3.0, f"c{i}") for i in range(10)])
        faixas = cond._faixas_h13(pares)
        self.assertIsNotNone(faixas["4-7"])
        self.assertEqual(faixas["4-7"][0], 12)
        self.assertAlmostEqual(faixas["4-7"][1], 1.0)
        self.assertIsNone(faixas["8-11"], "so 3 tokens distintos -- abaixo do minimo de 10")
        self.assertIsNotNone(faixas[">=12"])
        self.assertEqual(faixas[">=12"][0], 10)

    def test_bootstrap_p_por_token_is_small_for_a_strong_consistent_relationship(self) -> None:
        pares = [(float(i), float(i) * 2.0, f"m{i}") for i in range(15)]
        p = cond._spearman_bootstrap_p_por_token(pares)
        self.assertLess(p, 0.05)

    def test_bootstrap_p_por_token_is_large_for_unrelated_data(self) -> None:
        pares = [(0.0, 3.0, "m0"), (1.0, 1.0, "m1"), (2.0, 4.0, "m2"), (3.0, 1.0, "m3"),
                (4.0, 5.0, "m4"), (5.0, 9.0, "m5"), (6.0, 2.0, "m6"), (7.0, 6.0, "m7"),
                (8.0, 0.0, "m8"), (9.0, 1.0, "m9"), (10.0, 7.0, "m10"), (11.0, 3.0, "m11")]
        p = cond._spearman_bootstrap_p_por_token(pares)
        self.assertGreater(p, 0.2)

    def test_bootstrap_p_por_token_is_not_dominated_by_a_single_hyperactive_token(self) -> None:
        """Mesma logica anti-pseudo-replicacao de H12: um UNICO token com dezenas de pares
        (x,y) correlacionados nunca pode, por si so, inflar a significancia -- o bloco e o TOKEN."""
        pares = [(float(i), float(i), "hiperativo") for i in range(50)]
        pares += [(float(i), -float(i), f"m{i}") for i in range(9)]   # 9 tokens com relacao OPOSTA
        p = cond._spearman_bootstrap_p_por_token(pares)
        # com blocos por token (10 tokens: 1 hiperativo positivo + 9 negativos), a maioria dos
        # bootstraps inclui pelo menos um token negativo -- p nao deve ficar artificialmente pequeno
        # so porque 1 token concentra 50/59 dos PARES individuais.
        self.assertGreater(p, 0.05)


class RodarH13Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="h13_storage_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _v1_fechado(self, mint: str, caixa_candles: int, result_net: float, risco_pct: float = 20.0) -> None:
        entry_price = 100.0
        stop = entry_price * (1.0 - risco_pct / 100.0)
        sid = self.storage.pr1_insert_signal({
            "chain": "solana", "pool": f"POOL-{mint}", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": mint, "symbol": mint, "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "fechado", "entry_price": entry_price, "stop": stop,
            "caixa_candles": caixa_candles, "result_net": result_net,
        })
        self.assertIsNotNone(sid)

    def _sombra_base4_fechado(self, mint: str, caixa_candles: int, result_net: float, risco_pct: float = 20.0) -> None:
        sid = self.storage.pr_sombra_insert({
            "versao": "sombra:base_min4", "chain": "solana", "pool": f"POOL-{mint}", "tf": "1h",
            "mint": mint, "symbol": mint, "ts_fechamento": 1_000, "status": "fechado",
            "criado_ts": 0.0, "atualizado_ts": 0.0, "risco_pct": risco_pct, "caixa_candles": caixa_candles,
            "result_net": result_net,
        })
        self.assertIsNotNone(sid)

    def test_rodar_h13_is_none_below_10_tokens_total(self) -> None:
        for i in range(5):
            self._v1_fechado(f"m{i}", 12, 0.1 * i)
        self.assertIsNone(cond.rodar_h13(self.storage))

    def test_rodar_h13_pools_v1_and_sombra_base_min4_and_detects_the_planted_relationship(self) -> None:
        for i in range(10):
            self._sombra_base4_fechado(f"s{i}", 4 + i % 4, 0.02 * (i + 1))   # box 4-7, R baixo
        for i in range(10):
            self._v1_fechado(f"v{i}", 14 + i, 0.30 + 0.03 * i)               # box 14..23, R alto
        r = cond.rodar_h13(self.storage)
        self.assertIsNotNone(r)
        self.assertEqual(r.n_tokens, 20)
        self.assertGreater(r.rho, 0.5)
        self.assertLess(r.p_valor, 0.05)
        self.assertIsNotNone(r.por_faixa["4-7"])
        self.assertIsNotNone(r.por_faixa[">=12"])

    def test_rodar_h13_ignores_signals_without_caixa_candles_or_result_net(self) -> None:
        for i in range(10):
            self._v1_fechado(f"v{i}", 12 + i, 0.1 * i)
        # sinal sem caixa_candles (sinal antigo, coluna NULL) -- nunca inventa um valor
        self.storage.pr1_insert_signal({
            "chain": "solana", "pool": "POOL-SEMBOX", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "SEMBOX", "symbol": "SEMBOX", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "fechado", "entry_price": 100.0, "stop": 80.0, "result_net": 0.5,
        })
        r = cond.rodar_h13(self.storage)
        self.assertIsNotNone(r)
        self.assertEqual(r.n_tokens, 10, "SEMBOX nunca entra -- caixa_candles ausente")


class RodarH14Tests(unittest.TestCase):
    """PEDIDO 2026-10-29 (item 4, Radar): H14 -- acompanhando vs ignorar, MFE/R mecanico 72h."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="h14_storage_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _radar_fechado(self, mint: str, decisao: str, mfe_r: float) -> None:
        now = 0.0
        rid = self.storage.pr_radar_insert({
            "chain": "solana", "pool": f"POOL-{mint}", "tf": "1h", "mint": mint, "symbol": mint,
            "ts_fechamento": 1_000, "status": "fechado", "criado_ts": now, "atualizado_ts": now,
            "mfe_r": mfe_r,
        })
        self.assertIsNotNone(rid)
        self.storage.pr_radar_update(rid, decisao=decisao, decisao_ts=now)

    def test_rodar_h14_is_none_below_10_tokens_per_side(self) -> None:
        for i in range(10):
            self._radar_fechado(f"a{i}", "acompanhando", 1.0)
        for i in range(5):
            self._radar_fechado(f"b{i}", "ignorar", 0.5)
        self.assertIsNone(cond.rodar_h14(self.storage))

    def test_rodar_h14_detects_a_clear_shift_between_groups(self) -> None:
        for i in range(12):
            self._radar_fechado(f"a{i}", "acompanhando", 5.0)
        for i in range(12):
            self._radar_fechado(f"b{i}", "ignorar", 0.1)
        r = cond.rodar_h14(self.storage)
        self.assertIsNotNone(r)
        self.assertEqual(r.n_acompanhando, 12)
        self.assertEqual(r.n_ignorar, 12)
        self.assertLess(r.p_valor, 0.01)

    def test_rodar_h14_ignores_rows_without_decisao_or_mfe_r(self) -> None:
        for i in range(10):
            self._radar_fechado(f"a{i}", "acompanhando", 1.0)
        for i in range(10):
            self._radar_fechado(f"b{i}", "ignorar", 0.5)
        # linha sem decisao (operador nunca clicou) -- nunca entra em nenhum dos 2 lados
        rid = self.storage.pr_radar_insert({
            "chain": "solana", "pool": "POOL-SEMDECISAO", "tf": "1h", "mint": "SEMDECISAO",
            "symbol": "SEMDECISAO", "ts_fechamento": 1_000, "status": "fechado",
            "criado_ts": 0.0, "atualizado_ts": 0.0, "mfe_r": 9.0,
        })
        self.assertIsNotNone(rid)
        r = cond.rodar_h14(self.storage)
        self.assertIsNotNone(r)
        self.assertEqual(r.n_acompanhando, 10)
        self.assertEqual(r.n_ignorar, 10)


if __name__ == "__main__":
    unittest.main()
