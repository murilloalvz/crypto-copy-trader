"""PEDIDO 2026-10-29 (auditoria+sensibilidade+sombra+radar), item 4: RADAR "caixa em formacao" --
alerta de ESTUDO, NUNCA um sinal (nunca entra na banca/CSV/relatorio v1|v2, nunca convida a agir).
Sem rede."""

from __future__ import annotations

import unittest

from .test_pos_runner_live import H, LiveHarness, start_tracking


class RadarTriggerTests(unittest.TestCase):
    """O cenario PADRAO (`start_tracking`/`textbook()`) ja produz 2 WATCHLIST do Radar (zonas 1 e 2,
    box_len 9 e 4) bem antes da ENTRADA real da V1 (zone_min_candles=12) -- confirmado por construcao
    (`DetectorV1` com `self._params_radar` sobre os MESMOS candles)."""

    def test_two_radar_candidates_are_recorded_and_sent_before_the_real_v1_entrada(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(20)   # zona 2 do Radar (box_len=4) arma 1 candle depois da ENTRADA real da V1
            radar = h.storage.pr_radar_signals()
            self.assertEqual(len(radar), 2, h.texts())
            self.assertEqual({r["caixa_candles"] for r in radar}, {9, 4})
            self.assertTrue(all(r["enviado"] == 1 for r in radar))
            enviados_radar = [(t, kb) for t, kb in h.tg.sent if "RADAR" in t]
            self.assertEqual(len(enviados_radar), 2, h.texts())
            for texto, kb in enviados_radar:
                self.assertIn("NÃO É SINAL", texto)
                botoes = [b["text"] for linha in (kb or {}).get("inline_keyboard", []) for b in linha]
                self.assertIn("👀 acompanhando", botoes)
                self.assertIn("❌ ignorar", botoes)
            # nunca entra na banca/CSV oficiais
            self.assertEqual(len(h.storage.pr1_signals()), 1)   # so a ENTRADA real da V1, de sempre
        finally:
            h.close()

    def test_sem_radar_env_disables_recording_even_when_a_candidate_would_qualify(self) -> None:
        h = LiveHarness(sem_radar=True)
        try:
            start_tracking(h)
            h.run_hours(17)
            self.assertEqual(h.storage.pr_radar_signals(), [])
            self.assertEqual([t for t in h.texts() if "RADAR" in t], [])
        finally:
            h.close()

    def test_history_before_tracking_never_fires_the_radar(self) -> None:
        """Mesmo gate de `tracked`/`_late` do WATCHLIST real da V1 -- descoberto DEPOIS do
        rompimento (mesmo cenario de `test_history_before_tracking_is_not_a_paper_signal`): o
        historico inteiro chega de uma vez na carga inicial, nunca como alerta ao vivo."""
        h = LiveHarness()
        try:
            h.clock.advance(30 * H)   # descoberto depois do rompimento -- historico todo e "passado"
            start_tracking(h)
            h.run_hours(3)
            self.assertEqual(h.storage.pr_radar_signals(), [])
        finally:
            h.close()


class RadarTetoTests(unittest.TestCase):
    """RADAR_MAX_DIA: persiste TODO alerta (enviado ou nao); so os ENVIADOS contam contra o teto."""

    def test_candidates_beyond_the_daily_cap_are_persisted_but_never_sent(self) -> None:
        h = LiveHarness(radar_max_dia=1)
        try:
            start_tracking(h)
            h.run_hours(20)
            radar = h.storage.pr_radar_signals()
            self.assertEqual(len(radar), 2, h.texts())
            enviados = [r for r in radar if r["enviado"] == 1]
            nao_enviados = [r for r in radar if r["enviado"] == 0]
            self.assertEqual(len(enviados), 1, "orcamento diario = 1 -- nunca mais que 1 enviado")
            self.assertEqual(len(nao_enviados), 1, "o 2o candidato e persistido mesmo sem orcamento")
            avisos = [t for t in h.texts() if "RADAR" in t]
            self.assertEqual(len(avisos), 1)
        finally:
            h.close()


class RadarCallbackTests(unittest.TestCase):
    """Botoes 👀 acompanhando / ❌ ignorar (idempotentes -- gravam so o horario da decisao)."""

    def test_acompanhando_button_records_the_decision_once(self) -> None:
        from ..telegram import OperatorHandler

        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)
            radar_id = h.storage.pr_radar_signals()[0]["id"]
            handler = OperatorHandler(h.tg, h.storage, lambda: None, h.clock)
            handler._handle_callback({"id": "cbid1", "data": f"radar:acomp:{radar_id}",   # noqa: SLF001
                                      "message": {"message_id": 1, "chat": {"id": 42}, "reply_markup": {}}})
            row = h.storage.pr_radar_by_id(radar_id)
            self.assertEqual(row["decisao"], "acompanhando")
            self.assertIsNotNone(row["decisao_ts"])
            # clicar de novo no MESMO botao nunca duplica/reescreve
            ts_1a = row["decisao_ts"]
            handler._handle_callback({"id": "cbid2", "data": f"radar:acomp:{radar_id}",   # noqa: SLF001
                                      "message": {"message_id": 1, "chat": {"id": 42}, "reply_markup": {}}})
            row2 = h.storage.pr_radar_by_id(radar_id)
            self.assertEqual(row2["decisao_ts"], ts_1a, "clicar de novo no mesmo botao nunca reescreve")
        finally:
            h.close()

    def test_ignorar_button_records_the_opposite_decision(self) -> None:
        from ..telegram import OperatorHandler

        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)
            radar_id = h.storage.pr_radar_signals()[0]["id"]
            handler = OperatorHandler(h.tg, h.storage, lambda: None, h.clock)
            handler._handle_callback({"id": "cbid1", "data": f"radar:ignorar:{radar_id}",   # noqa: SLF001
                                      "message": {"message_id": 1, "chat": {"id": 42}, "reply_markup": {}}})
            row = h.storage.pr_radar_by_id(radar_id)
            self.assertEqual(row["decisao"], "ignorar")
        finally:
            h.close()

    def test_unknown_radar_id_answers_not_found_never_raises(self) -> None:
        from ..telegram import OperatorHandler

        h = LiveHarness()
        try:
            handler = OperatorHandler(h.tg, h.storage, lambda: None, h.clock)
            handler._handle_callback({"id": "cbid1", "data": "radar:acomp:999999",   # noqa: SLF001
                                      "message": {}})
        finally:
            h.close()


class RadarTrajetoriaTests(unittest.TestCase):
    """`_update_radar_trajetoria`: progride 'aberto' -> 'fechado' com os candles JA em `pr_bars`
    (reusa `calcular_trajetoria`, `risco_frac=1.0` -- sem stop real)."""

    def test_resolves_mfe_r_from_cached_candles_and_closes_after_72h(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(30)   # candles o bastante p/ a trajetoria do Radar ter o que medir
            radar_id = h.storage.pr_radar_signals()[0]["id"]
            h.live._update_radar_trajetoria(h.clock())   # noqa: SLF001
            row = h.storage.pr_radar_by_id(radar_id)
            self.assertIsNotNone(row["mfe_r"])
            self.assertEqual(row["status"], "aberto", "ainda nao passaram 72h reais")
            for _ in range(60):
                h.clock.advance(3600)
            h.live._update_radar_trajetoria(h.clock())   # noqa: SLF001
            row2 = h.storage.pr_radar_by_id(radar_id)
            self.assertEqual(row2["status"], "fechado")
            self.assertIsNotNone(row2["fechado_ts"])
        finally:
            h.close()


class EquivalenciaRadarTests(unittest.TestCase):
    """PEDIDO: saidas V1/V2 identicas byte a byte com o modulo de Radar ligado e desligado."""

    def test_v1_v2_signals_and_alerts_are_byte_identical_with_radar_on_and_off(self) -> None:
        h_on = LiveHarness()
        h_off = LiveHarness(sem_radar=True)
        try:
            start_tracking(h_on)
            h_on.run_hours(17)
            start_tracking(h_off)
            h_off.run_hours(17)
            # `tg_message_id` e o UNICO campo que pode legitimamente divergir: o Radar manda
            # mensagens de Telegram REAIS (a diferenca de sombra/evidencia, que nunca mandam nada no
            # cenario padrao) -- isso desloca a numeracao de id do FakeTelegram, nunca a decisao de
            # trade em si (entrada/stop/tp1/saida/resultado, todas excluidas desta lista, continuam
            # IDENTICAS). Equivalente a comparar o trade, nao o `message_id` incidental do transporte.
            cols_v1 = [k for k in h_on.storage.pr1_signals()[0].keys() if k != "tg_message_id"]
            rows_on_v1 = [{k: r[k] for k in cols_v1} for r in h_on.storage.pr1_signals()]
            rows_off_v1 = [{k: r[k] for k in cols_v1} for r in h_off.storage.pr1_signals()]
            self.assertEqual(rows_on_v1, rows_off_v1)
            cols_v2 = [k for k in h_on.storage.pr2_signals()[0].keys() if k != "tg_message_id"]
            rows_on_v2 = [{k: r[k] for k in cols_v2} for r in h_on.storage.pr2_signals()]
            rows_off_v2 = [{k: r[k] for k in cols_v2} for r in h_off.storage.pr2_signals()]
            self.assertEqual(rows_on_v2, rows_off_v2)
            self.assertEqual(h_off.storage.pr_radar_signals(), [], "SEM_RADAR=1 nunca grava nenhuma linha")
        finally:
            h_on.close()
            h_off.close()


if __name__ == "__main__":
    unittest.main()
