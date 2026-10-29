"""POS-RUNNER-V1 ao vivo, integrada no MESMO PosRunnerLive do V0 (mesmos candles via pr_bars). Sem rede.

Reaproveita o harness do V0 (`test_pos_runner_live.LiveHarness`/`start_tracking`) -- a V1 roda em paralelo
sobre o MESMO cenario que o V0 ja usa, exatamente como pedido no item 0 do prompt ("V0 continua rodando em
silencio sobre os MESMOS candles")."""

from __future__ import annotations

import json
import unittest
from typing import Any

from ..http import CallBudget
from ..pos_runner.candles import Bar
from ..pos_runner.live import LineageVerifier, PosRunnerLive
from ..pos_runner.quotes import REFERENCE_POOLS, SOL_MINT
from .test_pos_runner import CREATED, GRAD, H, textbook
from .test_pos_runner_live import CTX, LINKS, LiveHarness, created_at, ok_lineage, start_tracking


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

    def _tp1_then_stop(self) -> None:
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

    def test_tp1_then_stop_closes_the_trade_and_updates_bankroll(self) -> None:
        self._tp1_then_stop()
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
        # item 1 da FASE 2 (medicao/UX): TP1 e EXIT FULL tem que ter os MESMOS botoes de
        # terminal/DexScreener do alerta de ENTRADA (nao so o feedback), pra nunca precisar rolar
        # pra cima pra achar o link.
        tp1_markup = next(markup for text, markup in self.h.tg.sent if text.startswith("🟡 [POS_RUNNER] TP1"))
        exit_markup = next(markup for text, markup in self.h.tg.sent if text.startswith("🔴 [POS_RUNNER] EXIT FULL"))
        for markup in (tp1_markup, exit_markup):
            labels = {b["text"] for row_ in markup["inline_keyboard"] for b in row_}
            self.assertIn("DexScreener", labels)
            self.assertTrue(any("Axiom" in lbl or "GMGN" in lbl for lbl in labels), labels)
            self.assertIn("👍 Bom", labels)
            urls = [b["url"] for row_ in markup["inline_keyboard"] for b in row_ if "url" in b]
            self.assertTrue(all(u.startswith("https://") for u in urls), urls)

    def test_entrada_confirmada_message_is_sent_once_with_the_real_fill_and_risk(self) -> None:
        # PATCH 2026-10-27 (diagnostico McRib): retifica o alerta ENTRADA (preco PROVISORIO) com o
        # fill/stop/risco REAIS, 1x, assim que o fill e conhecido.
        self._tp1_then_stop()
        # a LiveHarness roda V1+V2 em paralelo por padrao (ver test_pos_runner_evidencia_live.py) --
        # cada versao manda sua propria confirmacao (nunca 0).
        confirmadas = [t for t in self.h.texts() if t.startswith("✅ [POS_RUNNER] ENTRADA CONFIRMADA")]
        self.assertGreaterEqual(len(confirmadas), 1, self.h.texts())
        self.assertIn("Fill:", confirmadas[0])
        self.assertIn("Risco real:", confirmadas[0])
        self.assertNotIn("risco_irrealista", confirmadas[0])
        row = self.h.storage.pr1_signals()[0]
        self.assertNotIn("risco_irrealista", json.loads(row["tags"] or "[]"))

    def test_retomada_after_a_long_offline_gap_resumes_tracking_instead_of_perdido_offline(self) -> None:
        # PEDIDO 2026-10-27 (item 3, pos-auditoria): o pool continua `ativo` -- o restart (instancia
        # NOVA, _startup roda 1x) nao pode fechar o sinal como perdido_offline so por estar atrasado;
        # o ciclo normal de refresh (GT, com fallback DexPaprika -- ja busca de grad_ts at'e `now`
        # sempre) fecha a lacuna sozinho e retoma o acompanhamento com os precos REAIS.
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

        def _passo(live: PosRunnerLive) -> None:
            self.h.clock.advance(H)
            self.h.tick(live=live)
            live.http.arm(CallBudget(10), 1, 10)
            live.quotes.series(SOL_MINT, GRAD, self.h.clock())
            live.http.disarm()

        # avanca so o suficiente p/ a ENTRADA existir (mesmo ritmo do cenario de referencia da V1
        # ja testado em test_tp1_then_stop_closes_the_trade_and_updates_bankroll), sem resolver
        # TP1/stop ainda -- a partir daqui simula o desligamento.
        for _ in range(27):
            _passo(self.h.live)
            if self.h.storage.pr1_signals():
                break
        sinal = self.h.storage.pr1_signals()[0]
        self.assertEqual(sinal["status"], "aberto")
        # DESLIGADO: nenhum tick roda durante o salto do relogio (todo o resto do caminho -- TP1 e
        # stop -- fica represado, nunca processado pelo `self.h.live` original).
        self.h.clock.advance(10 * H)
        fresh = self.h.new_live()   # reinicio: instancia NOVA, mesmo storage -- _startup roda 1x aqui
        _passo(fresh)
        pos_restart = self.h.storage.pr1_signals()[0]
        self.assertNotEqual(pos_restart["status"], "perdido_offline",
                            "pool ainda ativo -- precisa retomar, nunca desistir so por estar atrasado")
        self.assertEqual(pos_restart["status"], "fechado", "a lacuna fecha no mesmo ciclo (GT busca ate `now`)")
        self.assertEqual(pos_restart["reason"], "stop")
        self.assertIsNotNone(pos_restart["tp1_price"])

    def test_perdido_offline_only_when_the_pool_itself_will_never_be_refreshed_again(self) -> None:
        # contraste direto com o teste anterior: pool `encerrado` (nunca mais recebe candle novo) --
        # SO AQUI os dados realmente nao existem/nao virao, perdido_offline e o fallback correto.
        self._run_to_entrada()
        sinal = self.h.storage.pr1_signals()[0]
        self.h.storage.pr_upsert_pool(sinal["pool"], status="encerrado", motivo="teste: pool encerrado")
        self.h.clock.advance(10 * H)
        fresh = self.h.new_live()
        self.h.tick(live=fresh)
        self.assertEqual(self.h.storage.pr1_signals(status="perdido_offline")[0]["id"], sinal["id"])

    def test_entrada_snapshot_crosses_top_holders_against_the_pro_list(self) -> None:
        # PEDIDO 2026-10-27 (H9, item 2): a snapshot da ENTRADA reusa a MESMA chamada de
        # adapter.holders() (nunca uma chamada RPC extra) e cruza contra o mapa de carteiras pro.
        from ..pos_runner.chain_adapter import HolderCheck
        self.h.live.adapter.holders = lambda mint, excl: HolderCheck(
            top_holders=[("ProWalletA", 5.0), ("Estranho", 1.0)])
        self.h.live._mapa_carteiras_pro = {"ProWalletA": "dani"}
        self._run_to_entrada()
        sinal = self.h.storage.pr1_signals()[0]
        self.assertEqual(sinal["carteiras_pro_presentes"], 1)
        self.assertEqual(sinal["n_pessoas_pro"], 1)
        snaps = self.h.storage.pr_carteiras_snapshot_para_sinal("v1", sinal["id"])
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["momento"], "entrada")
        self.assertEqual(snaps[0]["n_pessoas_pro"], 1)

    def test_entrada_never_fabricates_a_zero_when_holders_are_unavailable(self) -> None:
        # adapter.rpc e None por padrao no harness -- holders_indisponivel, nunca um 0 adivinhado.
        self._run_to_entrada()
        sinal = self.h.storage.pr1_signals()[0]
        self.assertIsNone(sinal["carteiras_pro_presentes"])
        self.assertIsNone(sinal["n_pessoas_pro"])
        self.assertEqual(self.h.storage.pr_carteiras_snapshot_all(), [])

    def test_sem_carteiras_disables_the_entrada_crossing_and_the_snapshot(self) -> None:
        from ..pos_runner.chain_adapter import HolderCheck
        h = LiveHarness(sem_carteiras=True)
        try:
            h.live.adapter.holders = lambda mint, excl: HolderCheck(top_holders=[("ProWalletA", 5.0)])
            h.live._mapa_carteiras_pro = {"ProWalletA": "dani"}
            start_tracking(h)
            h.run_hours(17)
            sinal = h.storage.pr1_signals()[0]
            self.assertIsNone(sinal["carteiras_pro_presentes"])
            self.assertIsNone(sinal["n_pessoas_pro"])
            self.assertEqual(h.storage.pr_carteiras_snapshot_all(), [])
        finally:
            h.close()

    def test_hourly_snapshot_only_runs_for_pools_with_an_open_position_and_respects_the_daily_budget(self) -> None:
        from ..pos_runner.chain_adapter import HolderCheck
        contagem = {"n": 0}

        def holders_fn(mint, excl):
            contagem["n"] += 1
            return HolderCheck(top_holders=[("ProWalletA", 5.0)])

        self.h.live.adapter.holders = holders_fn
        self.h.live._mapa_carteiras_pro = {"ProWalletA": "dani"}
        self.h.live.carteiras_max_chamadas_dia = 1
        self._run_to_entrada()   # a janela de 17h ja inclui horas suficientes p/ 1 snapshot horaria
        self.assertGreaterEqual(len(self.h.storage.pr_carteiras_snapshot_all()), 1)
        horarias_apos_entrada = [r for r in self.h.storage.pr_carteiras_snapshot_all() if r["momento"] == "horaria"]
        self.assertEqual(len(horarias_apos_entrada), 1, "orcamento diario = 1 -- nunca mais que 1 horaria")
        chamadas_antes = contagem["n"]
        # avanca mais horas: orcamento diario (1) ja foi gasto -- nenhuma chamada/linha horaria nova
        for _ in range(3):
            self.h.clock.advance(H)
            self.h.tick()
        horarias_depois = [r for r in self.h.storage.pr_carteiras_snapshot_all() if r["momento"] == "horaria"]
        self.assertEqual(len(horarias_depois), 1, "orcamento diario de 1 chamada horaria ja foi gasto")
        self.assertEqual(contagem["n"], chamadas_antes, "orcamento esgotado -- nenhuma chamada RPC nova")

    def test_hourly_carteiras_collection_runs_after_the_schedule_is_already_advanced(self) -> None:
        """INCIDENTE 2026-10-27 (fila de atualizacao 1h presa 30-59min depois do fechamento da hora): a
        coleta horaria de carteiras e uma chamada RPC NOVA (`adapter.holders()`) que pode ser lenta --
        rodar ela ANTES de reagendar atrasava o PROPRIO `_schedule` do (pool,tf), disparando o alerta
        operacional de fila atrasada mesmo sem nenhum pool realmente travado. Prova que o reagendamento
        normal do (pool,tf) ja aconteceu ANTES da chamada RPC de carteiras (medicao ao lado nunca atrasa
        a cadencia oficial de candles/alerta, mesmo que a RPC em si demore)."""
        from ..pos_runner.chain_adapter import HolderCheck
        self._run_to_entrada()
        pool = self.h.storage.pr1_signals()[0]["pool"]
        vistos: dict[str, Any] = {}

        def holders_fn(mint: str, excl: Any) -> HolderCheck:
            vistos["next_na_hora_da_chamada"] = self.h.live.sched.get((pool, "1h"), {}).get("next")
            return HolderCheck(top_holders=[])

        self.h.live.adapter.holders = holders_fn
        self.h.live.carteiras_max_chamadas_dia = 10
        self.h.clock.advance(H)
        self.h.tick()
        self.assertIn("next_na_hora_da_chamada", vistos, "a coleta horaria precisa ter rodado neste teste")
        self.assertIsNotNone(vistos["next_na_hora_da_chamada"])
        self.assertGreater(vistos["next_na_hora_da_chamada"], self.h.clock(),
                           "_schedule ja tinha avancado o (pool,tf) ANTES da chamada RPC de carteiras")

    def test_risco_irrealista_is_tagged_and_disclosed_never_blocks_the_signal(self) -> None:
        # PATCH 2026-10-27: risco real (fill vs stop) < 3% -- McRib: fill ~441k colado no stop 440k
        # (~0,2%). Tag/registro, NUNCA bloqueio/cancelamento silencioso do sinal.
        from ..pos_runner.simulate_v1 import TradeResultV1
        self._run_to_entrada()
        sinal = self.h.storage.pr1_signals()[0]
        row = self.h.storage.pr_pool("POOL1")
        res = TradeResultV1(status="fechado", entry_idx=0, entry_price=441_000.0, stop=440_000.0,
                            risk_frac=(441_000.0 - 440_000.0) / 441_000.0)
        self.h.live._confirmar_entrada_v1(sinal, res, row, self.h.clock())  # noqa: SLF001
        atualizado = self.h.storage.pr1_signal(sinal["id"])
        self.assertIn("risco_irrealista", json.loads(atualizado["tags"] or "[]"))
        self.assertEqual(atualizado["status"], "aberto", "nunca cancela/bloqueia por risco baixo")
        confirmadas = [t for t in self.h.texts() if t.startswith("✅ [POS_RUNNER] ENTRADA CONFIRMADA")]
        self.assertEqual(len(confirmadas), 1)
        self.assertIn("risco_irrealista", confirmadas[0])

    # -- PEDIDO ADICIONAL FASE 5: /abertos, /fechados [n], R acumulado no resumo diario -------------------
    def test_abertos_texto_lists_the_open_position_with_unrealized_r(self) -> None:
        self._run_to_entrada()
        texto = self.h.live.abertos_texto()
        self.assertIn("POSIÇÕES ABERTAS", texto)
        row = self.h.storage.pr1_signals()[0]
        self.assertIn(row["symbol"], texto)
        self.assertIn("R não realizado", texto)
        self.assertIn("desde a entrada", texto)

    def test_fechados_texto_and_daily_summary_show_realized_r_after_a_closed_trade(self) -> None:
        self._tp1_then_stop()
        row = self.h.storage.pr1_signals()[0]
        self.assertEqual(row["status"], "fechado")
        fechados = self.h.live.fechados_texto()
        self.assertIn("ÚLTIMOS 10 FECHADOS", fechados)
        self.assertIn(row["symbol"], fechados)
        self.assertIn("R realizado", fechados)
        self.assertIn("stop", fechados)
        resumo = self.h.live.daily_summary_v1()
        self.assertIn("V1:", resumo)
        self.assertIn("1/30 tokens distintos", resumo)
        # posicao ja fechada: /abertos nao pode mais listar nada pra essa versao.
        abertos = self.h.live.abertos_texto()
        self.assertIn("nenhuma posição aberta", abertos)

    def test_fechados_texto_respects_the_n_argument(self) -> None:
        self._tp1_then_stop()
        self.assertIn("ÚLTIMOS 3 FECHADOS", self.h.live.fechados_texto(3))


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
    def test_heartbeat_fires_at_startup_and_then_periodically_with_the_counters(self) -> None:
        """Revisao FASE 1.1: o 1o heartbeat sai JA no startup (nao espera a 1a janela de 6h/`heartbeat_interval_s`)."""
        h = LiveHarness()
        try:
            h.live.heartbeat_interval_s = 3 * H   # acelera o teste (padrao real: 6h)
            start_tracking(h)
            beats = [t for t in h.texts() if t.startswith("💓 POS-RUNNER-V1")]
            self.assertEqual(len(beats), 1, h.texts())   # ja sai no 1o ciclo, antes de qualquer run_hours
            self.assertIn("pools acompanhados:", beats[0])
            self.assertIn("chamadas/min", beats[0])
            self.assertIn("429 na janela:", beats[0])
            self.assertIn("fila de atualização:", beats[0])
            self.assertIn("dado_invalido:", beats[0])
            self.assertIn("l_bc_suspeito:", beats[0])
            self.assertIn("filtrado_mc_baixo:", beats[0])
            self.assertIn("filtrado_idade:", beats[0])
            self.assertIn(h.live.version_v1, beats[0])
            h.run_hours(3)
            self.assertEqual(len([t for t in h.texts() if t.startswith("💓 POS-RUNNER-V1")]), 2,
                             "o heartbeat tem que repetir a cada janela, nao so uma vez")
            h.run_hours(3)
            self.assertEqual(len([t for t in h.texts() if t.startswith("💓 POS-RUNNER-V1")]), 3)
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
            # revisao FASE 1.1: descoberta/promocao NAO sao "so do V0" -- sao a MESMA fila de pools ativos que
            # a V1 consome (item 0 do prompt); --sem-v0 nunca pode corta-las, senao mataria a V1 tambem. O
            # corte real de chamada "so do V0" e nenhum Detector do V0 ser criado.
            self.assertEqual(h.storage.pr_pool("POOL1")["status"], "ativo", "descoberta/promocao continuam rodando")
            self.assertEqual(h.live.dets, {}, "com --sem-v0 o V0 nunca cria detector (zero chamada so dele)")
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

    def test_heat_scheduling_works_from_v1_alone_when_v0_is_off(self) -> None:
        """Revisao da FASE 1: `_heat` so olhava `self.dets`/`pr_signals` (V0) -- com --sem-v0 (`self.dets`
        sempre vazio) todo pool parecia "sem carga" e perdia a prioridade de fase 2/trade aberto da V1."""
        h = LiveHarness()
        try:
            h.live = PosRunnerLive(h.settings, h.params, h.storage, h.world, CTX, h.tg, LINKS, "solana",
                                   h.paths.dados / "pos_runner", clock=h.clock, sem_v0=True)
            start_tracking(h)
            h.run_hours(12)   # entra na fase 2 (zona) antes do rompimento -- fica "quente" so na V1
            self.assertEqual(h.live.dets, {}, "com --sem-v0 o V0 nunca cria detector")
            self.assertEqual(h.live._heat("POOL1", "1h"), 0, "a V1 sozinha ja deveria marcar o pool como quente")
        finally:
            h.close()


class CicloLogTests(unittest.TestCase):
    """BUG PRIORITARIO (2026-10-22, item 4): log INFO por ciclo do V1 (fila, chamadas, 429, tempo) -- antes
    nao existia nenhuma linha de busca de candles do V1, dificultando confirmar "V1 famintо" so pelo log."""

    def test_tick_logs_an_info_line_with_fila_chamadas_429_and_tempo(self) -> None:
        h = LiveHarness()
        try:
            with self.assertLogs("signals_mvp.pos_runner.live", level="INFO") as ctx:
                start_tracking(h)
            lines = [m for m in ctx.output if "POS-RUNNER-V1: ciclo" in m]
            self.assertTrue(lines, ctx.output)
            self.assertIn("fila=", lines[0])
            self.assertIn("chamadas=", lines[0])
            self.assertIn("429=", lines[0])
            self.assertIn("tempo=", lines[0])
        finally:
            h.close()


def _start_tracking_shifted(h: LiveHarness, offset: float) -> None:
    """Mesmo cenario do textbook(), com TODOS os candles deslocados `offset` segundos -- muda a hora BRT do
    fechamento que dispara a ENTRADA sem mudar mais nada (idade desde a criacao continua igual: `created_ts`
    desloca junto)."""
    shifted = [Bar(b.ts + offset, b.open, b.high, b.low, b.close, b.volume) for b in textbook().bars]
    h.world.add_series("POOL1", "1h", shifted)
    h.list_pool(created=GRAD + offset + 60)
    h.verifier = LineageVerifier(h.storage, None, clock=h.clock, verify=ok_lineage(grad_ts=GRAD + offset + 60),
                                 creation=created_at(ts=CREATED + offset))
    h.tick()
    h.verifier.step()
    h.tick()


class JanelaDeOuroTests(unittest.TestCase):
    """Complemento FASE 1.1 (2026-10-22): a janela de ouro (item 2.3) NUNCA filtra -- o alerta sai igual fora
    dela, so com a tag/rotulo diferente. Teste explicito para nao confundir com `filtrado_idade` (que
    BLOQUEIA, ver IdadeFilterTests abaixo)."""

    def test_a_signal_outside_the_golden_window_still_alerts_with_the_fora_da_janela_tag(self) -> None:
        h = LiveHarness()
        try:
            _start_tracking_shifted(h, offset=4 * H)   # desloca a ENTRADA de 11:00 BRT (dentro) p/ 15:00 (fora)
            h.run_hours(21)
            entradas = _entrada_v1(h)
            self.assertEqual(len(entradas), 1, h.texts())   # NUNCA bloqueia: o alerta sai normal
            self.assertIn("fora da janela de ouro", entradas[0])
            row = h.storage.pr1_signals()[0]
            self.assertEqual(row["janela_ouro"], "fora_da_janela")
        finally:
            h.close()

    def test_a_signal_inside_the_golden_window_alerts_with_the_janela_ouro_tag(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)   # mesmo cenario padrao: ENTRADA cai as 11:00 BRT, dentro da janela
            entradas = _entrada_v1(h)
            self.assertEqual(len(entradas), 1, h.texts())
            self.assertIn("dentro da janela de ouro", entradas[0])
            row = h.storage.pr1_signals()[0]
            self.assertEqual(row["janela_ouro"], "janela_ouro")
        finally:
            h.close()


class IdadeFilterTests(unittest.TestCase):
    """Complemento FASE 1.1 (2026-10-22): idade fora de [2,7] dias (item 2.2 + INTERPRETACOES.md #10a) e um
    FILTRO REAL -- bloqueia o alerta e o paper (diferente da janela de ouro, que nunca bloqueia)."""

    def test_entry_outside_the_age_window_never_alerts_never_enters_paper_and_counts_filtrado_idade(self) -> None:
        h = LiveHarness()
        try:
            h.world.add_series("POOL1", "1h", textbook().bars)
            h.list_pool()
            h.verifier = LineageVerifier(h.storage, None, clock=h.clock, verify=ok_lineage(),
                                         creation=created_at(ts=GRAD))   # criado soh ~1 dia antes da entrada: < 2 dias
            h.tick()
            h.verifier.step()
            h.tick()
            h.run_hours(17)
            self.assertEqual(_entrada_v1(h), [], h.texts())        # nunca alerta
            self.assertEqual(h.storage.pr1_signals(), [])          # nunca entra no paper
            counts = h.storage.pr1_filtrado_counts(0.0)
            self.assertGreaterEqual(counts.get("filtrado_idade", 0), 1)
        finally:
            h.close()


class MedicaoUxTests(unittest.TestCase):
    """FASE 2 de medicao/UX, item 4: contador filtrado_queda_90_96 (nunca alerta) e tag base_ge_2d
    (nunca filtra) -- os dois so instrumentacao, nenhuma regra/limiar da V1 muda."""

    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_filtrado_queda_90_96_counter_without_any_alert(self) -> None:
        start_tracking(self.h)
        bars = list(textbook(start_flat=0).bars)
        bars[11] = Bar(bars[11].ts, 250_000, 255_000, 70_000, 75_000, 1_000.0)   # queda ~93% do pico (1M)
        self.h.world.add_series("POOL1", "1h", bars)
        self.h.list_pool()
        self.h.tick()
        self.h.verifier.step()
        self.h.run_hours(len(bars) + 5)
        self.assertEqual(_entrada_v1(self.h), [], self.h.texts())
        counts = self.h.storage.pr1_filtrado_counts(0.0)
        self.assertGreaterEqual(counts.get("filtrado_queda_90_96", 0), 1)

    def test_a_drop_below_90_percent_never_counts_as_filtrado_queda_90_96(self) -> None:
        self._run_to_entrada_default()
        counts = self.h.storage.pr1_filtrado_counts(0.0)
        self.assertEqual(counts.get("filtrado_queda_90_96", 0), 0)

    def _run_to_entrada_default(self) -> None:
        start_tracking(self.h)
        self.h.run_hours(17)

    def test_base_ge_2d_tag_when_the_consolidation_box_is_long_enough(self) -> None:
        start_tracking(self.h)
        s = textbook(range_len=90, start_flat=0)   # medido: box_len=50 >= 48 (ver detector_v1.py: box_len=i-anchor)
        self.h.world.add_series("POOL1", "1h", s.bars)
        self.h.list_pool()
        self.h.tick()
        self.h.verifier.step()
        self.h.run_hours(len(s.bars) + 5)
        rows = self.h.storage.pr1_signals()
        self.assertEqual(len(rows), 1, self.h.texts())
        self.assertIn("base_ge_2d", json.loads(rows[0]["tags"] or "[]"))

    def test_base_ge_2d_tag_absent_when_the_box_is_short(self) -> None:
        self._run_to_entrada_default()   # textbook() padrao: range_len=8 -> box_len=13 (< 48)
        rows = self.h.storage.pr1_signals()
        self.assertEqual(len(rows), 1, self.h.texts())
        self.assertNotIn("base_ge_2d", json.loads(rows[0]["tags"] or "[]"))


class RelatorioSemanalTests(unittest.TestCase):
    """FASE 3 (feedback no Telegram), item 3: "bons vs ruins" da semana -- por gatilho, por janela de ouro,
    por tag, e SO da versao congelada atual (nunca mistura versoes de config)."""

    def setUp(self) -> None:
        self.h = LiveHarness()
        start_tracking(self.h)
        self.h.run_hours(17)   # 1 ENTRADA real
        rows = self.h.storage.pr1_signals()
        self.assertEqual(len(rows), 1, self.h.texts())
        self.signal_id = rows[0]["id"]

    def tearDown(self) -> None:
        self.h.close()

    def test_report_counts_the_vote_and_breaks_it_down_by_gatilho_and_janela(self) -> None:
        self.h.storage.pr1_feedback_upsert(self.signal_id, "voto", "555", self.h.clock(), voto="bom")
        text = self.h.live.relatorio_semanal_v1()
        self.assertIn("RELATÓRIO SEMANAL", text)
        self.assertIn("👍 1", text)
        self.assertIn("👎 0", text)
        self.assertIn(self.h.live.version_v1, text)

    def test_report_never_mixes_feedback_from_a_discontinued_config_version(self) -> None:
        """Um voto registrado sob uma versao_config_v1 DIFERENTE (ex.: antes de um restart com parametro
        novo) nunca pode contar no relatorio da versao ATUAL -- mesma regra do daily_summary_v1."""
        self.h.storage.pr1_feedback_upsert(self.signal_id, "voto", "555", self.h.clock(), voto="bom")
        # forca a linha de feedback a carregar uma versao antiga, como se tivesse sido gravada antes de um
        # restart com config nova (o relatorio so olha pr1_feedback.versao_config_v1, nunca o da V1 atual).
        self.h.storage._exec("UPDATE pr1_feedback SET versao_config_v1=? WHERE pr1_signal_id=?",  # noqa: SLF001
                             ("versao_antiga_descontinuada", self.signal_id))
        text = self.h.live.relatorio_semanal_v1()
        self.assertIn("👍 0", text)
        self.assertIn("👎 0", text)

    def test_report_only_counts_votes_not_entrei_sai_or_nota(self) -> None:
        self.h.storage.pr1_feedback_upsert(self.signal_id, "entrei", "555", self.h.clock(), valor=0.002)
        self.h.storage.pr1_feedback_upsert(self.signal_id, "nota", "555", self.h.clock(), texto="x")
        text = self.h.live.relatorio_semanal_v1()
        self.assertIn("de 0 sinais com feedback", text)   # nenhum VOTO ainda, so entrei/nota


if __name__ == "__main__":
    unittest.main()
