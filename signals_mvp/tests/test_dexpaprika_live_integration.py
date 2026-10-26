"""PEDIDO CONSOLIDADO FASE 1 (DexPaprika) integrado no `PosRunnerLive` real: conferencia cruzada grava
divergencia de verdade; fallback e chamado quando o GeckoTerminal falha de um jeito retomavel. Reaproveita
o harness do V0/V1 (`LiveHarness`/`start_tracking`), so leitura, sem rede real (duble do provider)."""

from __future__ import annotations

import unittest

from ..http import ApiError
from ..pos_runner.dexpaprika_v1 import Divergencia
from .test_pos_runner_live import LiveHarness, start_tracking
from .test_pos_runner_v1_live import H


class _StubDexPaprikaProvider:
    """Duble minimo: grava toda chamada, devolve o que o teste armar."""

    def __init__(self, divergencias=None, fallback_bars=None):
        self.conferir_chamadas: list[tuple] = []
        self.fallback_chamadas: list[tuple] = []
        self._divergencias = list(divergencias or [])
        self._fallback_bars = list(fallback_bars or [])

    def deve_conferir(self) -> bool:
        return True

    def conferir(self, network, pool, tf, candle_gt):
        self.conferir_chamadas.append((network, pool, tf, candle_gt))
        return list(self._divergencias)

    def candles_fallback(self, network, pool, tf, since_ts, now):
        self.fallback_chamadas.append((network, pool, tf, since_ts, now))
        return list(self._fallback_bars)


class ConferenciaCruzadaIntegrationTests(unittest.TestCase):
    def test_divergence_flagged_by_the_provider_gets_persisted_and_shows_up_in_the_csv(self) -> None:
        h = LiveHarness()
        try:
            div = Divergencia(campo="close", valor_gt=100.0, valor_dexpaprika=120.0, diff_pct=20.0)
            stub = _StubDexPaprikaProvider(divergencias=[div])
            h.live.dexpaprika = stub
            start_tracking(h)
            h.run_hours(17)   # mesmo cenario que ja produz WATCHLIST + ENTRADA nos outros testes da V1
            self.assertGreater(len(stub.conferir_chamadas), 0, "a conferencia cruzada tem que ter sido chamada")
            rows = h.storage.pr1_dexpaprika_divergencias()
            self.assertGreaterEqual(len(rows), 1)
            self.assertEqual(rows[0]["campo"], "close")
            self.assertEqual(rows[0]["valor_gt"], 100.0)
            self.assertEqual(rows[0]["valor_dexpaprika"], 120.0)
            self.assertAlmostEqual(rows[0]["diff_pct"], 20.0)
            h.storage.export_csvs(force=True)
            content = h.storage.paths.pos_runner_v1_dexpaprika_csv.read_text(encoding="utf-8")
            self.assertIn("close", content)
            self.assertIn("120.0", content)
        finally:
            h.close()

    def test_no_divergence_when_the_provider_reports_none(self) -> None:
        h = LiveHarness()
        try:
            stub = _StubDexPaprikaProvider(divergencias=[])
            h.live.dexpaprika = stub
            start_tracking(h)
            h.run_hours(17)
            self.assertGreater(len(stub.conferir_chamadas), 0)
            self.assertEqual(h.storage.pr1_dexpaprika_divergencias(), [])
        finally:
            h.close()


class FallbackIntegrationTests(unittest.TestCase):
    def test_a_retryable_gt_failure_triggers_the_dexpaprika_fallback_attempt(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(5)   # ja rastreando, candles normais ate aqui
            stub = _StubDexPaprikaProvider(fallback_bars=[])   # [] = "sem candle novo ainda", nunca quebra o ciclo
            h.live.dexpaprika = stub
            h.world.fail = ApiError("timeout", "GT fora do ar (simulado)")
            h.clock.advance(H)
            out = h.tick()
            self.assertGreater(len(stub.fallback_chamadas), 0, "o fallback tinha que ter sido tentado")
            self.assertGreaterEqual(out["erros"], 1)   # a falha do GT ainda e contada normalmente
        finally:
            h.close()

    def test_a_404_never_triggers_the_fallback(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(5)
            stub = _StubDexPaprikaProvider(fallback_bars=[])
            h.live.dexpaprika = stub
            h.world.fail = ApiError("not_found", "pool nao existe mais", 404)
            h.clock.advance(H)
            h.tick()
            self.assertEqual(stub.fallback_chamadas, [])   # 404 nao e "retomavel": nunca tenta o fallback
        finally:
            h.close()

    def test_dexpaprika_none_never_calls_anything(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(5)
            self.assertIsNone(h.live.dexpaprika)   # padrao: recurso desligado
            h.world.fail = ApiError("timeout", "GT fora do ar (simulado)")
            h.clock.advance(H)
            h.tick()   # nao pode levantar nem quebrar so por nao ter o provider
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
