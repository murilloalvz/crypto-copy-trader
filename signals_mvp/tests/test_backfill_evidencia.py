"""PEDIDO 2026-10-29, item 3: `scripts/backfill_evidencia.py` -- preenche retroativamente
pr_trajetoria/pr_baseline usando SO candles em cache (zero chamada nova), reproduzindo os MESMOS
valores que o bot ao vivo ja teria calculado; marca `pre_instrumentacao` quando o candle nao esta
mais em `pr_bars`; nunca toca pr1_signals/pr2_signals."""

from __future__ import annotations

import unittest

from ..pos_runner.candles import Bar
from ..scripts import backfill_evidencia as bf
from .test_pos_runner import textbook
from .test_pos_runner_v1_live import H
from .test_pos_runner_live import LiveHarness


def _tp1_then_stop(h: LiveHarness) -> None:
    """MESMA sequencia de `test_pos_runner_v1_live.py::EntradaTests._tp1_then_stop` (rompimento, TOPO
    com exaustao -> TP1, depois cai e toca o stop) -- SEM a cotacao SOL/USD cacheada de proposito (o
    backfill tambem nao tem, `_SOL_USD_SEMPRE_NONE`; sem isso a comparacao "mesmos valores" compararia
    um custo real com o fallback conservador de 1%, que nunca seriam iguais por desenho)."""
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


class BackfillEvidenciaTests(unittest.TestCase):
    def test_backfilling_a_wiped_trajetoria_reproduces_the_exact_same_values(self) -> None:
        h = LiveHarness()
        try:
            _tp1_then_stop(h)
            sinal = h.storage.pr1_signals()[0]
            traj_original = h.storage.pr_trajetoria_get("v1", sinal["id"])
            self.assertIsNotNone(traj_original, "o bot ao vivo precisa ter escrito a trajetoria neste cenario")
            # simula "pre-instrumentacao": como se a linha nunca tivesse sido calculada.
            h.storage._exec("DELETE FROM pr_trajetoria WHERE versao='v1' AND entry_id=?", (sinal["id"],))  # noqa: SLF001
            self.assertIsNone(h.storage.pr_trajetoria_get("v1", sinal["id"]))
            relatorio = bf.executar(h.storage.paths.db)
            # v2 compartilha o mesmo pool/candles e tambem tem uma trajetoria em aberto que
            # legitimamente e reatualizada -- o teste importa aqui e os VALORES, nao a contagem total.
            self.assertRegex(relatorio[1], r"trajetoria preenchida/atualizada: [1-9]\d*")
            traj_refeita = h.storage.pr_trajetoria_get("v1", sinal["id"])
            self.assertIsNotNone(traj_refeita)
            # "fechado" fica de fora: depende de quanto tempo real passou desde entry_ts ATE o
            # momento do calculo (`now`) -- o bot ao vivo usa o relogio simulado do teste, o backfill
            # usa o relogio real (`time.time()`), entao os dois podem legitimamente diferir aqui sem
            # que nenhum dos dois esteja errado (ver docstring de evidencia.calcular_trajetoria).
            for campo in ("preco_entrada", "risco_pct", "mfe_r", "mae_r", "ret_r_1h", "tocou_tp1"):
                self.assertEqual(traj_original[campo], traj_refeita[campo], campo)
            self.assertEqual(traj_refeita["pre_instrumentacao"], 0)
        finally:
            h.close()

    def test_backfilling_a_wiped_baseline_reproduces_the_exact_same_values(self) -> None:
        h = LiveHarness()
        try:
            _tp1_then_stop(h)
            sinal = h.storage.pr1_signals()[0]
            base_original = h.storage.pr_baseline_get("v1", sinal["id"])
            self.assertIsNotNone(base_original)
            h.storage._exec("DELETE FROM pr_baseline WHERE versao='v1' AND entry_id=?", (sinal["id"],))  # noqa: SLF001
            bf.executar(h.storage.paths.db)
            base_refeita = h.storage.pr_baseline_get("v1", sinal["id"])
            self.assertIsNotNone(base_refeita)
            # a selecao de controles roda so na 1a vez que a linha e criada, usando os bars EM CACHE
            # naquele momento -- re-rodar mais tarde pode legitimamente ver mais candles acumulados e
            # sortear um pool/conjunto diferente (nao e um bug, ver evidencia.py). O que o backfill
            # garante e uma baseline VALIDA (minimo de controles), nao os MESMOS indices.
            self.assertGreaterEqual(base_refeita["n_controles"], bf.N_CONTROLES_MINIMO)
        finally:
            h.close()

    def test_marks_pre_instrumentacao_when_no_candle_is_cached(self) -> None:
        h = LiveHarness()
        try:
            _tp1_then_stop(h)
            sinal = h.storage.pr1_signals()[0]
            h.storage._exec("DELETE FROM pr_trajetoria WHERE versao='v1' AND entry_id=?", (sinal["id"],))  # noqa: SLF001
            h.storage._exec("DELETE FROM pr_baseline WHERE versao='v1' AND entry_id=?", (sinal["id"],))  # noqa: SLF001
            h.storage._exec("DELETE FROM pr_bars WHERE pool=?", (sinal["pool"],))  # noqa: SLF001 -- "sem candle em cache"
            relatorio = bf.executar(h.storage.paths.db)
            # v1 e v2 compartilham o mesmo pool -- apagar os candles do pool afeta as ENTRADAs das 2
            # versoes, por isso >=1 (nao exatamente 1); o que importa aqui e a linha v1 especifica abaixo.
            self.assertRegex(relatorio[1], r"marcados pre_instrumentacao \(sem candle em cache\): [1-9]\d*")
            traj = h.storage.pr_trajetoria_get("v1", sinal["id"])
            base = h.storage.pr_baseline_get("v1", sinal["id"])
            self.assertEqual(traj["pre_instrumentacao"], 1)
            self.assertEqual(base["pre_instrumentacao"], 1)
            self.assertIsNone(traj["mfe_r"])
        finally:
            h.close()

    def test_never_touches_the_official_signal_rows(self) -> None:
        h = LiveHarness()
        try:
            _tp1_then_stop(h)
            antes = [dict(r) for r in h.storage.pr1_signals()] + [dict(r) for r in h.storage.pr2_signals()]
            bf.executar(h.storage.paths.db)
            depois = [dict(r) for r in h.storage.pr1_signals()] + [dict(r) for r in h.storage.pr2_signals()]
            self.assertEqual(antes, depois)
        finally:
            h.close()

    def test_backs_up_before_any_write(self) -> None:
        h = LiveHarness()
        try:
            _tp1_then_stop(h)
            relatorio = bf.executar(h.storage.paths.db)
            self.assertTrue(relatorio[0].startswith("backup: "))
            backup_path = relatorio[0].split("backup: ", 1)[1]
            from pathlib import Path
            self.assertTrue(Path(backup_path).exists())
        finally:
            h.close()

    def test_is_idempotent_running_twice_changes_nothing_further(self) -> None:
        h = LiveHarness()
        try:
            _tp1_then_stop(h)
            for _ in range(5):
                h.clock.advance(H)
                h.tick()
            bf.executar(h.storage.paths.db)
            sinal = h.storage.pr1_signals()[0]
            traj_1a = dict(h.storage.pr_trajetoria_get("v1", sinal["id"]))
            bf.executar(h.storage.paths.db)
            traj_2a = dict(h.storage.pr_trajetoria_get("v1", sinal["id"]))
            self.assertEqual({k: v for k, v in traj_1a.items() if k != "atualizado_ts"},
                             {k: v for k, v in traj_2a.items() if k != "atualizado_ts"})
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
