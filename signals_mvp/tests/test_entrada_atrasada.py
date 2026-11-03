"""PEDIDO 2026-10-30 (FASE 1a/1b, emenda EXECUCAO): guarda de atraso (_late) na ENTRADA -- nunca
alerta, nunca abre posicao, so registra o descarte; e contagem de eventos decididos antes da
admissao (`added_ts`). Sem rede."""

from __future__ import annotations

import unittest

from .test_pos_runner import H, textbook
from .test_pos_runner_live import LiveHarness, start_tracking


def _entrada_alerts(h: LiveHarness) -> list[str]:
    return [t for t in h.texts() if t.startswith("🚨 [POS_RUNNER]")]


class EntradaAtrasadaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_entrada_in_the_middle_of_a_multi_tick_catchup_never_alerts_or_opens_a_position(self) -> None:
        """Pula o lote inteiro de candles SEM tick -- quando o proximo tick finalmente roda, o MESMO
        `_refresh_core` do bot ao vivo consome todo o backlog de uma vez (`seq`), incluindo o
        rompimento no MEIO da caminhada, bem antes do ultimo candle do lote (`now` do tick). Isso
        reproduz exatamente um pool cujo catch-up (ex.: fila/429) levou varios ciclos pra alcancar
        "agora" -- a MESMA guarda `_late` que ja existia so pro alerta agora bloqueia a criacao do
        sinal/posicao tambem."""
        start_tracking(self.h)
        self.h.clock.advance(30 * H)
        self.h.tick()
        self.assertEqual(_entrada_alerts(self.h), [], self.h.texts())
        self.assertEqual(self.h.storage.pr1_signals(), [])
        self.assertEqual(self.h.storage.pr2_signals(), [])
        self.assertGreaterEqual(self.h.storage.pr_entrada_atrasada_count(0.0), 1)

    def test_entrada_on_the_current_candle_still_alerts_normally(self) -> None:
        """Mesmo cenario, so que SEM pular o lote (candle a candle, como o bot ao vivo roda o tempo
        todo) -- a ENTRADA chega "no horario", nunca atrasada; nunca descartada."""
        start_tracking(self.h)
        self.h.run_hours(17)   # candle do rompimento + folga de indexacao (mesmo cenario de EntradaTests)
        entradas = _entrada_alerts(self.h)
        self.assertEqual(len(entradas), 1, self.h.texts())
        rows = self.h.storage.pr1_signals()
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["atraso_candles"])
        self.assertLess(rows[0]["atraso_candles"], 1.0)
        self.assertEqual(self.h.storage.pr_entrada_atrasada_count(0.0), 0)

    def test_events_decided_before_admission_are_counted_as_evento_pre_admissao(self) -> None:
        """PEDIDO 2026-10-30 (FASE 1b): a ENTRADA (e qualquer WATCHLIST/ONDA_INVALIDA) decidida num
        candle anterior a `added_ts` ja era descartada silenciosamente pela guarda `tracked` -- agora
        conta em `pr_eventos_pre_admissao`, nunca na guarda de atraso (motivos diferentes)."""
        self.h.world.add_series("POOL1", "1h", textbook().bars)
        self.h.list_pool()
        self.h.tick()                 # descoberta -> pendente
        self.h.verifier.step()        # linhagem -> verificado
        # pula o relogio ANTES da promocao -- quando o pool finalmente for promovido (`added_ts` =
        # agora, bem depois do rompimento), o backfill completo (grad_ts->now) encontra o rompimento
        # NUM CANDLE ANTERIOR a `added_ts`: a guarda `tracked` descarta, nunca `_late`.
        self.h.clock.advance(30 * H)
        self.h.tick()                 # vaga -> ativo (added_ts = agora) + carga inicial do 1h
        self.assertEqual(_entrada_alerts(self.h), [], self.h.texts())
        self.assertEqual(self.h.storage.pr1_signals(), [])
        contagem = self.h.storage.pr_evento_pre_admissao_count_por_tipo(0.0)
        self.assertGreaterEqual(contagem.get("ENTRADA", 0), 1)
        # nunca tambem registrado como atraso (motivo DIFERENTE -- decision_ts < added_ts, nunca
        # "atrasado em relacao a now").
        self.assertEqual(self.h.storage.pr_entrada_atrasada_count(0.0), 0)


if __name__ == "__main__":
    unittest.main()
