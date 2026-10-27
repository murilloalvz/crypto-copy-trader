"""PEDIDO (PARTE 1 de 2) FASES 1-2: integracao ao vivo de pr_trajetoria/pr_baseline (sobre o MESMO
cenario de ENTRADA+TP1+stop ja usado pelos testes de equivalencia da V1) -- nunca muda sinal/alerta/
banca oficial, e SEM_EVIDENCIA desliga por completo. A V1 roda com a V2 em paralelo por padrao (como o
resto do bot), entao a maioria dos cenarios produz 1 linha de cada versao -- os testes sempre filtram
por `versao` em vez de assumir 1 linha so."""

from __future__ import annotations

import json
import unittest

from ..http import CallBudget
from ..pos_runner.candles import Bar
from ..pos_runner.live import event_v1_from_json
from ..pos_runner.quotes import REFERENCE_POOLS, SOL_MINT
from .test_pos_runner import GRAD, H, textbook
from .test_pos_runner_live import LiveHarness, start_tracking


def _run_entrada(h: LiveHarness) -> None:
    start_tracking(h)
    h.run_hours(18)   # 17h (mesmo cenario de EntradaTests._run_to_entrada) + 1h p/ a entrada preencher de verdade


def _run_tp1_then_stop(h: LiveHarness) -> None:
    """MESMO cenario de test_pos_runner_v1_live.EntradaTests._tp1_then_stop."""
    s = textbook(start_flat=0)
    t = s.bars[-1].ts + H
    extra = [
        Bar(t, 400_000, 420_000, 395_000, 410_000, 1_000.0),
        Bar(t + H, 405_000, 1_050_000, 400_000, 620_000, 1_000.0),
        Bar(t + 2 * H, 700_000, 710_000, 690_000, 705_000, 1_000.0),
        Bar(t + 3 * H, 705_000, 710_000, 151_000, 152_000, 1_000.0),
    ]
    h.world.add_series("POOL1", "1h", s.bars + extra)
    h.list_pool()
    h.tick()
    h.verifier.step()
    h.tick()
    ref_pool, _side = REFERENCE_POOLS[SOL_MINT]
    h.world.series[(ref_pool, "1h")] = [Bar(GRAD - 30 * H + k * H, 150.0, 150.0, 150.0, 150.0, 1e6) for k in range(400)]
    for _ in range(27):
        h.clock.advance(H)
        h.tick()
        h.live.http.arm(CallBudget(10), 1, 10)
        h.live.quotes.series(SOL_MINT, GRAD, h.clock())
        h.live.http.disarm()


def _v1_row(rows):
    return next(r for r in rows if r["versao"] == "v1")


class TrajetoriaIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_trajetoria_row_is_created_for_the_real_entry_without_touching_the_official_signal(self) -> None:
        _run_entrada(self.h)
        sinal = self.h.storage.pr1_signals()[0]
        rows = self.h.storage.pr_trajetoria_all()
        self.assertEqual({r["versao"] for r in rows}, {"v1", "v2"}, "FASE 1: trajetoria para V1 E V2")
        row = _v1_row(rows)
        self.assertEqual(row["entry_id"], sinal["id"])
        self.assertEqual(row["pool"], "POOL1")
        self.assertAlmostEqual(row["preco_entrada"], sinal["entry_price"])
        self.assertAlmostEqual(row["risco_pct"], 100.0 * (1.0 - sinal["stop"] / sinal["entry_price"]))
        self.assertIsNotNone(row["ret_r_1h"])
        self.assertIsNone(row["ret_r_72h"], "poucas horas de candle ainda -- nunca interpolado")
        self.assertEqual(row["fechado"], 0)
        # o sinal oficial continua intacto (medicao nunca altera V1)
        self.assertEqual(dict(self.h.storage.pr1_signals()[0]), dict(sinal))

    def test_tocou_tp1_and_fechado_flag_after_72h_of_candles(self) -> None:
        _run_tp1_then_stop(self.h)
        row = _v1_row(self.h.storage.pr_trajetoria_all())
        self.assertEqual(row["tocou_tp1"], 1)
        # 27h de candles depois da entrada (bem menos que 72h): ainda nao fechou.
        self.assertEqual(row["fechado"], 0)

    def test_sem_evidencia_produces_no_trajetoria_or_baseline_rows_at_all(self) -> None:
        h = LiveHarness(sem_evidencia=True)
        try:
            _run_entrada(h)
            self.assertEqual(h.storage.pr_trajetoria_all(), [])
            self.assertEqual(h.storage.pr_baseline_all(), [])
            # a V1 continua funcionando normalmente com a flag desligada
            self.assertEqual(len(h.storage.pr1_signals()), 1)
        finally:
            h.close()

    def test_csv_export_includes_the_trajetoria_row(self) -> None:
        _run_entrada(self.h)
        self.h.storage.export_csvs(force=True)
        content = self.h.storage.paths.pos_runner_v1_trajetoria_csv.read_text(encoding="utf-8")
        self.assertIn("v1", content)
        self.assertIn("v2", content)
        self.assertIn("POOL1", content)


class BaselineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_baseline_row_is_created_with_controls_sampled_from_cached_candles(self) -> None:
        _run_entrada(self.h)
        rows = self.h.storage.pr_baseline_all()
        self.assertEqual({r["versao"] for r in rows}, {"v1", "v2"})
        row = _v1_row(rows)
        self.assertGreaterEqual(row["n_controles"], 3)
        self.assertIsNone(row["dif_pareada"], "ainda sem desfecho dos controles/sinal -- nunca parcial")

    def test_never_samples_the_real_trigger_candle_as_a_control(self) -> None:
        _run_entrada(self.h)
        sinal = self.h.storage.pr1_signals()[0]
        ev = event_v1_from_json(sinal["event_json"])
        controles = json.loads(_v1_row(self.h.storage.pr_baseline_all())["controles_json"])
        self.assertNotIn(ev.idx, [c["idx"] for c in controles])

    def test_dif_pareada_is_computed_once_every_control_and_the_signal_resolve(self) -> None:
        _run_tp1_then_stop(self.h)   # fecha o sinal real (TP1 + stop)
        sinal = self.h.storage.pr1_signals()[0]
        self.assertEqual(sinal["status"], "fechado")
        # os controles sorteados ainda estao "em_aberto" dentro dos candles do fixture -- acrescenta mais
        # alguns candles (so pra este teste fechar os controles de verdade, nunca altera pr1_signals).
        bars = self.h.live._bars_de("POOL1", "1h")  # noqa: SLF001
        last_ts = bars[-1].ts
        extra = [(last_ts + 3600 * (i + 1), 1000.0, 1000.0, 1000.0, 1000.0, 1.0, False) for i in range(5)]
        self.h.storage.pr_append_bars("POOL1", "1h", extra, fonte="gt")
        bars2 = self.h.live._bars_de("POOL1", "1h")  # noqa: SLF001
        row = self.h.storage.pr_pool("POOL1")
        self.h.live._atualizar_baseline("v1", sinal, row, bars2, self.h.live.params_v1, self.h.clock())  # noqa: SLF001
        resultado = self.h.storage.pr_baseline_get("v1", sinal["id"])
        self.assertIsNotNone(resultado["dif_pareada"])
        self.assertAlmostEqual(resultado["dif_pareada"], resultado["r_sinal"] - resultado["r_controle_medio"])
        controles = json.loads(resultado["controles_json"])
        self.assertTrue(all(c["status"] != "pendente" for c in controles))

    def test_seed_is_deterministic_across_a_fresh_recompute(self) -> None:
        _run_entrada(self.h)
        baseline1 = json.loads(_v1_row(self.h.storage.pr_baseline_all())["controles_json"])
        sinal = self.h.storage.pr1_signals()[0]
        # forca o storage a "esquecer" (apaga as linhas) e recalcula do zero sobre o MESMO entry_id/versao
        self.h.storage._db.execute("DELETE FROM pr_baseline")  # noqa: SLF001 -- so para forcar um novo sorteio
        row = self.h.storage.pr_pool("POOL1")
        bars = self.h.live._bars_de("POOL1", "1h")  # noqa: SLF001
        self.h.live._atualizar_baseline("v1", sinal, row, bars, self.h.live.params_v1, self.h.clock())  # noqa: SLF001
        baseline2 = json.loads(_v1_row(self.h.storage.pr_baseline_all())["controles_json"])
        self.assertEqual([c["idx"] for c in baseline1], [c["idx"] for c in baseline2])


class EntryPriceAlertaTests(unittest.TestCase):
    """DIAGNOSTICO 2026-10-27 (McRib): `entry_price_alerta` e o preco PROVISORIO do alerta ENTRADA
    (ev.data["close"]), gravado 1x e nunca sobrescrito -- ao contrario de `entry_price`, que
    _update_paper_v1/v2 corrige silenciosamente quando o fill real e conhecido. So diagnostico/
    exclusao (analise.condicional); nunca lido por regra/filtro/alerta/banca de V1 ou V2."""

    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_entry_price_alerta_matches_what_the_entrada_alert_showed_even_when_the_real_fill_differs(self) -> None:
        # no fixture padrao o fill real (bars[j0].open) DIFERE do provisorio do gatilho (ev.data["close"])
        # -- exatamente o mecanismo do McRib: entry_price_alerta fica com o valor do alerta ja enviado,
        # entry_price e corrigido para o fill real (_update_paper_v1).
        _run_entrada(self.h)
        sinal = self.h.storage.pr1_signals()[0]
        ev = event_v1_from_json(sinal["event_json"])
        self.assertIsNotNone(sinal["entry_price_alerta"])
        self.assertAlmostEqual(sinal["entry_price_alerta"], ev.data.get("close"))
        self.assertNotAlmostEqual(sinal["entry_price_alerta"], sinal["entry_price"])

    def test_entry_price_alerta_never_changes_after_entry_price_is_later_corrected(self) -> None:
        _run_entrada(self.h)
        sinal = self.h.storage.pr1_signals()[0]
        original_alerta = sinal["entry_price_alerta"]
        # simula a correcao silenciosa que _update_paper_v1 faz quando o fill real difere do
        # provisorio do alerta (ver live.py, "if res.entry_price is not None and signal[...")
        self.h.storage.pr1_update_signal(sinal["id"], entry_price=original_alerta * 2.0)
        corrigido = self.h.storage.pr1_signal(sinal["id"])
        self.assertAlmostEqual(corrigido["entry_price"], original_alerta * 2.0)
        self.assertAlmostEqual(corrigido["entry_price_alerta"], original_alerta, msg="nunca sobrescrito")


class AnaliseTextoTests(unittest.TestCase):
    """PEDIDO (PARTE 1 de 2) FASE 2c: PosRunnerLive.analise_texto (reusado pelo /analise do Telegram)."""

    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_reports_amostra_insuficiente_before_any_resolved_baseline(self) -> None:
        texto = self.h.live.analise_texto("v1")
        self.assertEqual(texto, "amostra insuficiente (0/30)")

    def test_v1_and_v2_are_reported_independently(self) -> None:
        self.assertEqual(self.h.live.analise_texto("v1"), "amostra insuficiente (0/30)")
        self.assertEqual(self.h.live.analise_texto("v2"), "amostra insuficiente (0/30)")


if __name__ == "__main__":
    unittest.main()
