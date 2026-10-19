"""`teste-pos-runner`: 1 alerta de ENTRADA de mentira (com mini-grafico, se der) + 1 resumo de banca de mentira
pro Telegram -- confirma a entrega da Parte B no celular do operador antes de ligar pra valer."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from .. import netcheck
from ..config import make_paths
from .fakes import FakeTelegram


class PosRunnerTelegramTestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.paths = make_paths(self.tmp)
        self.fake = FakeTelegram()
        self._real_telegram = netcheck._telegram
        netcheck._telegram = lambda paths: self.fake

    def tearDown(self):
        netcheck._telegram = self._real_telegram
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sends_a_fake_entry_alert_and_a_fake_bankroll_summary(self):
        rc = netcheck.run_pos_runner_telegram_test(self.paths)
        self.assertEqual(rc, 0)
        # o alerta de entrada sai como foto (com matplotlib) ou texto (sem ele) -- um dos dois, nunca nenhum
        entrada = [cap for _png, cap, *_ in self.fake.photos] + [t for t in self.fake.notified if "ENTRADA" in t]
        self.assertTrue(entrada, "nenhum alerta de entrada foi enviado")
        self.assertTrue(any("TESTE" in t for t in entrada))
        self.assertTrue(any("mentira" in t.lower() for t in entrada))     # nunca passa por sinal real
        resumo = [t for t in self.fake.notified if "Resumo diário" in t]
        self.assertEqual(len(resumo), 1)
        self.assertIn("mentira", resumo[0].lower())
        self.assertIn("1h/A", resumo[0])
        self.assertIn("1h/B", resumo[0])

    def test_without_telegram_env_it_fails_with_a_clear_instruction(self):
        netcheck._telegram = self._real_telegram   # sem token/chat id configurados neste tmp
        rc = netcheck.run_pos_runner_telegram_test(self.paths)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
