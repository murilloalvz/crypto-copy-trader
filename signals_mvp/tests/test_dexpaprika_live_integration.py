"""PEDIDO CONSOLIDADO FASE 1 (DexPaprika) integrado no `PosRunnerLive` real: conferencia cruzada grava
divergencia de verdade; fallback e chamado quando o GeckoTerminal falha de um jeito retomavel. Reaproveita
o harness do V0/V1 (`LiveHarness`/`start_tracking`), so leitura, sem rede real (duble do provider)."""

from __future__ import annotations

import unittest
from unittest import mock

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


class PendenciaFallbackTests(unittest.TestCase):
    """PEDIDO 2026-10-28, item 3: independente de erro explicito do GT, um (pool,tf) 1h pendente
    >= `POS_RUNNER_FALLBACK_DP_MIN` (padrao 20) min depois do fechamento da hora tenta o fallback
    DexPaprika uma vez (nunca martela a cada tick, nunca mais de 1x por hora)."""

    def test_fires_once_past_20_minutes_pending_then_never_twice_in_the_same_hour(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(5)
            stub = _StubDexPaprikaProvider(fallback_bars=[])
            h.live.dexpaprika = stub
            row = h.storage.pr_pool("POOL1")
            hora = (h.clock() // 3600) * 3600
            h.live._tentar_fallback_por_pendencia(row, "1h", hora + 10 * 60.0)  # noqa: SLF001 -- ainda sob o teto (20)
            self.assertEqual(stub.fallback_chamadas, [])
            h.live._tentar_fallback_por_pendencia(row, "1h", hora + 25 * 60.0)  # noqa: SLF001 -- passou o teto
            self.assertEqual(len(stub.fallback_chamadas), 1)
            h.live._tentar_fallback_por_pendencia(row, "1h", hora + 40 * 60.0)  # noqa: SLF001 -- mesma hora
            self.assertEqual(len(stub.fallback_chamadas), 1, "nunca martela DexPaprika 2x na mesma hora")
            proxima_hora = hora + H
            h.live._tentar_fallback_por_pendencia(row, "1h", proxima_hora + 25 * 60.0)  # noqa: SLF001
            self.assertEqual(len(stub.fallback_chamadas), 2, "nova hora pendente libera 1 nova tentativa")
        finally:
            h.close()

    def test_the_attempt_itself_is_always_registered_in_sched_regardless_of_outcome(self) -> None:
        """PEDIDO 2026-10-29, item 2: antes, uma tentativa de fallback que nao trazia candle novo (ou
        que falhava) nao deixava rastro em `self.sched` -- o diagnostico do alerta mostrava "fonte:
        s/d" mesmo depois do fallback ter rodado. Agora `ultima_tentativa`/`fonte`/`ultimo_erro`
        sempre sao gravados, nos 2 desfechos (sem candle novo vs. erro)."""
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(5)
            row = h.storage.pr_pool("POOL1")
            hora = (h.clock() // 3600) * 3600

            h.live.dexpaprika = _StubDexPaprikaProvider(fallback_bars=[])   # sem candle novo
            h.live._tentar_fallback_por_pendencia(row, "1h", hora + 25 * 60.0)  # noqa: SLF001
            st = h.live.sched[("POOL1", "1h")]
            self.assertEqual(st["fonte"], "dexpaprika_fallback")
            self.assertEqual(st["ultimo_erro"], "dexpaprika_sem_candle_novo")
            self.assertAlmostEqual(st["ultima_tentativa"], hora + 25 * 60.0)

            proxima_hora = hora + H

            class _ProviderQuebrado:
                def candles_fallback(self, *a, **kw):
                    raise RuntimeError("DexPaprika fora do ar (simulado)")

            h.live.dexpaprika = _ProviderQuebrado()
            h.live._tentar_fallback_por_pendencia(row, "1h", proxima_hora + 25 * 60.0)  # noqa: SLF001
            st = h.live.sched[("POOL1", "1h")]
            self.assertEqual(st["fonte"], "dexpaprika_fallback")
            self.assertEqual(st["ultimo_erro"], "dexpaprika_falhou")
            self.assertAlmostEqual(st["ultima_tentativa"], proxima_hora + 25 * 60.0)
        finally:
            h.close()

    def test_never_fires_for_timeframes_other_than_1h(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(5)
            stub = _StubDexPaprikaProvider(fallback_bars=[])
            h.live.dexpaprika = stub
            row = h.storage.pr_pool("POOL1")
            hora = (h.clock() // 3600) * 3600
            h.live._tentar_fallback_por_pendencia(row, "4h", hora + 25 * 60.0)  # noqa: SLF001
            self.assertEqual(stub.fallback_chamadas, [])
        finally:
            h.close()

    def test_the_minutes_threshold_is_configurable_via_env(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(5)
            stub = _StubDexPaprikaProvider(fallback_bars=[])
            h.live.dexpaprika = stub
            row = h.storage.pr_pool("POOL1")
            hora = (h.clock() // 3600) * 3600
            with mock.patch.dict("os.environ", {"POS_RUNNER_FALLBACK_DP_MIN": "5"}):
                h.live._tentar_fallback_por_pendencia(row, "1h", hora + 6 * 60.0)  # noqa: SLF001
            self.assertEqual(len(stub.fallback_chamadas), 1)
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
