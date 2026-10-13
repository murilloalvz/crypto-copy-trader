"""Comportamento sob pressao de rate limit: limitador adaptativo, orcamento, candidatos adiados, prioridade do refresh."""

from __future__ import annotations

import unittest

from ..http import ApiError, RateLimited, RateLimiter
from .fakes import SOL_TOKEN, T0, FakeClock
from .helpers import Env
from .test_engine_e2e import happy


class AdaptiveLimiterTest(unittest.TestCase):
    def make(self, **kw):
        clock = FakeClock(0.0)
        return RateLimiter(kw.pop("per_min", 15), kw.pop("burst", 2), pause_s=30, pause_max_s=120, clock=clock, sleep=clock.advance, **kw), clock

    def test_rate_halves_on_429_with_a_floor_and_recovers_on_success(self) -> None:
        limiter, _ = self.make(per_min=16, min_per_min=3, recover_per_success=1.0)
        limiter.on_429()
        self.assertEqual(limiter.per_min, 8.0)
        limiter.on_429()
        limiter.on_429()
        self.assertEqual(limiter.per_min, 3.0)   # piso
        for _ in range(100):
            limiter.on_success()
        self.assertEqual(limiter.per_min, 16.0)  # nunca passa do maximo configurado

    def test_slower_rate_means_longer_waits(self) -> None:
        limiter, clock = self.make(per_min=60, burst=1, min_per_min=10)
        limiter.acquire()
        before = clock()
        limiter.acquire()
        fast_wait = clock() - before
        limiter.on_429()                       # 60 -> 30 por min, mas ha uma pausa
        clock.advance(limiter.blocked_for() + 1)
        limiter.on_success()
        limiter.acquire()
        before = clock()
        limiter.acquire()
        self.assertGreater(clock() - before, fast_wait)

    def test_default_floor_is_a_quarter_of_the_max(self) -> None:
        limiter, _ = self.make(per_min=20)
        for _ in range(10):
            limiter.on_429()
        self.assertEqual(limiter.per_min, 5.0)


class AvailableWithinTest(unittest.TestCase):
    def test_counts_tokens_and_refill_and_respects_pause(self) -> None:
        clock = FakeClock(0.0)
        limiter = RateLimiter(60, 3, pause_s=30, pause_max_s=60, clock=clock, sleep=clock.advance)
        self.assertEqual(limiter.available_within(10), 3 + 10)        # 3 fichas + 1/s durante 10 s
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()
        self.assertEqual(limiter.available_within(10), 10)
        limiter.on_429()
        self.assertEqual(limiter.available_within(10), 0)              # em pausa por mais tempo que a janela
        clock.advance(31)
        self.assertGreaterEqual(limiter.available_within(10), 1)

    def test_faster_recovery_after_a_429_burst(self) -> None:
        limiter = RateLimiter(15, 2)
        for _ in range(3):
            limiter.on_429()
        floor = limiter.per_min
        self.assertEqual(floor, 3.75)
        for _ in range(10):                    # ~10 chamadas ok (poucos ciclos) ja devolvem o ritmo cheio
            limiter.on_success()
        self.assertEqual(limiter.per_min, 8.75)
        for _ in range(10):
            limiter.on_success()
        self.assertEqual(limiter.per_min, 13.75)


class RoundRobinTest(unittest.TestCase):
    def tearDown(self) -> None:
        self.env.close()

    def test_first_chain_rotates_so_none_starves_under_a_short_budget(self) -> None:
        self.env = Env({"gt": {"orcamento_por_ciclo": 3}})
        order: list[str] = []
        original = self.env.gt.new_pools

        def spy(ctx, page):
            order.append(ctx.name)
            return original(ctx, page)

        self.env.gt.new_pools = spy  # type: ignore[method-assign]
        self.env.engine.cfg.raw["gt"]["orcamento_por_ciclo"] = 3
        firsts = []
        for _ in range(6):
            order.clear()
            self.env.cycle(1)
            firsts.append(order[0])
        self.assertEqual(set(firsts), {"solana", "bsc", "robinhood"})

    def test_local_throttle_is_counted_but_is_not_an_error(self) -> None:
        self.env = Env()
        self.env.gt.fail["new_pools"] = ApiError("budget", "sem ficha")
        stats = self.env.cycle(1)
        self.assertGreaterEqual(stats.throttled, 1)
        self.assertEqual(stats.errors, 0)
        self.assertIn("limitado", stats.line())


class CycleBudgetTest(unittest.TestCase):
    def tearDown(self) -> None:
        self.env.close()

    def test_budget_shrinks_with_the_limiter_rate(self) -> None:
        self.env = Env()
        limiter = RateLimiter(15, 2)
        self.env.gt.http = type("H", (), {"limiter": limiter})()  # o FakeGt passa a "ter" um limitador
        full = self.env.engine._cycle_budget()  # noqa: SLF001
        self.assertEqual(full, 11)
        limiter.on_429()
        self.assertLess(self.env.engine._cycle_budget(), full)  # noqa: SLF001
        for _ in range(10):
            limiter.on_429()
        self.assertEqual(self.env.engine._cycle_budget(), 3)    # piso: sempre da para fazer o essencial  # noqa: SLF001

    def test_gt_blocked_for_reads_the_limiter(self) -> None:
        self.env = Env()
        self.assertEqual(self.env.engine.gt_blocked_for(), 0.0)
        limiter = RateLimiter(15, 2)
        self.env.gt.http = type("H", (), {"limiter": limiter})()
        limiter.on_429()
        self.assertGreater(self.env.engine.gt_blocked_for(), 0.0)


class StarvationTest(unittest.TestCase):
    def tearDown(self) -> None:
        self.env.close()

    def test_postponed_candidate_is_finished_before_looking_for_new_pools(self) -> None:
        """Orcamento curto: dois candidatos disparam juntos, so cabe um enriquecimento. No ciclo seguinte a PRIMEIRA
        chamada ao GeckoTerminal tem que ser o refresh do adiado — nao a descoberta de pools novos."""
        self.env = Env({"gt": {"orcamento_por_ciclo": 4}})
        self.env.gt.add(happy(pool="W1", token=SOL_TOKEN, symbol="KittyAI"))
        self.env.gt.add(happy(pool="W2", token=SOL_TOKEN[:-2] + "zz", symbol="KittyAI2"))
        self.env.cycle(3)  # no ciclo 3 (idade 90 s) os dois passam no gatilho
        self.assertEqual(len(self.env.read("sinais.csv")), 1)
        self.assertEqual(len(self.env.engine._carry), 1)  # noqa: SLF001
        self.env.gt.log.clear()
        self.env.cycle(1)
        self.assertEqual(self.env.gt.log[0], "pools_multi")
        self.assertEqual(len(self.env.read("sinais.csv")), 2)
        self.assertEqual(len(self.env.tg.sent), 2)

    def test_carry_is_cleared_after_processing(self) -> None:
        self.env = Env()
        self.env.gt.add(happy())
        self.env.cycle(4)
        self.assertEqual(self.env.engine._carry, set())  # noqa: SLF001

    def test_rate_limited_cycle_flags_stats_and_loses_nothing(self) -> None:
        self.env = Env()
        self.env.gt.add(happy())
        self.env.cycle(1)
        self.env.gt.fail["new_pools"] = RateLimited(30)
        stats = self.env.cycle(1)
        self.assertTrue(stats.rate_limited)
        del self.env.gt.fail["new_pools"]
        self.env.cycle(4)
        self.assertEqual(len(self.env.read("sinais.csv")), 1)  # o sinal sai assim que a API volta

    def test_local_throttling_postpones_instead_of_evaluating_with_missing_info(self) -> None:
        """Sem ficha no limitador LOCAL: nao decide com descricao/mint faltando (a 1a decisao e final) — adia."""
        self.env = Env()
        self.env.gt.add(happy())
        self.env.gt.fail["token_info"] = ApiError("budget", "limitador local")
        self.env.cycle(5)
        self.assertEqual(self.env.read("sinais.csv"), [])
        self.assertEqual(len(self.env.engine._carry), 1)  # noqa: SLF001
        del self.env.gt.fail["token_info"]
        self.env.cycle(2)
        row = self.env.read("sinais.csv")[0]
        self.assertEqual(row["seguranca"], "ok")  # agora com o GT disponivel para mint/freeze

    def test_goplus_local_throttling_postpones_and_expiry_explains_why(self) -> None:
        self.env = Env()
        self.env.gt.add(happy(chain="bsc", pool="0xpool", token="0xtoken", dex="pancakeswap_v2", vol_m5=lambda a: 12000.0 if a < 400 else 100.0))
        self.env.goplus.error = ApiError("budget", "limitador local")
        self.env.cycle(20)  # a janela do `novo` (10 min) fecha com o GoPlus sempre indisponivel
        self.assertEqual(self.env.read("sinais.csv"), [])
        row = self.env.read("descartados.csv")[0]
        self.assertEqual(row["etapa"], "adiado")
        self.assertIn("gatilho disparou mas nao foi avaliado", row["motivo"])
        self.assertIn("GoPlus indisponivel", row["motivo"])

    def test_goplus_timeouts_get_a_few_attempts_then_policy_applies(self) -> None:
        self.env = Env()
        self.env.gt.add(happy(chain="bsc", pool="0xpool", token="0xtoken", dex="pancakeswap_v2"))
        self.env.goplus.error = ApiError("timeout")
        self.env.cycle(2)
        self.assertEqual(self.env.read("sinais.csv"), [])           # ainda tentando
        self.env.cycle(4)
        self.assertEqual(self.env.read("sinais.csv")[0]["seguranca"], "sem_dado")  # desistiu e seguiu a politica (liberar com aviso)

    def test_api_errors_in_enrichment_do_not_block_the_alert_forever(self) -> None:
        self.env = Env()
        self.env.gt.add(happy())
        self.env.gt.fail["token_info"] = ApiError("timeout")
        self.env.gt.fail["trades"] = ApiError("timeout")
        self.env.cycle(5)
        row = self.env.read("sinais.csv")[0]
        self.assertEqual(row["enviado"], "1")  # sem descricao e sem valor de trades, mas o sinal sai
        self.assertEqual(row["seguranca"], "sem_dado")


class PruneTest(unittest.TestCase):
    def test_prune_keeps_signals_and_open_labels(self) -> None:
        env = Env()
        try:
            env.gt.add(happy(pool="KEEP", token=SOL_TOKEN))
            env.gt.add(happy(pool="OLDQUIET", token=SOL_TOKEN[:-2] + "qq", vol_m5=lambda a: 0.0))
            env.cycle(30)
            before = env.storage.counts()["pools"]
            removed = env.storage.prune(env.clock() + 5 * 86400, keep_days=3)
            self.assertGreaterEqual(removed.get("pools", 0), 1)
            self.assertLess(env.storage.counts()["pools"], before)
            self.assertIsNotNone(env.storage.get_pool("solana", "KEEP"))   # tem sinal: fica
            self.assertEqual(len(env.read("sinais.csv")), 2)               # sinais nunca sao apagados (novo + sobrevivente20)
        finally:
            env.close()


class RefreshPriorityTest(unittest.TestCase):
    def test_most_active_pools_are_refreshed_first(self) -> None:
        env = Env()
        try:
            env.gt.add(happy(pool="QUIET", token="QuietTokenAddr0000000000000000000000000000", vol_m5=lambda a: 10.0, buys=lambda a: 1, sells=lambda a: 0, buyers=lambda a: 1))
            env.gt.add(happy(pool="BUSY", token=SOL_TOKEN, vol_m5=lambda a: 50000.0))
            env.cycle(1)  # descobre os dois e registra a atividade
            order = [r["pool"] for r in env.storage.pools_to_refresh(T0 + 100, 600, 1200, 1500)]
            self.assertEqual(order[0], "BUSY")
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
