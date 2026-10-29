"""PEDIDO 2026-10-29, item 4: `scripts/saude.py` -- somente leitura, nunca escreve, relatorio
compacto (<=60 linhas impressas)."""

from __future__ import annotations

import json
import unittest

from ..scripts import saude
from .test_pos_runner_live import LiveHarness, start_tracking


class SaudeScriptTests(unittest.TestCase):
    def test_runs_without_exceptions_against_an_empty_database(self) -> None:
        h = LiveHarness()
        try:
            h.storage.pr_upsert_pool("POOL1", status="ativo")
            texto = saude.executar(h.storage.paths.db, None, 48.0)
            self.assertNotIn("Traceback", texto)
            self.assertLessEqual(len(texto.splitlines()), 60)
            for esperado in ("LOG (", "UPTIME:", "HASHES:", "FILA:", "CARTEIRAS:", "TRAJETORIA/BASELINE",
                            "DEXPAPRIKA:", "GT 429", "ALERTAS:", "BACKUPS:", "HEALTHCHECKS.IO:",
                            "TAGS:", "CONSISTENCIA"):
                self.assertIn(esperado, texto, texto)
        finally:
            h.close()

    def test_runs_without_exceptions_against_a_populated_database(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)   # mesmo cenario que ja produz WATCHLIST + ENTRADA (V1 e V2) nos outros testes
            texto = saude.executar(h.storage.paths.db, None, 48.0)
            self.assertNotIn("Traceback", texto)
            self.assertNotIn("secao falhou", texto)
            self.assertLessEqual(len(texto.splitlines()), 60)
            self.assertIn("POSICOES ABERTAS: V1=1 V2=1", texto)
        finally:
            h.close()

    def test_never_writes_to_the_database(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)
            antes = h.storage._all("SELECT * FROM pr1_signals")  # noqa: SLF001
            saude.executar(h.storage.paths.db, None, 48.0)
            depois = h.storage._all("SELECT * FROM pr1_signals")  # noqa: SLF001
            self.assertEqual([dict(r) for r in antes], [dict(r) for r in depois])
        finally:
            h.close()

    def test_v1_and_v2_entries_for_the_same_closed_candle_are_never_counted_as_duplicate_alerts(self) -> None:
        """PEDIDO 2026-10-29: V1 e V2 sao detectores independentes -- o MESMO (pool,tf,ts_fechamento)
        alertando nos 2 e esperado, nunca um "duplicado"."""
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)
            texto = saude.executar(h.storage.paths.db, None, 48.0)
            self.assertIn("ALERTAS: 0 (versao,pool,tf,ts_fechamento)", texto)
        finally:
            h.close()

    def test_contaminated_trades_are_counted_and_excluded_note_is_present(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)
            sinal = h.storage.pr1_signals()[0]
            h.storage.pr1_update_signal(sinal["id"], tags=json.dumps(["risco_irrealista"]))
            texto = saude.executar(h.storage.paths.db, None, 48.0)
            self.assertIn("risco_irrealista=1", texto)
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
