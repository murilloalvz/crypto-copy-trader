"""POS-RUNNER-V2 (PEDIDO CONSOLIDADO FASE 2): MESMO detector/simulador/banca da V1, so parametros
diferentes (drop_max=0.96, age_window_days=[2, 36500] sem teto) -- roda em paralelo sobre os MESMOS
candles, tabelas/CSV/banca PROPRIAS, alerta mesclado ("V1+V2") quando a V1 ja decidiu no MESMO candle,
"SOMENTE V2 (experimental)" quando so a V2 decidiu. Sem rede."""

from __future__ import annotations

import unittest

from ..http import CallBudget
from ..pos_runner.candles import Bar
from ..pos_runner.detector_v1 import DetectorV1, EventV1
from ..pos_runner.params_v1 import load_params_v1
from ..pos_runner.params_v2 import load_params_v2
from ..pos_runner.quotes import REFERENCE_POOLS, SOL_MINT
from .test_pos_runner import GRAD, H, textbook
from .test_pos_runner_live import LiveHarness, start_tracking


def _confirma_v2(h: LiveHarness) -> list[str]:
    return [t for t in h.texts() if "V2 CONFIRMA" in t]


def _somente_v2(h: LiveHarness) -> list[str]:
    return [t for t in h.texts() if "SOMENTE V2 (experimental)" in t]


class ParamsV2HashTests(unittest.TestCase):
    def test_v2_hash_is_frozen_and_differs_from_v1(self) -> None:
        self.assertEqual(load_params_v2().version, "d57b4331d51d")
        self.assertNotEqual(load_params_v2().version, load_params_v1().version)

    def test_v2_differs_from_v1_only_in_the_2_documented_parameters(self) -> None:
        p1, p2 = load_params_v1().as_dict(), load_params_v2().as_dict()
        diffs = {k for k in p1 if p1[k] != p2[k]}
        self.assertEqual(diffs, {"drop_max", "age_window_days"})
        self.assertEqual(p2["drop_max"], 0.96)
        self.assertEqual(p2["age_window_days"], [2.0, 36500.0])


class MergedAlertTests(unittest.TestCase):
    """Cenario padrao da V1 (`start_tracking` + 17h) tambem fecha uma ENTRADA da V2 no MESMO candle --
    o alerta da V2 tem que ser so a nota de confirmacao, NUNCA um cartao cheio duplicado."""

    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_v2_sends_a_confirmation_reply_not_a_duplicate_full_alert(self) -> None:
        start_tracking(self.h)
        self.h.run_hours(17)
        v1_rows = self.h.storage.pr1_signals()
        v2_rows = self.h.storage.pr2_signals()
        self.assertEqual(len(v1_rows), 1, self.h.texts())
        self.assertEqual(len(v2_rows), 1, self.h.texts())
        self.assertEqual(v2_rows[0]["so_v2"], 0)   # mesclado: ts_fechamento bateu com a V1
        self.assertEqual(v2_rows[0]["versao_config_v2"], self.h.live.version_v2)
        confirma = _confirma_v2(self.h)
        self.assertEqual(len(confirma), 1, self.h.texts())
        self.assertIn("V1+V2", confirma[0])
        self.assertEqual(_somente_v2(self.h), [])   # nunca um alerta cheio pra um sinal mesclado
        self.assertIsNotNone(v2_rows[0]["tg_message_id"])   # a nota de confirmacao e sua propria mensagem

    def _run_to_closed_trade(self) -> None:
        """MESMO cenario de `test_pos_runner_v1_live.EntradaTests.
        test_tp1_then_stop_closes_the_trade_and_updates_bankroll` (TP1 depois stop) -- precisa fechar o
        trade de verdade para a banca dar um passo (so acontece no fechamento, nunca em aberto)."""
        start_tracking(self.h)
        s = textbook(start_flat=0)
        t = s.bars[-1].ts + H
        extra = [
            Bar(t, 400_000, 420_000, 395_000, 410_000, 1_000.0),
            Bar(t + H, 405_000, 1_050_000, 400_000, 620_000, 1_000.0),
            Bar(t + 2 * H, 700_000, 710_000, 690_000, 705_000, 1_000.0),
            Bar(t + 3 * H, 705_000, 710_000, 151_000, 152_000, 1_000.0),
        ]
        self.h.world.add_series("POOL1", "1h", s.bars + extra)
        self.h.list_pool()
        self.h.tick()
        self.h.verifier.step()
        self.h.tick()
        ref_pool, _side = REFERENCE_POOLS[SOL_MINT]
        self.h.world.series[(ref_pool, "1h")] = [Bar(GRAD - 30 * H + k * H, 150.0, 150.0, 150.0, 150.0, 1e6) for k in range(400)]
        for _ in range(27):
            self.h.clock.advance(H)
            self.h.tick()
            self.h.live.http.arm(CallBudget(10), 1, 10)
            self.h.live.quotes.series(SOL_MINT, GRAD, self.h.clock())
            self.h.live.http.disarm()

    def test_v1_and_v2_keep_separate_bankrolls_even_when_merged(self) -> None:
        self._run_to_closed_trade()
        self.assertEqual(self.h.storage.pr1_signals()[0]["status"], "fechado")
        self.assertEqual(self.h.storage.pr2_signals()[0]["status"], "fechado")
        v1_resumos = self.h.storage.pr1_bankroll_resumos()
        v2_resumos = self.h.storage.pr2_bankroll_resumos()
        self.assertTrue(any(self.h.live.version_v1[:12] in k for k in v1_resumos))
        self.assertTrue(any(self.h.live.version_v2[:12] in k for k in v2_resumos))
        # chaves de v1/v2 nunca se misturam (hashes diferentes, nunca aparecem no dict um do outro)
        self.assertFalse(any(self.h.live.version_v2[:12] in k for k in v1_resumos))
        self.assertFalse(any(self.h.live.version_v1[:12] in k for k in v2_resumos))

    def test_relatorio_v2_reports_its_own_version_and_pnl(self) -> None:
        start_tracking(self.h)
        self.h.run_hours(24)
        text = self.h.live.relatorio_semanal_v2()
        self.assertIn(self.h.live.version_v2, text)
        self.assertNotIn(self.h.live.version_v1, text)

    def test_csv_export_writes_a_separate_v2_file(self) -> None:
        start_tracking(self.h)
        self.h.run_hours(17)
        self.h.storage.export_csvs(force=True)
        content = self.h.storage.paths.pos_runner_v2_csv.read_text(encoding="utf-8")
        self.assertIn(self.h.live.version_v2, content)
        self.assertNotIn(self.h.live.version_v1, content)


class SemV2FlagTests(unittest.TestCase):
    def test_sem_v2_disables_the_detector_and_produces_no_rows(self) -> None:
        h = LiveHarness(sem_v2=True)
        try:
            start_tracking(h)
            h.run_hours(17)
            self.assertEqual(h.storage.pr2_signals(), [])
            self.assertEqual(_confirma_v2(h), [])
            self.assertEqual(_somente_v2(h), [])
            # a V1 continua funcionando normalmente com a flag desligada
            self.assertEqual(len(h.storage.pr1_signals()), 1, h.texts())
        finally:
            h.close()


class SomenteV2Tests(unittest.TestCase):
    """Chamada direta de `_entry_v2` (sem passar pela V1) para exercitar o ramo "SOMENTE V2" sem
    precisar reconstruir um cenario de candles onde so a V2 decide (idade > 7 dias, so a V2 aceita)."""

    def setUp(self) -> None:
        self.h = LiveHarness()
        start_tracking(self.h)
        self.h.run_hours(5)   # pool ja rastreado, SEM nenhuma ENTRADA ainda (nem V1 nem V2)

    def tearDown(self) -> None:
        self.h.close()

    def test_entry_v2_sends_its_own_full_alert_tagged_experimental_when_v1_has_no_match(self) -> None:
        row = self.h.storage.pr_pool("POOL1")
        det = DetectorV1(self.h.live.params_v2, "1h", row["l_bc"], row["grad_ts"], None)
        ev = EventV1(
            kind="ENTRADA", idx=0, ts=int(self.h.clock()), decision_ts=int(self.h.clock()),
            data={"gatilho": ["reacao_suporte"], "P_peak": 1_000_000.0, "close": 300_000.0, "stop": 150_000.0,
                 "TOPO": 1_000_000.0, "S": 150_000.0, "R": 260_000.0, "risco_fora_da_faixa": False,
                 "box_len": 10, "idade_dias": 3.0, "queda_pct": 70.0, "L_bc": row["l_bc"]},
        )
        self.assertIsNone(self.h.storage.pr1_signal_by_key("solana", "POOL1", "1h", "ENTRADA", ev.decision_ts))
        self.h.live._entry_v2(row, "1h", det, ev, self.h.clock())  # noqa: SLF001
        rows = self.h.storage.pr2_signals()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["so_v2"], 1)
        alerts = _somente_v2(self.h)
        self.assertEqual(len(alerts), 1, self.h.texts())
        self.assertIn("SINAL DE ENTRADA DETECTADO", alerts[0])
        self.assertEqual(_confirma_v2(self.h), [])


if __name__ == "__main__":
    unittest.main()
