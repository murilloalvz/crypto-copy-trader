"""PEDIDO 2026-10-30 (item 5, contador/vagas): teto de pools ativos (`max_pools`) + aposentadoria de
pools estagnados (`_retire_estagnado`) -- medicao/operacao de QUEM fica sob observacao, nunca toca
regra de deteccao/entrada/saida/banca de V1/V2. Sem rede."""

from __future__ import annotations

import json
import unittest

from ..pos_runner.live import LiveSettings
from .test_pos_runner import CREATED
from .test_pos_runner_live import GRAD, H, LiveHarness, start_tracking

SETTINGS_MAX1 = LiveSettings(ligado=True, timeframes=("1h",), max_pools=1, chamadas_por_ciclo=3,
                             descoberta_min=3, fontes=("pumpswap",), grafico=False)


def _seed_verificado(h: LiveHarness, pool: str, mc_found: float, grad_ts: float = GRAD,
                     criado_ts: float = CREATED) -> None:
    h.storage.pr_upsert_pool(pool, status="verificado", mint=f"MINT-{pool}", symbol=pool, grad_ts=grad_ts,
                             mc_found=mc_found, dex="pumpswap", launchpad="pumpfun",
                             info=json.dumps({"criado_ts": criado_ts}))


class PromoteCapacityTests(unittest.TestCase):
    """`_promote`: so promove ate `max_pools`; o resto da fila (ordenada por MC desc) fica
    `verificado`, nunca `break`a sem registrar quem foi bloqueado (item 5b)."""

    def test_candidates_beyond_max_pools_are_recorded_as_vaga_negada_once_per_day(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            _seed_verificado(h, "POOL1", mc_found=1_000_000.0)
            _seed_verificado(h, "POOL2", mc_found=500_000.0)
            now = h.clock()
            h.live._promote(now)   # noqa: SLF001
            self.assertEqual({r["pool"] for r in h.storage.pr_pools("ativo")}, {"POOL1"}, "maior MC primeiro")
            self.assertEqual(h.storage.pr_vaga_descarte_count(0.0), 1)
            # chamar de novo no MESMO dia (POOL2 continua bloqueado) nunca duplica a contagem
            h.live._promote(now + 60.0)   # noqa: SLF001
            h.live._promote(now + 120.0)   # noqa: SLF001
            self.assertEqual(h.storage.pr_vaga_descarte_count(0.0), 1, "idempotente por dia UTC")
        finally:
            h.close()

    def test_freeing_a_slot_lets_a_previously_blocked_candidate_get_promoted(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            _seed_verificado(h, "POOL1", mc_found=1_000_000.0)
            _seed_verificado(h, "POOL2", mc_found=500_000.0)
            now = h.clock()
            h.live._promote(now)   # noqa: SLF001
            self.assertEqual({r["pool"] for r in h.storage.pr_pools("ativo")}, {"POOL1"})
            h.storage.pr_upsert_pool("POOL1", status="encerrado", checked_ts=now, motivo="teste")
            h.live._promote(now + 60.0)   # noqa: SLF001
            self.assertEqual({r["pool"] for r in h.storage.pr_pools("ativo")}, {"POOL2"})
        finally:
            h.close()


class RetireEstagnadoTests(unittest.TestCase):
    """`_retire_estagnado`: libera vaga de pool MORTO -- nunca toca regra de V1/V2, so decide quem
    fica sob observacao."""

    def test_a_pool_with_no_new_candle_for_24h_is_retired(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            h.storage.pr_upsert_pool("POOL1", status="ativo", mint="MINT1", symbol="CAT", grad_ts=GRAD,
                                     added_ts=h.clock())
            h.storage.pr_append_bars("POOL1", "1h", [(int(GRAD), 1.0, 1.0, 1.0, 1.0, 1.0, True)])
            h.live._retire_estagnado(GRAD + 25 * H)   # noqa: SLF001
            row = h.storage.pr_pool("POOL1")
            self.assertEqual(row["status"], "encerrado")
            self.assertIn("estagnado", row["motivo"])
            self.assertIn("sem candle", row["motivo"])
        finally:
            h.close()

    def test_a_pool_below_the_24h_threshold_is_never_retired(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            h.storage.pr_upsert_pool("POOL1", status="ativo", mint="MINT1", symbol="CAT", grad_ts=GRAD,
                                     added_ts=h.clock())
            h.storage.pr_append_bars("POOL1", "1h", [(int(GRAD), 1.0, 1.0, 1.0, 1.0, 1.0, True)])
            h.live._retire_estagnado(GRAD + 10 * H)   # noqa: SLF001
            self.assertEqual(h.storage.pr_pool("POOL1")["status"], "ativo")
        finally:
            h.close()

    def test_a_pool_with_an_open_v1_position_is_never_retired_even_if_stale(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(20)
            abertos = h.storage.pr1_signals(status="aberto")
            self.assertEqual(len(abertos), 1, h.texts())
            pool = abertos[0]["pool"]
            # "agora" bem no futuro -- o ultimo candle real fica MUITO mais antigo que 24h, mas a
            # posicao aberta tem que blindar mesmo assim (mesma guarda de `_retire`).
            h.live._retire_estagnado(h.clock() + 100 * H)   # noqa: SLF001
            self.assertEqual(h.storage.pr_pool(pool)["status"], "ativo")
        finally:
            h.close()

    def test_a_pool_with_drop_beyond_99_5_percent_is_retired(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(5)
            self.assertEqual(h.storage.pr1_signals(status="aberto"), [], "ainda sem posicao aberta")
            det = h.live.dets_v1.get(("POOL1", "1h"))
            self.assertIsNotNone(det)
            det.peak, det.trough = 1_000_000.0, 4_000.0   # queda 99.6% -- so pra este teste isolado
            h.live._retire_estagnado(h.clock())   # noqa: SLF001
            row = h.storage.pr_pool("POOL1")
            self.assertEqual(row["status"], "encerrado")
            self.assertIn("estagnado", row["motivo"])
            self.assertIn("queda", row["motivo"])
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
