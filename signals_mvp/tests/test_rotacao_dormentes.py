"""PEDIDO 2026-10-30 (FASE 2, item 2/3/4): rotacao por incapacidade ESTRUTURAL (nunca toca
detector/regra de V1/V2 -- so decide QUEM fica sob observacao), lista dormente (readmissao com
prioridade) e tag `regime_amostragem`. Sem rede."""

from __future__ import annotations

import json
import unittest

from ..http import CallBudget
from ..pos_runner.candles import Bar
from ..pos_runner.detector_v1 import DetectorV1
from ..pos_runner.live import POS_RUNNER_ROTACAO_HORAS, LiveSettings
from .test_pos_runner import CREATED
from .test_pos_runner_live import GRAD, H, SUPPLY, USDC, LiveHarness, start_tracking


def _recheck_dormentes_armado(h: LiveHarness, now: float) -> None:
    """`_recheck_dormentes` so faz chamada de rede dentro do orcamento ARMADO (`tick()` arma antes de
    chamar) -- chamado isolado (unit-level, como o resto desta suite) precisa armar manualmente."""
    h.live.http.arm(CallBudget(10), 1, 1)
    try:
        h.live._recheck_dormentes(now)   # noqa: SLF001
    finally:
        h.live.http.disarm()


SETTINGS_MAX1 = LiveSettings(ligado=True, timeframes=("1h",), max_pools=1, chamadas_por_ciclo=3,
                             descoberta_min=3, fontes=("pumpswap",), grafico=False)


def _seed_verificado(h: LiveHarness, pool: str, mc_found: float, grad_ts: float = GRAD,
                     criado_ts: float = CREATED, info_extra: dict | None = None) -> None:
    info = {"criado_ts": criado_ts, **(info_extra or {})}
    h.storage.pr_upsert_pool(pool, status="verificado", mint=f"MINT-{pool}", symbol=pool, grad_ts=grad_ts,
                             mc_found=mc_found, dex="pumpswap", launchpad="pumpfun", info=json.dumps(info))


def _seed_ativo_incapaz(h: LiveHarness, pool: str, now: float, sem_fase_desde: float,
                        mc_atual: float = 50_000.0) -> None:
    """Pool ativo, sem_fase ha mais de `POS_RUNNER_ROTACAO_HORAS`, MC abaixo do piso -- so falta
    "candidato esperando vaga" pra ser rotacionado."""
    h.storage.pr_upsert_pool(pool, status="ativo", mint=f"MINT-{pool}", symbol=pool, grad_ts=GRAD,
                             added_ts=GRAD, l_bc=1_000.0, sem_fase_desde=sem_fase_desde,
                             info=json.dumps({"criado_ts": CREATED}))
    h.storage.pr_append_bars(pool, "1h", [(int(now), mc_atual, mc_atual, mc_atual, mc_atual, 1.0, True)])


class RotacaoVagasTests(unittest.TestCase):
    def test_a_pool_meeting_all_structural_incapacity_conditions_is_rotated_to_dormente(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            now = GRAD + 100 * H
            _seed_ativo_incapaz(h, "POOL1", now, sem_fase_desde=now - (POS_RUNNER_ROTACAO_HORAS + 1) * H)
            _seed_verificado(h, "CANDIDATO", mc_found=500_000.0)   # candidato esperando vaga
            h.live._rotacionar_vagas(now)   # noqa: SLF001
            row = h.storage.pr_pool("POOL1")
            self.assertEqual(row["status"], "dormente")
            dormentes = h.storage.pr_dormentes("dormente")
            self.assertEqual(len(dormentes), 1)
            self.assertEqual(dormentes[0]["pool"], "POOL1")
            self.assertIsNotNone(h.storage.pr_rotacao_ativacao_ts_get())
        finally:
            h.close()

    def test_never_rotates_without_a_waiting_candidate(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            now = GRAD + 100 * H
            _seed_ativo_incapaz(h, "POOL1", now, sem_fase_desde=now - (POS_RUNNER_ROTACAO_HORAS + 1) * H)
            h.live._rotacionar_vagas(now)   # noqa: SLF001
            self.assertEqual(h.storage.pr_pool("POOL1")["status"], "ativo")
        finally:
            h.close()

    def test_never_rotates_before_the_sem_fase_threshold(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            now = GRAD + 100 * H
            _seed_ativo_incapaz(h, "POOL1", now, sem_fase_desde=now - (POS_RUNNER_ROTACAO_HORAS - 1) * H)
            _seed_verificado(h, "CANDIDATO", mc_found=500_000.0)
            h.live._rotacionar_vagas(now)   # noqa: SLF001
            self.assertEqual(h.storage.pr_pool("POOL1")["status"], "ativo")
        finally:
            h.close()

    def test_never_rotates_a_pool_in_runner_or_pullback(self) -> None:
        """`sem_fase_desde` so existe quando V1 E V2 estao sem_fase -- um pool em runner/pullback
        NUNCA tem `sem_fase_desde` setado (fica NULL), nunca entra na lista de candidatos."""
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            now = GRAD + 100 * H
            h.storage.pr_upsert_pool("POOL1", status="ativo", mint="MINT1", symbol="CAT", grad_ts=GRAD,
                                     added_ts=GRAD, l_bc=1_000.0, sem_fase_desde=None,
                                     info=json.dumps({"criado_ts": CREATED}))
            h.storage.pr_append_bars("POOL1", "1h", [(int(now), 50_000.0, 50_000.0, 50_000.0, 50_000.0, 1.0, True)])
            _seed_verificado(h, "CANDIDATO", mc_found=500_000.0)
            h.live._rotacionar_vagas(now)   # noqa: SLF001
            self.assertEqual(h.storage.pr_pool("POOL1")["status"], "ativo")
        finally:
            h.close()

    def test_never_rotates_a_pool_with_an_open_position(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(20)
            abertos = h.storage.pr1_signals(status="aberto")
            self.assertEqual(len(abertos), 1, h.texts())
            pool = abertos[0]["pool"]
            now = h.clock() + 100 * H
            h.storage.pr_upsert_pool(pool, sem_fase_desde=now - (POS_RUNNER_ROTACAO_HORAS + 1) * H)
            det = h.live.dets_v1.get((pool, "1h"))
            det.peak, det.trough = 1_000_000.0, 4_000.0   # queda > 96% -- incapaz
            _seed_verificado(h, "CANDIDATO", mc_found=500_000.0)
            h.live._rotacionar_vagas(now)   # noqa: SLF001
            self.assertEqual(h.storage.pr_pool(pool)["status"], "ativo")
        finally:
            h.close()

    def test_max_rotations_per_hour_is_respected(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            now = GRAD + 100 * H
            for i in range(3):
                _seed_ativo_incapaz(h, f"POOL{i}", now, sem_fase_desde=now - (POS_RUNNER_ROTACAO_HORAS + 1) * H)
            for i in range(3):
                _seed_verificado(h, f"CAND{i}", mc_found=500_000.0 - i)
            h.live._rotacionar_vagas(now)   # noqa: SLF001
            rotacionados = sum(1 for i in range(3) if h.storage.pr_pool(f"POOL{i}")["status"] == "dormente")
            self.assertEqual(rotacionados, h.live.rotacao_max_por_hora)
        finally:
            h.close()

    def test_sem_rotacao_env_disables_everything(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1, sem_rotacao=True)
        try:
            now = GRAD + 100 * H
            _seed_ativo_incapaz(h, "POOL1", now, sem_fase_desde=now - (POS_RUNNER_ROTACAO_HORAS + 1) * H)
            _seed_verificado(h, "CANDIDATO", mc_found=500_000.0)
            h.live._rotacionar_vagas(now)   # noqa: SLF001
            self.assertEqual(h.storage.pr_pool("POOL1")["status"], "ativo")
        finally:
            h.close()


class PersistirFasesSemFaseDesdeTests(unittest.TestCase):
    def test_sem_fase_desde_is_set_when_both_versions_go_sem_fase_and_cleared_when_active(self) -> None:
        h = LiveHarness()
        try:
            h.storage.pr_upsert_pool("POOL1", status="ativo", mint="MINT1", symbol="CAT", grad_ts=GRAD)
            now1 = GRAD + H
            h.live._persistir_fases("POOL1", "1h", now1)   # noqa: SLF001 -- nenhum detector: sem_fase/sem_fase
            self.assertEqual(h.storage.pr_pool("POOL1")["sem_fase_desde"], now1)
            now2 = now1 + H
            h.live._persistir_fases("POOL1", "1h", now2)   # noqa: SLF001 -- continua sem_fase: nao avanca
            self.assertEqual(h.storage.pr_pool("POOL1")["sem_fase_desde"], now1)
            det = DetectorV1(h.live.params_v1, "1h", 1_000.0, GRAD, CREATED)
            det.phase = 1   # PHASE_RUNNER -- ativo agora
            h.live.dets_v1[("POOL1", "1h")] = det
            now3 = now2 + H
            h.live._persistir_fases("POOL1", "1h", now3)   # noqa: SLF001
            self.assertIsNone(h.storage.pr_pool("POOL1")["sem_fase_desde"])
        finally:
            h.close()


class RecheckDormentesTests(unittest.TestCase):
    def test_a_dormant_pool_with_recovered_mc_is_readmitted_with_priority(self) -> None:
        h = LiveHarness()
        try:
            now = h.clock()
            # MESMO quote/supply usados em qualquer pool normal -- `_recheck_dormentes` passa pela
            # MESMA conversao token->MC USD de `_refresh_core` (`to_mc_bars`/`self.quotes.series`).
            h.storage.pr_upsert_pool("POOL1", status="dormente", mint="MINT1", symbol="CAT", grad_ts=GRAD,
                                     quote=USDC, supply=SUPPLY,
                                     info=json.dumps({"criado_ts": CREATED, "side": "base"}))
            h.storage.pr_dormente_insert("POOL1", "MINT1", "CAT", "rotacao: teste", 50_000.0, now)
            # MC (USD) acima do piso de 100k -- add_series ja converte p/ preco bruto (MC/SUPPLY).
            h.world.add_series("POOL1", "1h", [Bar(int(now) - H, 200_000.0, 200_000.0, 200_000.0, 200_000.0, 1.0)])
            _recheck_dormentes_armado(h, now)
            row = h.storage.pr_pool("POOL1")
            self.assertEqual(row["status"], "verificado")
            self.assertTrue(json.loads(row["info"] or "{}").get("readmitido_dormente"))
            d = h.storage.pr_dormentes("readmitido")
            self.assertEqual(len(d), 1)
            self.assertIsNotNone(d[0]["ts_readmitido"])
        finally:
            h.close()

    def test_a_dormant_pool_still_below_the_floor_is_not_readmitted(self) -> None:
        h = LiveHarness()
        try:
            now = h.clock()
            h.storage.pr_upsert_pool("POOL1", status="dormente", mint="MINT1", symbol="CAT", grad_ts=GRAD,
                                     quote=USDC, supply=SUPPLY,
                                     info=json.dumps({"criado_ts": CREATED, "side": "base"}))
            h.storage.pr_dormente_insert("POOL1", "MINT1", "CAT", "rotacao: teste", 50_000.0, now)
            h.world.add_series("POOL1", "1h", [Bar(int(now) - H, 20_000.0, 20_000.0, 20_000.0, 20_000.0, 1.0)])
            _recheck_dormentes_armado(h, now)
            self.assertEqual(h.storage.pr_pool("POOL1")["status"], "dormente")
            d = h.storage.pr_dormentes("dormente")
            self.assertEqual(len(d), 1)
            self.assertIsNotNone(d[0]["ts_recheck_ultimo"], "atualiza o recheck mesmo sem readmitir")
        finally:
            h.close()

    def test_only_one_dormant_pool_is_checked_per_tick_oldest_recheck_first(self) -> None:
        h = LiveHarness()
        try:
            now = h.clock()
            for nome, recheck_ha in (("VELHO", 48 * H), ("NOVO", 25 * H)):
                h.storage.pr_upsert_pool(nome, status="dormente", mint=f"MINT-{nome}", symbol=nome, grad_ts=GRAD,
                                         quote=USDC, supply=SUPPLY, info=json.dumps({"side": "base"}))
                dor_id = h.storage.pr_dormente_insert(nome, f"MINT-{nome}", nome, "rotacao: teste", 50_000.0, now)
                h.storage.pr_dormente_update(dor_id, ts_recheck_ultimo=now - recheck_ha)
                h.world.add_series(nome, "1h", [Bar(int(now) - H, 20_000.0, 20_000.0, 20_000.0, 20_000.0, 1.0)])
            _recheck_dormentes_armado(h, now)
            atualizados = [d for d in h.storage.pr_dormentes("dormente") if d["ts_recheck_ultimo"] == now]
            self.assertEqual([d["pool"] for d in atualizados], ["VELHO"])
        finally:
            h.close()

    def test_readmitted_pool_is_promoted_before_a_higher_mc_new_candidate(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            now = GRAD + 10 * H
            h.storage.pr_upsert_pool("DORMIU", status="verificado", mint="MINT-DORMIU", symbol="DORMIU", grad_ts=GRAD,
                                     mc_found=1_000.0,   # mc_found BAIXO -- so a prioridade de readmissao salva
                                     info=json.dumps({"criado_ts": CREATED, "readmitido_dormente": True}))
            _seed_verificado(h, "NOVO", mc_found=10_000_000.0)   # MC muito maior, mas nunca foi dormente
            h.live._promote(now)   # noqa: SLF001
            self.assertEqual({r["pool"] for r in h.storage.pr_pools("ativo")}, {"DORMIU"})
        finally:
            h.close()


class RegimeAmostragemTests(unittest.TestCase):
    def test_a_new_signal_before_any_rotation_is_tagged_pre_rotacao(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)
            sinal = h.storage.pr1_signals()[0]
            self.assertEqual(sinal["regime_amostragem"], "pre_rotacao")
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
