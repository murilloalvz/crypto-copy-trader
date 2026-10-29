"""PEDIDO ADICIONAL FASE 6, item 2: alertas operacionais no Telegram (saude do bot, nunca um sinal) --
taxa de 429 do GeckoTerminal acima de um teto por N horas, e fila de atualizacao (candles 1h) que nao
esvazia ate N min depois do fechamento da hora. 1 alerta por OCORRENCIA, sem spam."""

from __future__ import annotations

import unittest
from unittest import mock

from .test_pos_runner_live import H, LiveHarness


def _row(i: int = 0) -> dict:
    """PEDIDO 2026-10-28: `_checar_fila_atrasada` agora le `row['symbol']`/`row['pool']` pro
    diagnostico por pool pendente -- um dict minimo basta, nunca precisa de uma linha real do SQLite."""
    return {"pool": f"POOL{i}", "symbol": f"TOK{i}"}


def _due(n_1h: int = 0, n_outro: int = 0) -> list[tuple[int, float, object, str]]:
    out = [(0, 0.0, _row(i), "1h") for i in range(n_1h)]
    out += [(0, 0.0, _row(100 + i), "4h") for i in range(n_outro)]
    return out


class Alerta429Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_never_alerts_with_fewer_than_5_samples(self) -> None:
        now = self.h.clock()
        for _ in range(4):
            self.h.live._checar_alerta_429(now, True)  # noqa: SLF001
            now += 1.0
        self.assertEqual(self.h.tg.notified, [])

    def test_fires_once_when_rate_exceeds_the_default_ceiling_then_never_spams(self) -> None:
        now = self.h.clock()
        for _ in range(10):
            self.h.live._checar_alerta_429(now, True)  # noqa: SLF001 -- 100% de 429, teto padrao 30%
            now += 1.0
        self.assertEqual(len(self.h.tg.notified), 1)
        self.assertIn("429", self.h.tg.notified[0])
        for _ in range(10):   # continua ruim: nunca manda um 2o aviso
            self.h.live._checar_alerta_429(now, True)  # noqa: SLF001
            now += 1.0
        self.assertEqual(len(self.h.tg.notified), 1)

    def test_never_alerts_below_the_ceiling(self) -> None:
        now = self.h.clock()
        for _ in range(10):
            self.h.live._checar_alerta_429(now, False)  # noqa: SLF001 -- 0% de 429
            now += 1.0
        self.assertEqual(self.h.tg.notified, [])

    def test_re_alerts_after_recovering_and_degrading_again(self) -> None:
        # janela padrao de 2h (7200s): cada salto abaixo pula alem da janela, entao os pontos da fase
        # anterior saem da media movel ANTES da fase seguinte comecar -- nunca uma mistura das 2 fases.
        now = self.h.clock()
        for _ in range(10):
            self.h.live._checar_alerta_429(now, True)  # noqa: SLF001
            now += 1.0
        self.assertEqual(len(self.h.tg.notified), 1)
        now += 8000.0   # recupera: pontos antigos saem da janela, taxa cai para 0%
        for _ in range(10):
            self.h.live._checar_alerta_429(now, False)  # noqa: SLF001
            now += 1.0
        self.assertEqual(len(self.h.tg.notified), 1, "taxa normalizada: nunca manda alerta de novo")
        now += 8000.0   # degrada de novo
        for _ in range(10):
            self.h.live._checar_alerta_429(now, True)  # noqa: SLF001
            now += 1.0
        self.assertEqual(len(self.h.tg.notified), 2, "nova ocorrencia depois de normalizar: alerta de novo")

    def test_the_ceiling_and_window_are_configurable_via_env(self) -> None:
        now = self.h.clock()
        with mock.patch.dict("os.environ", {"POS_RUNNER_429_TETO_PCT": "0.9"}):
            for _ in range(10):   # 50% de 429: fica abaixo do teto de 90%
                self.h.live._checar_alerta_429(now, now % 2 == 0)  # noqa: SLF001
                now += 1.0
        self.assertEqual(self.h.tg.notified, [])


class FilaAtrasadaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def _hora_boundary(self, now: float) -> float:
        return (now // 3600) * 3600

    def test_never_alerts_before_the_delay_threshold(self) -> None:
        now = self._hora_boundary(self.h.clock()) + 10 * 60.0   # so 10 min depois do fechamento (teto padrao 30)
        self.h.live._checar_fila_atrasada(now, _due(n_1h=1))  # noqa: SLF001
        self.assertEqual(self.h.tg.notified, [])

    def test_never_alerts_when_the_1h_queue_is_empty(self) -> None:
        now = self._hora_boundary(self.h.clock()) + 45 * 60.0
        self.h.live._checar_fila_atrasada(now, _due(n_1h=0, n_outro=3))  # noqa: SLF001 -- so 4h/5m, nunca conta
        self.assertEqual(self.h.tg.notified, [])

    def test_fires_once_past_the_threshold_then_never_twice_in_the_same_hour(self) -> None:
        hora = self._hora_boundary(self.h.clock())
        now = hora + 45 * 60.0
        self.h.live._checar_fila_atrasada(now, _due(n_1h=2))  # noqa: SLF001
        self.assertEqual(len(self.h.tg.notified), 1)
        self.assertIn("fila", self.h.tg.notified[0])
        now = hora + 50 * 60.0   # ainda na MESMA hora, continua atrasada
        self.h.live._checar_fila_atrasada(now, _due(n_1h=2))  # noqa: SLF001
        self.assertEqual(len(self.h.tg.notified), 1, "nunca pode mandar 2 avisos na mesma hora")

    def test_clearing_the_queue_sends_one_resolved_message_then_allows_a_new_alert_later(self) -> None:
        """PEDIDO 2026-10-28, item 2: quando a fila esvazia de verdade depois de ter alertado, manda
        exatamente 1 mensagem "resolvido" (nunca 0, nunca mais de 1) -- e uma nova hora atrasada
        depois disso alerta de novo normalmente."""
        hora = self._hora_boundary(self.h.clock())
        self.h.live._checar_fila_atrasada(hora + 45 * 60.0, _due(n_1h=1))  # noqa: SLF001
        self.assertEqual(len(self.h.tg.notified), 1)
        self.h.live._checar_fila_atrasada(hora + 50 * 60.0, _due(n_1h=0))  # noqa: SLF001 -- esvaziou
        self.assertEqual(len(self.h.tg.notified), 2)
        self.assertIn("normalizada", self.h.tg.notified[1])
        self.h.live._checar_fila_atrasada(hora + 55 * 60.0, _due(n_1h=0))  # noqa: SLF001 -- continua vazia
        self.assertEqual(len(self.h.tg.notified), 2, "nunca manda 'resolvido' 2x pra mesma ocorrencia")
        proxima_hora = hora + H
        self.h.live._checar_fila_atrasada(proxima_hora + 45 * 60.0, _due(n_1h=1))  # noqa: SLF001 -- atrasa de novo
        self.assertEqual(len(self.h.tg.notified), 3)

    def test_never_sends_resolved_when_the_queue_empties_before_ever_alerting(self) -> None:
        hora = self._hora_boundary(self.h.clock())
        self.h.live._checar_fila_atrasada(hora + 10 * 60.0, _due(n_1h=1))  # noqa: SLF001 -- abaixo do teto, nunca alertou
        self.h.live._checar_fila_atrasada(hora + 15 * 60.0, _due(n_1h=0))  # noqa: SLF001 -- esvaziou sem alertar
        self.assertEqual(self.h.tg.notified, [])

    def test_the_delay_threshold_is_configurable_via_env(self) -> None:
        hora = self._hora_boundary(self.h.clock())
        now = hora + 20 * 60.0
        with mock.patch.dict("os.environ", {"POS_RUNNER_FILA_ATRASO_MIN": "15"}):
            self.h.live._checar_fila_atrasada(now, _due(n_1h=1))  # noqa: SLF001
        self.assertEqual(len(self.h.tg.notified), 1)

    def test_alert_includes_per_pool_diagnostics_token_phase_last_attempt_error_and_source(self) -> None:
        """PEDIDO 2026-10-28, item 2: cada aviso traz token, fase, ultima tentativa, ultimo erro e
        fonte por (pool,tf) pendente -- lido de `self.sched` (gravado por `_refresh_safe`/
        `_refresh_core`), nunca uma chamada nova."""
        hora = self._hora_boundary(self.h.clock())
        now = hora + 45 * 60.0
        self.h.live.sched[("POOL0", "1h")] = {
            "next": 0.0, "erros": 0.0, "ultimo_erro": "timeout", "ultima_tentativa": now - 600.0, "fonte": "gt",
        }
        self.h.live._checar_fila_atrasada(now, _due(n_1h=1))  # noqa: SLF001
        self.assertEqual(len(self.h.tg.notified), 1)
        texto = self.h.tg.notified[0]
        self.assertIn("TOK0", texto)
        self.assertIn("sem_fase", texto)
        self.assertIn("10min atrás", texto)
        self.assertIn("timeout", texto)
        self.assertIn("fonte: gt", texto)

    def test_only_re_alerts_at_the_60_and_120_minute_tiers_never_in_between(self) -> None:
        """PEDIDO 2026-10-28, item 2: a versao anterior re-alertava a cada oscilacao 0->=1 dentro da
        MESMA hora (sintoma real: 1 aviso a cada 1-2 min por quase 30 min). Agora, no maximo 3 avisos
        por hora -- no teto (30min padrao), em +60min e em +120min -- mesmo com `due` oscilando entre
        vazio e nao-vazio dezenas de vezes entre os tiers."""
        hora = self._hora_boundary(self.h.clock())
        for minuto in (31, 32, 34, 36, 38, 39, 41, 42, 44, 45, 47, 48, 50, 51, 53, 54, 56, 57, 59):
            self.h.live._checar_fila_atrasada(hora + minuto * 60.0, _due(n_1h=1))  # noqa: SLF001
        self.assertEqual(len(self.h.tg.notified), 1, "so 1 aviso no tier do teto, mesmo com 19 checagens")
        self.h.live._checar_fila_atrasada(hora + 91 * 60.0, _due(n_1h=1))  # noqa: SLF001 -- cruza +60min
        self.assertEqual(len(self.h.tg.notified), 2, "reaviso no tier +60min")
        self.h.live._checar_fila_atrasada(hora + 95 * 60.0, _due(n_1h=1))  # noqa: SLF001 -- ainda no tier +60
        self.assertEqual(len(self.h.tg.notified), 2, "nunca repete o mesmo tier")
        self.h.live._checar_fila_atrasada(hora + 151 * 60.0, _due(n_1h=1))  # noqa: SLF001 -- cruza +120min
        self.assertEqual(len(self.h.tg.notified), 3, "reaviso no tier +120min")
        self.h.live._checar_fila_atrasada(hora + 200 * 60.0, _due(n_1h=1))  # noqa: SLF001 -- so os 3 tiers existem
        self.assertEqual(len(self.h.tg.notified), 3, "nunca manda um 4o aviso na mesma hora")


if __name__ == "__main__":
    unittest.main()
