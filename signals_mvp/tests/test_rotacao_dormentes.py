"""PEDIDO 2026-10-30 (FASE 2, item 2/3/4): rotacao por incapacidade ESTRUTURAL (nunca toca
detector/regra de V1/V2 -- so decide QUEM fica sob observacao), lista dormente (readmissao com
prioridade) e tag `regime_amostragem`. Sem rede."""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

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
                        mc_atual: float = 50_000.0, criado_ts: float = CREATED) -> None:
    """Pool ativo, sem_fase ha mais do limiar (72h padrao, 24h se idade>=2d -- PEDIDO 2026-11-02
    FASE 1b), MC abaixo do piso -- so falta "candidato esperando vaga" pra ser rotacionado."""
    h.storage.pr_upsert_pool(pool, status="ativo", mint=f"MINT-{pool}", symbol=pool, grad_ts=GRAD,
                             added_ts=GRAD, l_bc=1_000.0, sem_fase_desde=sem_fase_desde,
                             info=json.dumps({"criado_ts": criado_ts}))
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
        """Idade < 2d (PEDIDO 2026-11-02 FASE 1b: limiar reduzido so entra a partir de 2d) --
        continua o limiar PADRAO de 72h; 71h ainda nao basta."""
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            now = GRAD + 100 * H
            _seed_ativo_incapaz(h, "POOL1", now, sem_fase_desde=now - (POS_RUNNER_ROTACAO_HORAS - 1) * H,
                               criado_ts=now - 1 * 86400.0)   # 1 dia de idade: < 2d, limiar fica 72h
            _seed_verificado(h, "CANDIDATO", mc_found=500_000.0)
            h.live._rotacionar_vagas(now)   # noqa: SLF001
            self.assertEqual(h.storage.pr_pool("POOL1")["status"], "ativo")
        finally:
            h.close()

    def test_a_young_pool_under_2_days_old_with_30h_sem_fase_is_never_rotated(self) -> None:
        """PEDIDO 2026-11-02 (FASE 1b, teste obrigatorio): pool de 1,5d com 30h de sem_fase NAO e
        aposentado -- idade < 2d, limiar continua 72h (30h < 72h)."""
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            now = GRAD + 100 * H
            _seed_ativo_incapaz(h, "POOL1", now, sem_fase_desde=now - 30 * H, criado_ts=now - 1.5 * 86400.0)
            _seed_verificado(h, "CANDIDATO", mc_found=500_000.0)
            h.live._rotacionar_vagas(now)   # noqa: SLF001
            self.assertEqual(h.storage.pr_pool("POOL1")["status"], "ativo")
        finally:
            h.close()

    def test_rotacao_thresholds_are_env_overridable(self) -> None:
        """PEDIDO 2026-11-02 (FASE 1b): nada hardcoded -- os 3 limiares sao lidos de env a cada
        chamada (mesmo padrao de `_fallback_dexpaprika_min_pendente`)."""
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            with mock.patch.dict(os.environ, {"POS_RUNNER_ROTACAO_HORAS_REDUZIDO": "5",
                                              "POS_RUNNER_ROTACAO_IDADE_MIN_DIAS": "1"}):
                self.assertEqual(h.live._rotacao_limiar_horas(1.5), 5.0)   # noqa: SLF001
            self.assertEqual(h.live._rotacao_limiar_horas(1.5), POS_RUNNER_ROTACAO_HORAS, "env restaurada: padrao de volta")
        finally:
            h.close()

    def test_a_pool_3_days_old_with_25h_sem_fase_and_low_mc_is_rotated(self) -> None:
        """PEDIDO 2026-11-02 (FASE 1b, teste obrigatorio): pool de 3d com 25h de sem_fase e MC<min_mc
        E' aposentado -- idade >= 2d, limiar cai pra 24h (25h > 24h)."""
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            now = GRAD + 100 * H
            _seed_ativo_incapaz(h, "POOL1", now, sem_fase_desde=now - 25 * H, criado_ts=now - 3 * 86400.0)
            _seed_verificado(h, "CANDIDATO", mc_found=500_000.0)
            h.live._rotacionar_vagas(now)   # noqa: SLF001
            self.assertEqual(h.storage.pr_pool("POOL1")["status"], "dormente")
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


class OaRotacaoBugReproTests(unittest.TestCase):
    """PEDIDO 2026-11-02 (diagnostico real: 0 aposentados com 60 candidatos esperando e pools como
    OA -- 8,8d, MC 3,9k, >184h sem_fase, sem candle novo >2h -- aparentemente elegiveis).

    DUAS causas, nao uma so:
    (a) `sem_fase_desde` e coluna NOVA (09d578f) sem backfill retroativo -- com so ~1h desde o
        deploy, o relogio de 72h NUNCA teria passado pra NENHUM pool ainda, mesmo sem bug algum
        (184h reais de sem_fase nunca aparecem retroativamente -- "missingness stays explicit").
        Isso sozinho ja explica aposentados=0 em 1h.
    (b) BUG real: `_persistir_fases` (unico lugar que SETA `sem_fase_desde`) so rodava DENTRO de
        `_refresh_core`, so quando um candle NOVO chegava. Um pool que NUNCA recebe NENHUM candle
        desde a promocao (`pr_bars` vazio pra sempre) nunca teria `sem_fase_desde` setado -- e
        `_retire_estagnado` TAMBEM nunca pegaria esse caso (precisa de ALGUM candle pra medir "ha
        quanto tempo sem candle novo"). Esse pool ficaria PRESO em 'ativo' pra sempre, sem
        mecanismo algum pra liberar a vaga. `_persistir_fases_todos` (todo ciclo, independente de
        candle) corrige isso.

        EMENDA 2026-11-02 (antecipar rotacao sem mudar a regra): a 1a vez que o relogio e
        preenchido, usa REPLAY causal de `pr_bars` (quando ha candle em cache) em vez de `now` --
        um pool que ja esta sem_fase ha 184h de verdade no historico fica elegivel no 1o tick,
        nunca precisa esperar mais 72h reais so porque a coluna e nova (ver
        `test_a_pool_with_a_long_sem_fase_history_becomes_eligible_on_the_first_tick`). So cai de
        volta em `now` quando NAO ha candle algum pra reconstruir o passado (caso (b) acima)."""

    def test_a_pool_stuck_without_a_fresh_candle_still_gets_sem_fase_desde_tracked(self) -> None:
        """OA tem historico (idade/MC conhecidos) mas para de receber candle novo por um tempo --
        isolado de `_retire_estagnado` (que so age em >=24h e teria precedencia -- ver docstring da
        classe) ficando BEM abaixo desse teto (20h) enquanto ainda mostra o bug/fix isolado."""
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            now0 = GRAD + H
            h.storage.pr_upsert_pool("OA", status="ativo", mint="MINT-OA", symbol="OA", grad_ts=GRAD,
                                     added_ts=GRAD, l_bc=1_000.0, quote=USDC, supply=SUPPLY,
                                     sem_fase_desde=None, info=json.dumps({"criado_ts": CREATED}))
            h.storage.pr_append_bars("OA", "1h", [(int(now0), 3_900.0, 3_900.0, 3_900.0, 3_900.0, 1.0, True)])
            # NUNCA chama `h.world.add_series` pra "OA" -- GT nunca devolve candle novo pra ele,
            # exatamente como relatado ("sem candle novo"); so avanca o relogio, nunca tick a tick.
            self.assertIsNone(h.storage.pr_pool("OA")["sem_fase_desde"], "estado inicial: nunca setado")
            _seed_verificado(h, "CANDIDATO", mc_found=500_000.0)
            # h.clock() JA comeca em GRAD+8h+120s (harness) -- avanca so o suficiente pra ficar BEM
            # abaixo de 24h de gap desde o candle (now0=GRAD+1h), nunca acionando _retire_estagnado.
            h.clock.advance(5 * H)
            h.tick()
            row = h.storage.pr_pool("OA")
            self.assertIsNotNone(row["sem_fase_desde"], "bug: sem o sweep, isso ficaria None pra sempre")
            self.assertEqual(row["status"], "ativo", "nem 24h (retire_estagnado) nem 72h (rotacao) ainda")
        finally:
            h.close()

    def test_a_pool_with_a_long_sem_fase_history_becomes_eligible_on_the_first_tick(self) -> None:
        """PEDIDO 2026-11-02 (antecipar rotacao sem mudar a regra -- segue o fix anterior): o
        relogio AINDA vazio agora e preenchido por REPLAY causal de `pr_bars` (MESMO calculo de
        `scripts/diagnostico_vagas.py: _horas_sem_fase_combinada` -- desde o 1o candle em cache,
        que nunca teve fase) em vez de `now` -- um pool com 184h de historico sem_fase fica
        elegivel (>72h) no 1o tick, nunca precisa esperar mais 72h reais so porque a coluna e
        nova. Candles HORARIOS continuos (nunca so 1) ate perto de "agora" -- isola de
        `_retire_estagnado` (24h sem candle NOVO), que senao venceria a corrida e marcaria
        'encerrado' antes da rotacao rodar."""
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            now0 = h.clock()
            primeiro_candle_ts = now0 - 184 * H
            h.storage.pr_upsert_pool("OA", status="ativo", mint="MINT-OA", symbol="OA", grad_ts=GRAD,
                                     added_ts=GRAD, l_bc=1_000.0, quote=USDC, supply=SUPPLY,
                                     sem_fase_desde=None, info=json.dumps({"criado_ts": CREATED}))
            bars = []
            t = primeiro_candle_ts
            while t <= now0 - H:   # ultimo candle ha so 1h -- bem abaixo do teto de 24h de _retire_estagnado
                bars.append((int(t), 3_900.0, 3_900.0, 3_900.0, 3_900.0, 1.0, True))
                t += H
            h.storage.pr_append_bars("OA", "1h", bars)
            _seed_verificado(h, "CANDIDATO", mc_found=500_000.0)
            h.tick()
            row = h.storage.pr_pool("OA")
            self.assertAlmostEqual(row["sem_fase_desde"], primeiro_candle_ts, delta=1.0,
                                   msg="relogio devia comecar no 1o candle em cache (replay), nunca em `now`")
            self.assertEqual(row["status"], "dormente", "184h de replay > 72h -- elegivel e rotacionado no 1o tick")
            self.assertEqual(h.storage.pr_sem_fase_desde_replay_count_desde(0.0), 1)
        finally:
            h.close()


class SemFaseDesdeReplayTests(unittest.TestCase):
    """PEDIDO 2026-11-02 (antecipar rotacao sem mudar a regra): testes diretos de
    `_sem_fase_desde_por_replay` -- funcao PURA (zero rede, zero toque no detector ao vivo, zero
    grava/conta -- isso e responsabilidade de quem chama: `_persistir_fases`, que conta o
    preenchimento inicial em `pr_sem_fase_desde_replay`, ver `OaRotacaoBugReproTests`/
    `FASE1aRelogioCorrigidoTests`)."""

    def _pool(self, h: LiveHarness, pool: str, bars: list) -> None:
        h.storage.pr_upsert_pool(pool, status="ativo", mint=f"MINT-{pool}", symbol=pool, grad_ts=GRAD,
                                 added_ts=GRAD, l_bc=1_000.0, quote=USDC, supply=SUPPLY,
                                 sem_fase_desde=None, info=json.dumps({"criado_ts": CREATED}))
        h.storage.pr_append_bars(pool, "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume, b.filled) for b in bars])

    def test_returns_the_first_cached_candle_when_the_pool_never_had_a_fase(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            bars = [Bar(GRAD + i * H, 3_900.0, 3_950.0, 3_850.0, 3_900.0, 1.0) for i in range(5)]
            self._pool(h, "POOL1", bars)
            resultado = h.live._sem_fase_desde_por_replay("POOL1", GRAD + 100 * H)   # noqa: SLF001
            self.assertEqual(resultado, float(GRAD))
            self.assertEqual(h.storage.pr_sem_fase_desde_replay_count_desde(0.0), 0, "funcao pura: nunca conta por si")
        finally:
            h.close()

    def test_returns_none_when_the_pool_is_really_active_right_now(self) -> None:
        """Pico (1M) -> queda 85% -> ultimo candle ainda em pullback: NUNCA grava um relogio (None),
        mesmo chamado de dentro do ramo "ambos_sem_fase" trivial de uma tf que a V1/V2 nunca usa."""
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            bars = [
                Bar(GRAD, 100_000.0, 100_000.0, 95_000.0, 100_000.0, 1_000.0),
                Bar(GRAD + H, 100_000.0, 1_000_000.0, 950_000.0, 950_000.0, 1_000.0),           # pico
                Bar(GRAD + 2 * H, 950_000.0, 960_000.0, 150_000.0, 150_000.0, 1_000.0),         # queda 85%
                Bar(GRAD + 3 * H, 155_000.0, 158_000.0, 152_000.0, 155_000.0, 1_000.0),         # pullback ativo
            ]
            self._pool(h, "POOL1", bars)
            resultado = h.live._sem_fase_desde_por_replay("POOL1", GRAD + 3 * H + 10.0)   # noqa: SLF001
            self.assertIsNone(resultado)
            self.assertEqual(h.storage.pr_sem_fase_desde_replay_count_desde(0.0), 0, "nunca conta quando fica None")
        finally:
            h.close()

    def test_falls_back_to_now_when_there_is_no_cached_candle_at_all(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            h.storage.pr_upsert_pool("POOL1", status="ativo", mint="MINT-POOL1", symbol="POOL1", grad_ts=GRAD,
                                     added_ts=GRAD, l_bc=1_000.0, quote=USDC, supply=SUPPLY,
                                     sem_fase_desde=None, info=json.dumps({"criado_ts": CREATED}))
            now = GRAD + 100 * H
            resultado = h.live._sem_fase_desde_por_replay("POOL1", now)   # noqa: SLF001
            self.assertEqual(resultado, now)
            self.assertEqual(h.storage.pr_sem_fase_desde_replay_count_desde(0.0), 0, "sem candle: nunca conta como replay")
        finally:
            h.close()


class FASE1aRelogioCorrigidoTests(unittest.TestCase):
    """PEDIDO 2026-11-02 (FASE 1a): `_persistir_fases` conta o preenchimento inicial
    (`pr_sem_fase_desde_replay`); `_corrigir_relogios_por_replay`/`_corrigir_relogios_periodico`
    ADIANTAM um relogio JA gravado (nunca o preenchem do zero) e contam em
    `pr_sem_fase_desde_corrigido`."""

    def _pool_sem_fase_longa(self, h: LiveHarness, pool: str = "POOL1") -> int:
        """184 candles horarios continuos, MC sempre abaixo de runner_min_mc -- `primeiro_candle_ts`
        e o valor que o replay deveria encontrar."""
        now0 = h.clock()
        primeiro_candle_ts = now0 - 184 * H
        h.storage.pr_upsert_pool(pool, status="ativo", mint=f"MINT-{pool}", symbol=pool, grad_ts=GRAD,
                                 added_ts=GRAD, l_bc=1_000.0, quote=USDC, supply=SUPPLY,
                                 sem_fase_desde=None, info=json.dumps({"criado_ts": CREATED}))
        bars = []
        t = primeiro_candle_ts
        while t <= now0 - H:
            bars.append((int(t), 3_900.0, 3_900.0, 3_900.0, 3_900.0, 1.0, True))
            t += H
        h.storage.pr_append_bars(pool, "1h", bars)
        return int(primeiro_candle_ts)

    def test_persistir_fases_counts_the_initial_fill(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            primeiro = self._pool_sem_fase_longa(h)
            h.live._persistir_fases("POOL1", h.live.params_v1.timeframes[0], h.clock())   # noqa: SLF001
            row = h.storage.pr_pool("POOL1")
            self.assertAlmostEqual(row["sem_fase_desde"], float(primeiro), delta=1.0)
            self.assertEqual(h.storage.pr_sem_fase_desde_replay_count_desde(0.0), 1)
            self.assertEqual(h.storage.pr_sem_fase_desde_corrigido_count_desde(0.0), 0, "preenchimento, nunca correcao")
        finally:
            h.close()

    def test_correction_advances_a_clock_stamped_as_now_before_this_fix_existed(self) -> None:
        """Simula o caso real (restart de 02/11 16:11Z): `sem_fase_desde` gravado como `now` de um
        tick antigo, bem mais recente que o 1o candle real em cache."""
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            primeiro = self._pool_sem_fase_longa(h)
            gravado_errado = h.clock() - 2 * H   # bem depois do 1o candle real (184h atras)
            h.storage.pr_upsert_pool("POOL1", sem_fase_desde=gravado_errado)
            corrigidos = h.live._corrigir_relogios_por_replay(h.clock())   # noqa: SLF001
            self.assertEqual(corrigidos, 1)
            row = h.storage.pr_pool("POOL1")
            self.assertAlmostEqual(row["sem_fase_desde"], float(primeiro), delta=1.0)
            self.assertEqual(h.storage.pr_sem_fase_desde_corrigido_count_desde(0.0), 1)
        finally:
            h.close()

    def test_correction_never_makes_a_clock_worse(self) -> None:
        """Relogio ja gravado MAIS antigo que o replay encontraria (ex.: alguem gravou na mao, ou
        um candle antigo saiu do cache) -- nunca atrasa, so adianta."""
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            primeiro = self._pool_sem_fase_longa(h)
            gravado_ja_melhor = float(primeiro) - 1000.0
            h.storage.pr_upsert_pool("POOL1", sem_fase_desde=gravado_ja_melhor)
            corrigidos = h.live._corrigir_relogios_por_replay(h.clock())   # noqa: SLF001
            self.assertEqual(corrigidos, 0)
            self.assertEqual(h.storage.pr_pool("POOL1")["sem_fase_desde"], gravado_ja_melhor)
        finally:
            h.close()

    def test_correction_skips_a_pool_currently_in_pullback_or_with_an_open_position(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            h.storage.pr_upsert_pool("POOL1", status="ativo", mint="MINT1", symbol="POOL1", grad_ts=GRAD,
                                     l_bc=1_000.0, quote=USDC, supply=SUPPLY, sem_fase_desde=h.clock() - H,
                                     fase_v1="pullback", info=json.dumps({"criado_ts": CREATED}))
            corrigidos = h.live._corrigir_relogios_por_replay(h.clock())   # noqa: SLF001
            self.assertEqual(corrigidos, 0)
        finally:
            h.close()

    def test_periodico_runs_at_startup_and_then_waits_6h(self) -> None:
        h = LiveHarness(settings=SETTINGS_MAX1)
        try:
            self._pool_sem_fase_longa(h)
            gravado_errado = h.clock() - 2 * H
            h.storage.pr_upsert_pool("POOL1", sem_fase_desde=gravado_errado)
            h.live._corrigir_relogios_periodico(h.clock())   # 1a chamada: corrige   # noqa: SLF001
            self.assertEqual(h.storage.pr_sem_fase_desde_corrigido_count_desde(0.0), 1)
            # regrava errado de proposito e chama de novo logo depois -- dentro das 6h, nunca corrige
            h.storage.pr_upsert_pool("POOL1", sem_fase_desde=gravado_errado)
            h.live._corrigir_relogios_periodico(h.clock() + H)   # noqa: SLF001
            self.assertEqual(h.storage.pr_sem_fase_desde_corrigido_count_desde(0.0), 1, "ainda dentro de 6h")
            h.live._corrigir_relogios_periodico(h.clock() + 7 * H)   # noqa: SLF001
            self.assertEqual(h.storage.pr_sem_fase_desde_corrigido_count_desde(0.0), 2, "passou de 6h")
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
