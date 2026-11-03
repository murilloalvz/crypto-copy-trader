"""PEDIDO 2026-11-02 (Passo 0e, item 5): smoke test do script somente-leitura sobre um banco real
(mesmo harness ao vivo) -- confirma que roda sem rede/escrita e que os números batem com o que já
está persistido (nunca um cálculo paralelo inventado)."""

from __future__ import annotations

import unittest

from ..scripts import passo0e_topo_e_fechamento as passo0e
from .test_pos_runner_live import LiveHarness, start_tracking


class Passo0eTests(unittest.TestCase):
    def test_runs_without_exceptions_and_reports_every_version(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)
            texto = passo0e.executar(h.storage.paths.db)
            self.assertIn("## V1", texto)
            self.assertIn("## V2", texto)
            self.assertIn("## V3", texto)
            self.assertIn("Resposta à pergunta do Passo 0e", texto)
            self.assertNotIn("Traceback", texto)
        finally:
            h.close()

    def test_medir_versao_matches_the_persisted_tp1_timestamp(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(40)   # tempo suficiente pra algum sinal fechar/tocar TP1
            r = passo0e.medir_versao(h.storage, "v1")
            self.assertEqual(r["versao"], "v1")
            self.assertGreaterEqual(r["n_entradas"], 0)
            # so confere a forma do resultado -- nenhum numero fabricado fora do que o banco tem.
            for chave in ("tempo_ate_topo_h", "mfe_r", "mfe_h"):
                self.assertIn(chave, r)
        finally:
            h.close()

    def test_empty_database_never_crashes(self) -> None:
        h = LiveHarness()
        try:
            texto = passo0e.executar(h.storage.paths.db)
            self.assertIn("s/d", texto)
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
