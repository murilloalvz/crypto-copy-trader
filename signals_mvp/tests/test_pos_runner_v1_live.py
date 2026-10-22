"""POS-RUNNER-V1 ao vivo, integrada no MESMO PosRunnerLive do V0 (mesmos candles via pr_bars). Sem rede.

Reaproveita o harness do V0 (`test_pos_runner_live.LiveHarness`/`start_tracking`) -- a V1 roda em paralelo
sobre o MESMO cenario que o V0 ja usa, exatamente como pedido no item 0 do prompt ("V0 continua rodando em
silencio sobre os MESMOS candles")."""

from __future__ import annotations

import unittest

from ..http import CallBudget
from ..pos_runner.candles import Bar
from ..pos_runner.live import PosRunnerLive
from ..pos_runner.quotes import REFERENCE_POOLS, SOL_MINT
from .test_pos_runner import CREATED, GRAD, H, textbook
from .test_pos_runner_live import CTX, LINKS, LiveHarness, start_tracking


def _watch_v1(h: LiveHarness) -> list[str]:
    return [t for t in h.texts() if t.startswith("👀 [POS_RUNNER] WATCHLIST")]


def _entrada_v1(h: LiveHarness) -> list[str]:
    return [t for t in h.texts() if t.startswith("🚨 [POS_RUNNER]")]


class EntradaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def _run_to_entrada(self) -> None:
        start_tracking(self.h)
        self.h.run_hours(17)   # candle 24 (rompimento) + folga de indexacao

    def test_entrada_alert_is_sent_and_persisted(self) -> None:
        self._run_to_entrada()
        entradas = _entrada_v1(self.h)
        self.assertEqual(len(entradas), 1, self.h.texts())
        self.assertIn("SINAL DE ENTRADA DETECTADO", entradas[0])
        rows = self.h.storage.pr1_signals()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "aberto")
        self.assertEqual(rows[0]["chain"], "solana")
        self.assertEqual(rows[0]["tf"], "1h")
        self.assertEqual(rows[0]["versao_config_v1"], self.h.live.version_v1)

    def test_resume_never_duplicates_the_entry_alert_or_the_row(self) -> None:
        self._run_to_entrada()
        self.assertEqual(len(_entrada_v1(self.h)), 1)
        self.assertEqual(len(self.h.storage.pr1_signals()), 1)
        # "reinicio": uma instancia NOVA de PosRunnerLive, mesmo storage/relogio -- reconstroi o detector dos
        # candles ja congelados (item 3.7: nunca duplica, nunca re-alerta o que ja foi mandado).
        fresh = self.h.new_live()
        self.h.tick(live=fresh)
        self.assertEqual(len(_entrada_v1(self.h)), 1, "reinicio nao pode repetir o alerta de entrada")
        self.assertEqual(len(self.h.storage.pr1_signals()), 1, "reinicio nao pode duplicar a linha do sinal")

    def test_tp1_then_stop_closes_the_trade_and_updates_bankroll(self) -> None:
        # Depois do rompimento, fabrica candles que levam o preco ao TOPO (1M) com exaustao (TP1), depois
        # caem e tocam o stop (fecha o trade). Mesmos valores de P_peak/S/stop do textbook() do V0; sem a
        # cauda longa de candles planos (start_flat=0) para o rompimento ficar logo antes dos meus candles.
        s = textbook(start_flat=0)
        t = s.bars[-1].ts + H
        extra = [
            Bar(t, 400_000, 420_000, 395_000, 410_000, 1_000.0),         # entrada no open (proximo candle)
            Bar(t + H, 405_000, 1_050_000, 400_000, 620_000, 1_000.0),   # toca o TOPO com pavio de exaustao -> TP1
            Bar(t + 2 * H, 700_000, 710_000, 690_000, 705_000, 1_000.0),  # preenche o TP1 no open (700k)
            Bar(t + 3 * H, 705_000, 710_000, 151_000, 152_000, 1_000.0),  # toca o stop (151,9k)
        ]
        self.h.world.add_series("POOL1", "1h", s.bars + extra)
        self.h.list_pool()
        self.h.tick()
        self.h.verifier.step()
        self.h.tick()
        # cotacao SOL/USD cacheada: sem ela a gestao de banca (que converte US$ -> SOL) fica sem dado, nunca
        # inventa um custo (mesma necessidade do bankroll do V0, ver test_pos_runner_live.py).
        ref_pool, _side = REFERENCE_POOLS[SOL_MINT]
        self.h.world.series[(ref_pool, "1h")] = [Bar(GRAD - 30 * H + k * H, 150.0, 150.0, 150.0, 150.0, 1e6) for k in range(400)]
        for _ in range(27):
            self.h.clock.advance(H)
            self.h.tick()
            self.h.live.http.arm(CallBudget(10), 1, 10)
            self.h.live.quotes.series(SOL_MINT, GRAD, self.h.clock())
            self.h.live.http.disarm()
        self.assertEqual(len(_entrada_v1(self.h)), 1, self.h.texts())
        tp1_msgs = [t for t in self.h.texts() if t.startswith("🟡 [POS_RUNNER] TP1")]
        exit_msgs = [t for t in self.h.texts() if t.startswith("🔴 [POS_RUNNER] EXIT FULL")]
        self.assertEqual(len(tp1_msgs), 1, self.h.texts())
        self.assertEqual(len(exit_msgs), 1, self.h.texts())
        row = self.h.storage.pr1_signals()[0]
        self.assertEqual(row["status"], "fechado")
        self.assertIsNotNone(row["tp1_price"])
        self.assertEqual(row["reason"], "stop")
        banca = self.h.storage.pr1_bankroll_resumos()
        self.assertEqual(len(banca), 1)
        self.assertEqual(next(iter(banca.values()))["n_trades"], 1)
        written = self.h.storage.export_csvs(force=True)
        self.assertIn("pos_runner_v1.csv", written)
        self.assertIn("pos_runner_v1_banca.csv", written)


class QualityFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_dado_invalido_pool_never_alerts(self) -> None:
        bad = [Bar(GRAD, 100.0, 1_000_000.0, 100.0, 1_000.0, 1.0)] + [Bar(GRAD + k * H, 1_000.0, 1_050.0, 950.0, 1_020.0, 1.0)
                                                                      for k in range(1, 30)]
        self.h.world.add_series("POOL1", "1h", bad)
        self.h.list_pool()
        self.h.tick()
        self.h.verifier.step()
        self.h.run_hours(5)
        self.assertEqual(_entrada_v1(self.h), [])
        self.assertEqual(_watch_v1(self.h), [])
        counts = self.h.storage.pr1_filtrado_counts(0.0)
        self.assertGreaterEqual(counts.get("dado_invalido", 0), 1)

    def test_filtrado_mc_baixo_is_recorded_and_never_blocks_v0(self) -> None:
        # a descoberta (V0) usa o MC do snapshot ao vivo (sempre >= runner_min_mc, senao nem entraria na
        # fila); o que importa para o filtro da V1 (item 2.4) e o MC do PRIMEIRO candle historico, que pode
        # ser bem menor (ex.: o candle de graduacao abriu baixo e so subiu depois).
        low = [Bar(GRAD + k * H, 50_000.0, 52_000.0, 49_000.0, 51_000.0, 1.0) for k in range(30)]
        self.h.world.add_series("POOL1", "1h", low)
        self.h.list_pool(mc=1_000_000.0)
        self.h.tick()
        self.h.verifier.step()
        self.h.tick()
        self.h.run_hours(5)
        self.assertEqual(_entrada_v1(self.h), [])
        counts = self.h.storage.pr1_filtrado_counts(0.0)
        self.assertGreaterEqual(counts.get("filtrado_mc_baixo", 0), 1)


class HeartbeatTests(unittest.TestCase):
    def test_heartbeat_is_sent_periodically_with_the_counters(self) -> None:
        h = LiveHarness()
        try:
            h.live.heartbeat_interval_s = 3 * H   # acelera o teste (padrao real: 4h)
            start_tracking(h)
            h.run_hours(3)
            beats = [t for t in h.texts() if t.startswith("💓 POS-RUNNER-V1")]
            self.assertEqual(len(beats), 1, h.texts())
            self.assertIn("pools acompanhados:", beats[0])
            self.assertIn("chamadas/min", beats[0])
            self.assertIn("dado_invalido:", beats[0])
            self.assertIn("filtrado_mc_baixo:", beats[0])
            h.run_hours(3)
            self.assertEqual(len([t for t in h.texts() if t.startswith("💓 POS-RUNNER-V1")]), 2,
                             "o heartbeat tem que repetir a cada janela, nao so uma vez")
        finally:
            h.close()


class SemV0Tests(unittest.TestCase):
    def test_sem_v0_disables_v0_alerts_but_keeps_v1(self) -> None:
        h = LiveHarness()
        try:
            h.live = PosRunnerLive(h.settings, h.params, h.storage, h.world, CTX, h.tg, LINKS, "solana",
                                   h.paths.dados / "pos_runner", clock=h.clock, sem_v0=True)
            start_tracking(h)
            h.run_hours(17)
            self.assertEqual([t for t in h.texts() if t.startswith("👀 WATCHLIST POS-RUNNER")], [],
                             "V0 nunca pode alertar com --sem-v0")
            self.assertEqual(h.storage.pr_signals(), [], "V0 nunca pode gravar sinal com --sem-v0")
            self.assertGreaterEqual(len(_entrada_v1(h)), 1, "a V1 continua alertando normalmente")
        finally:
            h.close()

    def test_sem_v0_also_shrinks_the_timeframes_fetched(self) -> None:
        """Revisao da FASE 1: --sem-v0 precisa parar de gastar orcamento de GT com os tfs que SO o V0 usava
        (tipicamente 5m/4h) -- antes da correcao, `tfs()` ficava igual ligado ou nao."""
        from ..pos_runner.live import LiveSettings

        settings = LiveSettings(ligado=True, timeframes=("5m", "1h", "4h"), max_pools=5, chamadas_por_ciclo=3,
                                descoberta_min=3, fontes=("pumpswap",), grafico=False)
        h = LiveHarness(settings=settings)
        try:
            ligado = PosRunnerLive(h.settings, h.params, h.storage, h.world, CTX, h.tg, LINKS, "solana",
                                   h.paths.dados / "pos_runner", clock=h.clock, sem_v0=False)
            desligado = PosRunnerLive(h.settings, h.params, h.storage, h.world, CTX, h.tg, LINKS, "solana",
                                      h.paths.dados / "pos_runner", clock=h.clock, sem_v0=True)
            self.assertEqual(ligado.tfs(), ("5m", "1h", "4h"))
            self.assertEqual(desligado.tfs(), desligado.params_v1.timeframes)
            self.assertEqual(desligado.tfs(), ("1h",))
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
