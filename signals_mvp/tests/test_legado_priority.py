"""BUG PRIORITARIO (2026-10-22, item 3): o POS-RUNNER-V1 tem prioridade real sobre o motor legado no MESMO
limitador/orcamento de GT. Antes, `run_cycle()` reservava "3 chamadas essenciais" do legado ANTES da fatia
do POS-RUNNER (`keep_pr = min(wanted, max(0, limit - 3 - keep_follow))`) -- com o orcamento do ciclo no piso
(3, o minimo que `_cycle_budget()` devolve apos uma sequencia de 429), a reserva do POS-RUNNER colapsava pra
0 mesmo ele "querendo" muito mais, e o V1 ficava faminto (fila nunca drena, 0 chamadas/min). Sem rede."""

from __future__ import annotations

import unittest
from typing import Any

from ..http import CallBudget
from .helpers import Env


class _FakePosRunner:
    """Duble minimo com a MESMA interface que `Engine._pos_runner_tick`/`_pos_runner_wanted` chamam --
    consome avidamente o que o orcamento deixar (respeitando `keep`), pra medir exatamente quanto o
    POS-RUNNER recebeu de verdade neste ciclo."""

    def __init__(self, wants: int):
        self._wants = wants
        self.tick_calls: list[tuple[float, int]] = []
        self.offer_calls = 0
        self.consumed = 0

    def enabled(self) -> bool:
        return True

    def wanted(self, now: float) -> int:
        return self._wants

    def offer(self, snaps: Any, now: float, fonte: str = "bot_v0") -> int:
        self.offer_calls += 1
        return 0

    def tick(self, now: float, budget: CallBudget, keep: int) -> dict:
        self.tick_calls.append((now, keep))
        chamadas = 0
        while budget.take(1, keep=keep):
            chamadas += 1
        self.consumed += chamadas
        return {"chamadas": chamadas, "erros": 0, "rate_limited": False}


class SemLegadoTests(unittest.TestCase):
    """`engine.legado_ligado=False` (SEM_LEGADO): zero chamada do motor legado, orcamento inteiro pro V1."""

    def setUp(self) -> None:
        self.env = Env()
        self.fake = _FakePosRunner(wants=10)
        self.env.engine.pos_runner = self.fake
        self.env.engine.legado_ligado = False

    def tearDown(self) -> None:
        self.env.close()

    def test_pos_runner_gets_the_whole_cycle_budget(self) -> None:
        stats = self.env.cycle(1)
        limit = self.env.engine._cycle_budget()  # noqa: SLF001
        self.assertEqual(self.fake.consumed, limit, "com o legado desligado o orcamento inteiro e do V1")
        self.assertEqual(stats.gt_calls, self.fake.consumed)

    def test_legacy_engine_makes_zero_gt_calls(self) -> None:
        self.env.cycle(1)
        self.assertEqual(sum(self.env.gt.calls.values()), 0,
                         f"motor legado deveria fazer ZERO chamadas de GT, fez {dict(self.env.gt.calls)}")

    def test_offer_is_never_called_without_legacy_discovery_feeding_it(self) -> None:
        """`_pos_runner_tick` ainda roda (`offer`/`tick`), so a descoberta do PROPRIO legado (`seen`) que fica
        vazia -- o POS-RUNNER continua com a sua propria descoberta interna (fora do alcance deste teste)."""
        self.env.cycle(1)
        self.assertEqual(self.fake.offer_calls, 1)


class LegadoOnButSqueezedBudgetTests(unittest.TestCase):
    """Legado LIGADO (explicito, `SEM_LEGADO=0`) mas o orcamento do ciclo caiu no piso (3, o minimo que
    `_cycle_budget()` devolve) -- antes da correcao, o V1 ficava com 0 aqui; agora ele tem prioridade."""

    def setUp(self) -> None:
        # so solana ligada: isola a reserva "essencial" do legado a 1 chain (menos ruido pra contar chamadas).
        self.env = Env(overrides={"chains": {"bsc": {"ligada": False}, "robinhood": {"ligada": False}}})
        self.fake = _FakePosRunner(wants=5)
        self.env.engine.pos_runner = self.fake
        self.env.engine.legado_ligado = True
        self.env.engine._cycle_budget = lambda: 3  # noqa: SLF001 -- simula o piso apos uma sequencia de 429

    def tearDown(self) -> None:
        self.env.close()

    def test_pos_runner_gets_priority_over_the_legacy_essential_reserve(self) -> None:
        self.env.engine.run_cycle()
        self.assertEqual(self.fake.consumed, 3, "o V1 deveria conseguir as 3 chamadas do orcamento no piso")

    def test_legacy_discovery_is_the_one_that_gets_squeezed_out_instead(self) -> None:
        self.env.engine.run_cycle()
        self.assertEqual(self.env.gt.calls.get("new_pools", 0), 0,
                         "com o orcamento todo reservado pro V1, a descoberta do legado fica sem chamada neste ciclo")


class HashUnaffectedTests(unittest.TestCase):
    """O ajuste de prioridade/orcamento e puramente operacional (worker.py/engine.py) -- nunca toca em
    `params_v1.py`/`pos_runner_v1.yaml`. BUG PRIORITARIO exige provar isto com teste."""

    def test_v1_hash_stays_279b79ffa3f0(self) -> None:
        from ..pos_runner.params_v1 import load_params_v1

        self.assertEqual(load_params_v1().version, "279b79ffa3f0")


if __name__ == "__main__":
    unittest.main()
