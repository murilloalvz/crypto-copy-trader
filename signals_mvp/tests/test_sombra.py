"""PEDIDO (PARTE 2A) FASE 3: sombra dos filtros filtrado_mc_baixo/filtrado_idade e da ONDA_INVALIDA de
queda extrema (96-99,5%, "queda_96_mais" -- a V2 ja cobre 90-96%) -- MEDICAO AO LADO (reusa o MESMO
`DetectorV1`/`simulate_v1` da V1, nunca duplica deteccao), nunca altera deteccao/entrada/saida/banca/
CSV oficiais de V1/V2 (`EquivalenciaSombraTests` abaixo prova isso byte a byte). Sem rede."""

from __future__ import annotations

import json
import unittest

from ..pos_runner.candles import Bar
from ..pos_runner.detector_v1 import EventV1
from ..pos_runner.live import LineageVerifier
from .test_pos_runner import GRAD, H, flat, textbook
from .test_pos_runner_live import LiveHarness, created_at, ok_lineage, start_tracking
from .test_pos_runner_v1_live import _entrada_v1, _watch_v1


def _mc_baixo_bars() -> list[Bar]:
    """MESMA forma do textbook() (zona/teste/rompimento do Setup 1), so ESCALADA e com o FECHAMENTO de
    TODO candle grudado em <=95.000 (abaixo do piso `filtrado_mc_baixo` da V1/V2, 100.000) -- so a
    MAXIMA de 1 candle (o pico, idx 6) chega a 320.000 (>= runner_min_mc=300.000, via pavio, nunca o
    fechamento). `l_bc` ao vivo = open do 1o candle (`_refresh_core`: `l_bc=seq[0].open`) -- fica em
    ~19.200, abaixo do fundo real (~48.000*k), nunca fura o nivel de graduacao."""
    s = textbook()
    k, cap = 0.32, 95_000.0
    bars = []
    for i, b in enumerate(s.bars):
        o, h, l, c = b.open * k, b.high * k, b.low * k, b.close * k
        o, c = min(o, cap), min(c, cap)
        l = min(l, o, c)
        if i != 6:
            h = max(l, min(h, cap))
        bars.append(Bar(b.ts, o, h, l, c, b.volume))
    return bars


def _queda_96_mais_bars() -> list[Bar]:
    """MESMO textbook(), so com `bottom`/`test_low` bem mais profundos -- queda de 97,5% do pico. A V1
    (drop_max=0,90) e a V2 (drop_max=0,96) matam a onda como ONDA_INVALIDA; so a sombra (drop_max=
    0,995) ve o gatilho. Os 2 primeiros candles (flat de preenchimento, nunca parte da zona) ficam
    mais baixos pra `l_bc` (= open do 1o candle) nao furar o fundo (0,995 ja cobre o drop; o teto de
    L_bc e um check SEPARADO, sempre ativo nos 3 detectores)."""
    s = textbook(bottom=25_000.0, test_low=25_500.0)
    bars = list(s.bars)
    bars[0] = flat(bars[0].ts, 20_000.0)
    bars[1] = flat(bars[1].ts, 20_000.0)
    return bars


class FiltradoMcBaixoSombraTests(unittest.TestCase):
    """Candidato cujo MC (fechamento do candle, igual ao filtro real) NUNCA cruza o piso de
    `filtrado_mc_baixo` -- a V1/V2 OFICIAIS nunca constroem detector pra esse (pool,tf) (nunca alertam,
    nunca entram na banca/CSV), mas o gatilho teria disparado (detector sombra PARALELO, sem o piso)."""

    def test_candidate_that_never_crosses_the_mc_floor_is_recorded_as_sombra_and_never_as_a_real_signal(self) -> None:
        # sem_v0=True de proposito NUNCA usado aqui: com V0/V1/V2 TODOS bloqueados (mc_baixo bloqueia
        # V1/V2; sem_v0 desligaria o unico detector que sobraria), `last`/`seq` em `_refresh_core`
        # (ancorados so em det/det_v1/det_v2) nunca avancam incrementalmente -- o V0 (sem piso de MC
        # equivalente) continua ligado so pra ancorar isso; nunca lido pelas asserções abaixo.
        h = LiveHarness()
        try:
            h.world.add_series("POOL1", "1h", _mc_baixo_bars())
            h.list_pool()
            h.tick()
            h.verifier.step()
            h.tick()
            h.run_hours(30)
            self.assertEqual(h.storage.pr1_signals(), [], "nunca pode virar sinal real da V1")
            self.assertEqual(h.storage.pr2_signals(), [], "nunca pode virar sinal real da V2")
            self.assertEqual(_entrada_v1(h), [], "nunca pode alertar como entrada real")
            counts = h.storage.pr1_filtrado_counts(0.0)
            self.assertGreaterEqual(counts.get("filtrado_mc_baixo", 0), 1)
            sombra = h.storage.pr_sombra_signals(versao="sombra:filtrado_mc_baixo")
            self.assertEqual(len(sombra), 1, h.texts())
            row = sombra[0]
            self.assertEqual(row["pool"], "POOL1")
            self.assertEqual(row["tf"], "1h")
            self.assertIn("reacao_suporte", json.loads(row["gatilho"]))
            self.assertIsNotNone(row["entry_price"])
            self.assertIsNone(row["result_net"], "ainda sem desfecho -- nunca inventa um numero")
        finally:
            h.close()

    def test_once_the_real_mc_floor_is_crossed_the_shadow_stops_and_never_competes(self) -> None:
        """Cenario PADRAO da V1 (MC bem acima do piso o tempo todo): a sombra de mc_baixo nunca deveria
        sequer abrir -- `_detector_sombra_mc` devolve None direto (ja existe detector oficial)."""
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)
            self.assertEqual(len(h.storage.pr1_signals()), 1)
            self.assertEqual(h.storage.pr_sombra_signals(versao="sombra:filtrado_mc_baixo"), [])
        finally:
            h.close()


class Queda96MaisSombraTests(unittest.TestCase):
    """Onda que cai 96-99,5% do pico -- a V1 e a V2 (drop_max 0,90/0,96) matam como ONDA_INVALIDA;
    so a sombra (drop_max 0,995) ve o gatilho. Unica sombra com aviso curto no Telegram."""

    def test_candidate_beyond_v1_v2_drop_max_is_recorded_and_sends_the_short_telegram_notice(self) -> None:
        h = LiveHarness(sem_v0=True)
        try:
            h.world.add_series("POOL1", "1h", _queda_96_mais_bars())
            h.list_pool()
            h.tick()
            h.verifier.step()
            h.tick()
            h.run_hours(30)
            self.assertEqual(h.storage.pr1_signals(), [], "V1 (drop_max=0,90) tem que matar a onda")
            self.assertEqual(h.storage.pr2_signals(), [], "V2 (drop_max=0,96) tambem tem que matar a onda")
            self.assertEqual(_entrada_v1(h), [])
            self.assertEqual(_watch_v1(h), [])
            sombra = h.storage.pr_sombra_signals(versao="sombra:queda_96_mais")
            self.assertEqual(len(sombra), 1, h.texts())
            self.assertGreater(sombra[0]["queda_pct"], 96.0)
            self.assertLessEqual(sombra[0]["queda_pct"], 99.5)
            avisos = [t for t in h.texts() if "SOMBRA" in t]
            self.assertEqual(len(avisos), 1, h.texts())
            self.assertIn("NÃO VALIDADO", avisos[0])
            self.assertIn("queda extrema", avisos[0])
            self.assertNotIn("👍", avisos[0])     # sem botoes de entrada/feedback
        finally:
            h.close()

    def test_a_drop_at_or_below_96_percent_is_never_double_counted_as_sombra(self) -> None:
        """Queda <=96% ja e territorio REAL da V2 (gera ENTRADA de verdade) -- nunca duplicada aqui."""
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)
            self.assertEqual(len(h.storage.pr2_signals()), 1)   # queda ~85%, dentro do drop_max da V2
            self.assertEqual(h.storage.pr_sombra_signals(versao="sombra:queda_96_mais"), [])
        finally:
            h.close()


def _base_min4_bars() -> list[Bar]:
    """MESMO `textbook()`, so com a caixa mais CURTA (`range_len=6`, confirmado por construcao: o
    gatilho real dispara com `box_len=8`) -- a V1 (`zone_min_candles=12`) nunca arma a zona a tempo;
    so a sombra (`zone_min_candles=4`) ve o gatilho."""
    return textbook(range_len=6).bars


class BaseMin4SombraTests(unittest.TestCase):
    """PEDIDO 2026-10-29 (item 3): caixa mais curta que `zone_min_candles=12` da V1 -- so a sombra
    `base_min4` (`zone_min_candles=4`) ve o gatilho. `caixa_candles` (tamanho_base_candles) persistido
    via `_contexto_execucao`, mesma coluna de pr1_signals/pr2_signals."""

    def test_a_shorter_box_than_the_real_v1_minimum_is_recorded_as_sombra(self) -> None:
        h = LiveHarness(sem_v0=True)
        try:
            h.world.add_series("POOL1", "1h", _base_min4_bars())
            h.list_pool()
            h.tick()
            h.verifier.step()
            h.tick()
            h.run_hours(30)
            self.assertEqual(h.storage.pr1_signals(), [], "caixa curta demais pra V1 real (zone_min_candles=12)")
            self.assertEqual(_entrada_v1(h), [])
            sombra = h.storage.pr_sombra_signals(versao="sombra:base_min4")
            self.assertEqual(len(sombra), 1, h.texts())
            self.assertEqual(sombra[0]["caixa_candles"], 8)
            self.assertIsNotNone(sombra[0]["entry_price"])
        finally:
            h.close()

    def test_a_box_at_or_above_the_real_v1_minimum_is_never_recorded(self) -> None:
        """box_len >= zone_min_candles da V1 (12) ja e territorio que a V1 real cobriria dali em
        diante -- nunca um candidato NOVO (mesmo raciocinio de `queda_96_mais`/`filtrado_idade`).
        Unitario e direto em `_on_event_sombra`: no cenario padrao (`start_tracking`) a sombra
        `base_min4` costuma disparar ANTES da V1 real, com um box_len genuinamente MENOR (near-miss
        legitimo, nao duplicado) -- e por isso que o filtro precisa ser testado isolado, nao so
        contra o cenario end-to-end padrao."""
        row = {"pool": "POOL1", "mint": "MINT1", "symbol": "CAT", "info": "{}"}
        h = LiveHarness()
        try:
            ev_igual = EventV1("ENTRADA", 10, 0, 0, {"box_len": 12, "gatilho": [], "close": 1.0, "stop": 0.5})
            h.live._on_event_sombra(row, "1h", ev_igual, h.clock(), "base_min4")   # noqa: SLF001
            self.assertEqual(h.storage.pr_sombra_signals(versao="sombra:base_min4"), [])
            ev_abaixo = EventV1("ENTRADA", 10, 0, 1, {"box_len": 11, "gatilho": [], "close": 1.0, "stop": 0.5})
            h.live._on_event_sombra(row, "1h", ev_abaixo, h.clock(), "base_min4")   # noqa: SLF001
            self.assertEqual(len(h.storage.pr_sombra_signals(versao="sombra:base_min4")), 1)
        finally:
            h.close()

    def test_sombra_max_pools_cap_counts_base_min4_slots_too(self) -> None:
        h = LiveHarness(sombra_max_pools=1)
        try:
            h.live.dets_sombra_base4[("OUTRO_POOL", "1h")] = object()
            self.assertFalse(h.live._sombra_abrir_slot(("POOL1", "1h")))   # noqa: SLF001
            self.assertEqual(h.storage.pr_sombra_descarte_count(), 1)
        finally:
            h.close()


class FiltradoIdadeSombraTests(unittest.TestCase):
    """V1 e V2 compartilham a MESMA idade MINIMA (2 dias) -- so o teto diverge (V1: 7d; V2: ~sem teto).
    Candidato mais novo que 2 dias e barrado pelas 2 (sombra genuina); mais velho que 7d so a V1 barra
    (a V2 ja cobre, entrada REAL -- nunca sombra)."""

    def test_candidate_younger_than_the_shared_2day_floor_is_recorded_as_sombra(self) -> None:
        h = LiveHarness()
        try:
            h.world.add_series("POOL1", "1h", textbook().bars)
            h.list_pool()
            h.verifier = LineageVerifier(h.storage, None, clock=h.clock, verify=ok_lineage(),
                                         creation=created_at(ts=GRAD))   # criado ~1 dia antes: < 2 dias
            h.tick()
            h.verifier.step()
            h.tick()
            h.run_hours(17)
            self.assertEqual(_entrada_v1(h), [])
            self.assertEqual(h.storage.pr1_signals(), [])
            self.assertEqual(h.storage.pr2_signals(), [], "idade < 2 dias e barrada pelas 2 (minimo compartilhado)")
            sombra = h.storage.pr_sombra_signals(versao="sombra:filtrado_idade")
            self.assertEqual(len(sombra), 1, h.texts())
        finally:
            h.close()

    def test_candidate_older_than_v1s_7day_ceiling_is_never_sombra_v2_already_takes_it_live(self) -> None:
        """Acima do teto da V1 (7d) a V2 (teto ~sem limite) ja gera ENTRADA REAL -- nunca sombra (e
        exatamente o mesmo raciocinio do `filtrado_queda_90_96`: o que uma das 2 ja cobre ao vivo nunca
        duplica como sombra)."""
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)
            self.assertEqual(len(h.storage.pr2_signals()), 1)
            self.assertEqual(h.storage.pr_sombra_signals(versao="sombra:filtrado_idade"), [])
        finally:
            h.close()


class SombraTetoTests(unittest.TestCase):
    def test_sombra_max_pools_discards_new_candidates_once_the_cap_is_reached(self) -> None:
        h = LiveHarness(sombra_max_pools=1)
        try:
            h.live.dets_sombra_mc[("OUTRO_POOL", "1h")] = object()
            self.assertFalse(h.live._sombra_abrir_slot(("POOL1", "1h")))   # noqa: SLF001
            self.assertEqual(h.storage.pr_sombra_descarte_count(), 1)
            self.assertTrue(h.live._sombra_abrir_slot(("OUTRO_POOL", "1h")))   # ja ocupado, sempre permite
        finally:
            h.close()

    def test_a_pool_already_tracked_in_either_dict_never_double_counts_against_the_cap(self) -> None:
        h = LiveHarness(sombra_max_pools=1)
        try:
            h.live.dets_sombra_queda96[("POOL1", "1h")] = object()
            self.assertTrue(h.live._sombra_abrir_slot(("POOL1", "1h")))
            self.assertEqual(h.storage.pr_sombra_descarte_count(), 0)
        finally:
            h.close()


class UpdateSombraTests(unittest.TestCase):
    """`_update_sombra` reusa o MESMO `simulate_v1` da V1, com os candles JA em `pr_bars` (zero chamada
    nova) -- aqui comparamos contra um sinal REAL da V1 (mesmo evento/bars) pra provar que reproduz o
    MESMO resultado, nunca um numero diferente."""

    def test_resolves_to_fechado_with_the_same_result_as_the_real_v1_trade(self) -> None:
        h = LiveHarness()
        try:
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
            for _ in range(27):
                h.clock.advance(H)
                h.tick()
            real = h.storage.pr1_signals()[0]
            self.assertEqual(real["status"], "fechado")
            now = h.clock()
            risco_pct = 100.0 * (1.0 - real["stop"] / real["entry_price"])
            sombra_row = {
                "versao": "sombra:filtrado_mc_baixo", "chain": "solana", "pool": "POOL1", "tf": "1h",
                "mint": "MINT1", "symbol": "CAT", "ts_fechamento": real["ts_fechamento"],
                "gatilho": real["gatilho"], "event_json": real["event_json"], "entry_price": real["entry_price_alerta"],
                "stop": real["stop"], "topo": real["topo"], "s_suporte": real["s_suporte"],
                "r_resistencia": real["r_resistencia"], "risco_pct": risco_pct, "queda_pct": None, "liquidez_usd": None,
                "status": "aberto", "criado_ts": now, "atualizado_ts": now,
            }
            sombra_id = h.storage.pr_sombra_insert(sombra_row)
            self.assertIsNotNone(sombra_id)
            h.live._update_sombra(now)   # noqa: SLF001
            resolvido = h.storage.pr_sombra_signals(versao="sombra:filtrado_mc_baixo")[0]
            self.assertEqual(resolvido["status"], "fechado")
            self.assertAlmostEqual(resolvido["result_net"], real["result_net"], places=9)
            self.assertAlmostEqual(resolvido["entry_price"], real["entry_price"], places=9)

            from ..analise import condicional
            comp = condicional.comparar_sombra(h.storage, "v1", "filtrado_mc_baixo", n_minimo=1)
            self.assertEqual(comp.n_com_filtro, 1)
            self.assertEqual(comp.n_sem_filtro, 1)
            r_esperado = real["result_net"] / (risco_pct / 100.0)
            self.assertAlmostEqual(comp.r_medio_com_filtro, r_esperado, places=9)
            self.assertAlmostEqual(comp.r_medio_sem_filtro, r_esperado, places=9)
            self.assertTrue(comp.amostra_suficiente)
        finally:
            h.close()


class EquivalenciaSombraTests(unittest.TestCase):
    """PEDIDO: saidas V1/V2 identicas byte a byte com o modulo de sombra ligado e desligado."""

    def test_v1_v2_signals_and_alerts_are_byte_identical_with_sombra_on_and_off(self) -> None:
        h_on = LiveHarness()
        h_off = LiveHarness(sem_sombra=True)
        try:
            start_tracking(h_on)
            h_on.run_hours(17)
            start_tracking(h_off)
            h_off.run_hours(17)
            cols_v1 = [k for k in h_on.storage.pr1_signals()[0].keys()]
            rows_on_v1 = [{k: r[k] for k in cols_v1} for r in h_on.storage.pr1_signals()]
            rows_off_v1 = [{k: r[k] for k in cols_v1} for r in h_off.storage.pr1_signals()]
            self.assertEqual(rows_on_v1, rows_off_v1)
            cols_v2 = [k for k in h_on.storage.pr2_signals()[0].keys()]
            rows_on_v2 = [{k: r[k] for k in cols_v2} for r in h_on.storage.pr2_signals()]
            rows_off_v2 = [{k: r[k] for k in cols_v2} for r in h_off.storage.pr2_signals()]
            self.assertEqual(rows_on_v2, rows_off_v2)
            self.assertEqual(sorted(_entrada_v1(h_on)), sorted(_entrada_v1(h_off)))
            self.assertEqual(h_off.storage.pr_sombra_signals(), [], "SEM_SOMBRA=1 nunca grava nenhuma linha")
        finally:
            h_on.close()
            h_off.close()

    def test_sem_sombra_env_disables_recording_even_when_a_candidate_would_qualify(self) -> None:
        h = LiveHarness(sem_sombra=True)
        try:
            h.world.add_series("POOL1", "1h", textbook().bars)
            h.list_pool()
            h.verifier = LineageVerifier(h.storage, None, clock=h.clock, verify=ok_lineage(),
                                         creation=created_at(ts=GRAD))
            h.tick()
            h.verifier.step()
            h.tick()
            h.run_hours(17)
            self.assertEqual(h.storage.pr_sombra_signals(), [])
        finally:
            h.close()


class SombraOverlappingWindowsRegressionTests(unittest.TestCase):
    """INCIDENTE DE PRODUCAO 2026-10-29 (VM, KIMCHIBULL/SHAVCOIN e outros, ~21h): o GT devolve janelas
    de candles SOBREPOSTAS -- sem `last` ancorado em NENHUM detector real (V0 desligado, V1/V2
    bloqueados por mc_baixo), `_refresh_core` recomputava `seq` do zero a cada ciclo, entregando pro
    detector sombra candles que ele JA tinha processado -> `ValueError: candles fora de ordem ou
    repetidos` direto em `det_sombra_mc.update(b)`, propagando pra fora de `_refresh_core` e pulando o
    agendamento normal (`_schedule`)/carteiras daquele ciclo. Corrigido com (a) `_sombra_feed` pulando
    qualquer candle com ts <= o ultimo ja processado por ESTE detector (idempotente) e (b) `_sombra_
    safe` isolando qualquer excecao da sombra (nunca derruba o resto do ciclo)."""

    def test_the_exact_production_scenario_never_raises_and_still_records_the_shadow_signal_once(self) -> None:
        """MESMO cenario que disparava o bug: --sem-v0 (so sobra a sombra pra ancorar `last`) + MC que
        nunca cruza o piso de `filtrado_mc_baixo` (V1 e V2 ficam bloqueados, `last` nunca avanca,
        `seq` se repete/sobrepoe a cada ciclo) -- antes da correcao, isto levantava a cada ciclo."""
        h = LiveHarness(sem_v0=True)
        try:
            h.world.add_series("POOL1", "1h", _mc_baixo_bars())
            h.list_pool()
            h.tick()
            h.verifier.step()
            h.tick()
            h.run_hours(30)   # antes da correcao: ValueError em TODO ciclo a partir daqui
            self.assertEqual(h.storage.pr1_signals(), [])
            self.assertEqual(h.storage.pr2_signals(), [])
            sombra = h.storage.pr_sombra_signals(versao="sombra:filtrado_mc_baixo")
            self.assertEqual(len(sombra), 1, "idempotente -- candles sobrepostos nunca duplicam a linha")
        finally:
            h.close()

    def test_scheduling_keeps_advancing_even_while_the_shadow_keeps_failing(self) -> None:
        """Mesmo que a sombra continue falhando (excecao forcada, nunca o caso real apos a correcao),
        `_schedule` (o agendamento OFICIAL por calor) precisa continuar rodando -- nunca mais preso no
        backoff generico de erro so por causa da sombra."""
        h = LiveHarness(sem_v0=True)
        try:
            h.world.add_series("POOL1", "1h", _mc_baixo_bars())
            h.list_pool()
            h.tick()
            h.verifier.step()
            h.tick()

            def _sempre_falha(*_a: object, **_k: object) -> None:
                raise RuntimeError("falha forcada (nunca deveria derrubar o ciclo)")

            h.live._sombra_feed = _sempre_falha  # type: ignore[method-assign]
            h.run_hours(5)
            key = ("POOL1", "1h")
            st = h.live.sched.get(key)
            self.assertIsNotNone(st)
            self.assertNotEqual(st.get("ultimo_erro"), "erro_inesperado",
                               "a excecao forcada da sombra nunca pode aparecer como erro do ciclo")
        finally:
            h.close()

    def test_sombra_feed_skips_a_candle_already_seen_idempotent_against_overlap(self) -> None:
        """Teste direto (sem rede) do mecanismo: o MESMO candle entregue 2x (janela sobreposta) nunca
        levanta e nunca processa 2x."""
        h = LiveHarness()
        try:
            start_tracking(h)
            pool_row = h.storage.pr_pool("POOL1")
            det = h.live._detector_sombra_queda96(pool_row, "1h", h.clock())
            bars_cache = [Bar(int(ts), o, hi, lo, c, v, bool(f)) for ts, o, hi, lo, c, v, f in
                         h.storage.pr_bars("POOL1", "1h")]
            self.assertTrue(bars_cache)
            ultimo = bars_cache[-1]
            # entrega o MESMO ultimo candle de novo (janela sobreposta) -- nunca pode levantar.
            h.live._sombra_feed(det, [ultimo, ultimo], pool_row, "1h", h.clock(), "queda_96_mais")
        finally:
            h.close()

    def test_sombra_safe_swallows_any_exception_and_logs_a_warning_never_raises(self) -> None:
        h = LiveHarness()
        try:
            def _explode() -> None:
                raise RuntimeError("erro inesperado qualquer")

            with self.assertLogs("signals_mvp.pos_runner.live", level="WARNING") as ctx:
                resultado = h.live._sombra_safe(_explode, contexto="teste")
            self.assertIsNone(resultado)
            self.assertTrue(any("teste" in m for m in ctx.output))
        finally:
            h.close()


class EquivalenciaComFalhaForcadaDaSombraTests(unittest.TestCase):
    """A V1/V2 precisa ficar BYTE A BYTE igual mesmo quando a sombra falha (forcado) todo ciclo --
    prova que o isolamento (`_sombra_safe`) realmente nunca influencia o caminho oficial."""

    def test_v1_v2_signals_identical_even_when_the_shadow_raises_every_cycle(self) -> None:
        h_normal = LiveHarness()
        h_falha = LiveHarness()
        try:
            start_tracking(h_normal)
            h_normal.run_hours(17)

            def _sempre_falha(*_a: object, **_k: object) -> None:
                raise RuntimeError("falha forcada (nunca deveria mudar o resultado oficial)")

            h_falha.live._sombra_feed = _sempre_falha  # type: ignore[method-assign]
            start_tracking(h_falha)
            h_falha.run_hours(17)

            cols_v1 = list(h_normal.storage.pr1_signals()[0].keys())
            rows_normal_v1 = [{k: r[k] for k in cols_v1} for r in h_normal.storage.pr1_signals()]
            rows_falha_v1 = [{k: r[k] for k in cols_v1} for r in h_falha.storage.pr1_signals()]
            self.assertEqual(rows_normal_v1, rows_falha_v1)
            cols_v2 = list(h_normal.storage.pr2_signals()[0].keys())
            rows_normal_v2 = [{k: r[k] for k in cols_v2} for r in h_normal.storage.pr2_signals()]
            rows_falha_v2 = [{k: r[k] for k in cols_v2} for r in h_falha.storage.pr2_signals()]
            self.assertEqual(rows_normal_v2, rows_falha_v2)
            self.assertEqual(h_falha.storage.pr_sombra_signals(), [],
                            "a sombra falhou sempre -- nunca grava nada, mas tambem nunca quebra a V1/V2")
        finally:
            h_normal.close()
            h_falha.close()


if __name__ == "__main__":
    unittest.main()
