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
          holders_tag=None, tags=(), janela_ouro="janela_ouro", entry_id: int = 0) -> cond.SinalResolvido:
    return cond.SinalResolvido(
        entry_id=entry_id, mint=mint, symbol=mint, t_entrada=dia_ts, dif_pareada=dif, gatilho=tuple(gatilho),
        risco_pct=risco_pct, liquidez_usd=liquidez_usd, holders_tag=holders_tag, tags=tuple(tags),
        janela_ouro=janela_ouro,
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

    def test_30_tokens_with_a_strong_planted_edge_passes_both_bootstraps(self) -> None:
        sinais = [_sinal(f"m{i}", 2.0, i * DIA) for i in range(30)]
        r = cond.rodar_h1(sinais)
        self.assertEqual(r.status, "PASS")
        self.assertIsNotNone(r.limite_inferior_dia)
        self.assertIsNotNone(r.limite_inferior_token)
        self.assertGreater(r.limite_inferior_dia, 0.0)
        self.assertGreater(r.limite_inferior_token, 0.0)

    def test_30_tokens_with_pure_noise_around_zero_fails(self) -> None:
        valores = [1.0, -1.0] * 15
        sinais = [_sinal(f"m{i}", v, i * DIA) for i, v in enumerate(valores)]
        r = cond.rodar_h1(sinais)
        self.assertEqual(r.status, "FAIL")

    def test_futility_checked_before_the_full_bootstrap_even_at_n_30(self) -> None:
        sinais = [_sinal(f"m{i}", -1.0, i * DIA) for i in range(30)]
        r = cond.rodar_h1(sinais)
        self.assertEqual(r.status, "FUTIL")
        self.assertIsNone(r.limite_inferior_dia, "futilidade nunca chega a rodar o bootstrap completo")


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


class FormatarTelegramTests(unittest.TestCase):
    def test_insufficient_sample_message_is_exactly_n_over_30(self) -> None:
        rel = cond.RelatorioCondicional(versao="v1", h1=cond.ResultadoH1("AMOSTRA_INSUFICIENTE", 7))
        self.assertEqual(cond.formatar_telegram(rel), "amostra insuficiente (7/30)")

    def test_pass_message_mentions_the_mean_and_candidates(self) -> None:
        h1 = cond.ResultadoH1("PASS", 30, media_dif_pareada=1.2, limite_inferior_dia=0.5, limite_inferior_token=0.4)
        grupo = cond.GrupoExploratorio("H2 tipo de gatilho", "power_candle_rompimento", 12, 2.0, 0.001, True)
        rel = cond.RelatorioCondicional(versao="v1", h1=h1, exploratorias=[grupo])
        texto = cond.formatar_telegram(rel)
        self.assertIn("PASS", texto)
        self.assertIn("1.20", texto)
        self.assertIn("H2 tipo de gatilho/power_candle_rompimento", texto)

    def test_telegram_mentions_the_exclusion_count_when_there_is_at_least_one(self) -> None:
        h1 = cond.ResultadoH1("PASS", 30, media_dif_pareada=1.2, limite_inferior_dia=0.5, limite_inferior_token=0.4)
        excluido = cond.Excluido(entry_id=9, mint="MINTX", symbol="X", motivo="preco_entrada_divergente")
        rel = cond.RelatorioCondicional(versao="v1", h1=h1, excluidos=[excluido])
        self.assertIn("1 excluído", cond.formatar_telegram(rel))

    def test_markdown_lists_each_excluded_signal_with_its_reason(self) -> None:
        h1 = cond.ResultadoH1("AMOSTRA_INSUFICIENTE", 7)
        excluido = cond.Excluido(entry_id=9, mint="MINTX", symbol="X", motivo="candle_divergente")
        rel = cond.RelatorioCondicional(versao="v1", h1=h1, excluidos=[excluido])
        texto = cond.formatar_markdown(rel)
        self.assertIn("entry_id=9 X (MINTX): candle_divergente", texto)


if __name__ == "__main__":
    unittest.main()
