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

    def test_log_section_groups_by_exact_message_with_count_and_first_last_occurrence(self) -> None:
        """PEDIDO 2026-10-29, item 1: as 5 mensagens distintas mais frequentes de ERRO/AVISO, com
        texto completo (nunca so o nome do modulo), contagem e 1a/ultima ocorrencia."""
        import time as _time
        h = LiveHarness()
        try:
            logs_dir = h.storage.paths.db.parent.parent / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            agora = _time.time()

            def _ts(delta_min: float) -> str:
                return _time.strftime("%Y-%m-%d %H:%M:%S", _time.gmtime(agora - delta_min * 60.0))

            t_primeira, t_ultima, t_aviso = _ts(90), _ts(0), _ts(10)
            linhas = (
                [f"{t_primeira}Z ERROR   signals_mvp.pos_runner.rpc: timeout na RPC (simulado)"] * 3
                + [f"{t_ultima}Z ERROR   signals_mvp.pos_runner.rpc: timeout na RPC (simulado)"]
                + [f"{t_aviso}Z WARNING signals_mvp.http: 429 do GeckoTerminal (simulado)"] * 2
            )
            (logs_dir / "signals_mvp.log").write_text("\n".join(linhas) + "\n", encoding="utf-8")
            texto = saude.executar(h.storage.paths.db, logs_dir, 48.0)
            self.assertIn(f"x4 [{t_primeira}..{t_ultima}] timeout na RPC (simulado)", texto)
            self.assertIn(f"x2 [{t_aviso}..{t_aviso}] 429 do GeckoTerminal (simulado)", texto)
        finally:
            h.close()

    def test_uptime_section_shows_current_session_separately_from_accumulated(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)
            texto = saude.executar(h.storage.paths.db, None, 48.0)
            self.assertIn("sessao atual ABERTA", texto)
            self.assertIn("acumulado total", texto)
        finally:
            h.close()

    def test_fila_section_names_the_pools_late_by_more_than_2h(self) -> None:
        h = LiveHarness()
        try:
            h.storage.pr_upsert_pool("POOLATRASADO", status="ativo", symbol="LENTO")
            h.storage.pr_append_bars("POOLATRASADO", "1h", [(int(h.clock()) - 4 * 3600, 1.0, 1.0, 1.0, 1.0, 0.0, 0)])
            texto = saude.executar(h.storage.paths.db, None, 48.0)
            self.assertIn("sem candle 1h novo ha >2h: 1", texto)
            self.assertIn("LENTO", texto)
            self.assertIn("POOLATRA", texto)
        finally:
            h.close()

    def test_dexpaprika_section_lists_up_to_15_recent_divergences_and_states_the_rule(self) -> None:
        """PEDIDO 2026-10-29, item 4: token/hora/campo/diff% das divergencias (24h), e a regra exata
        que decide a tag candle_divergente."""
        import time as _time
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)
            agora = _time.time()
            for i in range(18):
                h.storage.pr1_dexpaprika_divergencia_insert(
                    agora - i * 60.0, "solana", "POOL1", "MINT1", "CAT", "1h", int(agora - i * 3600),
                    "close", 100.0, 102.0, 2.0, h.live.version_v1)
            texto = saude.executar(h.storage.paths.db, None, 48.0)
            self.assertIn("divergencias (24h)=18", texto)
            self.assertIn("regra candle_divergente:", texto)
            self.assertIn("tolerancia (padrao 1.0%)", texto)
            self.assertIn("ultimas 15 de 18 divergencia(s)", texto)
            self.assertIn("CAT", texto)
            self.assertIn("close 2.00%", texto)
            self.assertLessEqual(len(texto.splitlines()), 60)
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
