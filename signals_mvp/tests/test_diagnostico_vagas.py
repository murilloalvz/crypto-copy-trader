"""PEDIDO 2026-10-30: testes de `scripts/diagnostico_vagas.py` -- SOMENTE LEITURA, zero rede."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.candles import Bar
from ..scripts import diagnostico_vagas as dv
from ..storage import Storage
from .test_pos_runner_v1 import CREATED, GRAD, H, L_BC

PICO = 1_000_000.0
TROUGH_OK = 150_000.0   # 85% de queda -- dentro de [80,90] (V1) e [80,96] (V2): PULLBACK fica ativo


def _bars_pullback_ativo(n_flat: int) -> list[Bar]:
    """Pico -> queda 85% -> N candles flat, sem recuperar nem furar drop_max: fase fica PULLBACK no
    ultimo candle (nunca sem_fase)."""
    bars = [
        Bar(GRAD, 100_000.0, 100_000.0, 95_000.0, 100_000.0, 1_000.0),
        Bar(GRAD + H, 100_000.0, PICO, 950_000.0, 950_000.0, 1_000.0),           # pico
        Bar(GRAD + 2 * H, 950_000.0, 960_000.0, TROUGH_OK, TROUGH_OK, 1_000.0),  # queda 85%
    ]
    t = GRAD + 3 * H
    for _ in range(n_flat):
        bars.append(Bar(t, 155_000.0, 158_000.0, 152_000.0, 155_000.0, 1_000.0))
        t += H
    return bars


def _bars_nunca_ativo(n: int) -> list[Bar]:
    """Nunca passa de runner_min_mc (300k) -- fase fica PHASE_NONE/sem_fase o tempo todo."""
    bars = []
    t = GRAD
    for _ in range(n):
        bars.append(Bar(t, 100_000.0, 101_000.0, 99_000.0, 100_000.0, 500.0))
        t += H
    return bars


class DiagnosticoVagasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="diagnostico_vagas_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _gravar_pool_ativo(self, pool: str, bars: list[Bar], criado_ts: float = CREATED) -> None:
        self.storage.pr_upsert_pool(pool, status="ativo", symbol=pool, mint=pool, l_bc=L_BC, grad_ts=GRAD,
                                    info=json.dumps({"criado_ts": criado_ts}))
        self.storage.pr_append_bars(pool, "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume, True) for b in bars])

    # -- A) pools ativos ------------------------------------------------------------------------

    def test_a_pool_currently_in_pullback_phase_has_zero_hours_sem_fase(self) -> None:
        self._gravar_pool_ativo("POOLATIVO", _bars_pullback_ativo(n_flat=2))
        con = dv._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            from ..pos_runner.params_v1 import load_params_v1
            from ..pos_runner.params_v2 import load_params_v2
            linhas = dv.secao_a(con, load_params_v1(), load_params_v2(), time.time())
        finally:
            con.close()
        linha = next(l for l in linhas if l["pool"] == "POOLATIVO")
        self.assertEqual(linha["horas_sem_fase"], 0.0)
        self.assertIn(linha["fase_v1"], ("pullback", "runner"))
        self.assertAlmostEqual(linha["queda_pct"], 100.0 * (1.0 - TROUGH_OK / PICO), places=3)
        self.assertEqual(linha["mc_atual"], 155_000.0)
        self.assertGreater(linha["idade_d"], 2.0)

    def test_a_pool_that_never_entered_a_wave_reports_hours_since_the_first_cached_candle(self) -> None:
        self._gravar_pool_ativo("POOLSEMFASE", _bars_nunca_ativo(n=5))
        con = dv._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            from ..pos_runner.params_v1 import load_params_v1
            from ..pos_runner.params_v2 import load_params_v2
            linhas = dv.secao_a(con, load_params_v1(), load_params_v2(), time.time())
        finally:
            con.close()
        linha = next(l for l in linhas if l["pool"] == "POOLSEMFASE")
        self.assertEqual(linha["fase_v1"], "sem_fase")
        self.assertEqual(linha["fase_v2"], "sem_fase")
        self.assertGreater(linha["horas_sem_fase"], 72.0, "GRAD e dezenas de dias no passado -- sempre > 72h")

    def test_a_pool_with_no_cached_candles_reports_missing_data_explicitly(self) -> None:
        self.storage.pr_upsert_pool("POOLVAZIO", status="ativo", symbol="POOLVAZIO", l_bc=L_BC, grad_ts=GRAD,
                                    info=json.dumps({"criado_ts": CREATED}))
        con = dv._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            from ..pos_runner.params_v1 import load_params_v1
            from ..pos_runner.params_v2 import load_params_v2
            linhas = dv.secao_a(con, load_params_v1(), load_params_v2(), time.time())
        finally:
            con.close()
        linha = next(l for l in linhas if l["pool"] == "POOLVAZIO")
        self.assertIsNone(linha["horas_sem_fase"])
        self.assertIsNone(linha["queda_pct"])
        self.assertIsNone(linha["mc_atual"])

    # -- B) candidatos sem vaga -------------------------------------------------------------------

    def test_b_candidate_passing_all_base_filters_is_counted_as_passing(self) -> None:
        now = time.time()
        self.storage.pr_upsert_pool("CANDOK", status="verificado", symbol="CANDOK",
                                    info=json.dumps({"criado_ts": now - 10 * 86400.0}))
        bars = [Bar(0, 100_000.0, PICO, 950_000.0, 950_000.0, 1.0), Bar(H, 950_000.0, 960_000.0, 148_000.0, 150_000.0, 1.0)]
        self.storage.pr_append_bars("CANDOK", "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume, True) for b in bars])
        self.storage.pr_vaga_descarte_insert(now, "CANDOK")
        con = dv._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            resultado = dv.secao_b(con, now)
        finally:
            con.close()
        self.assertEqual(resultado["n_candidatos"], 1)
        self.assertEqual(resultado["passam"], 1)
        self.assertEqual(resultado["reprovados"], 0)

    def test_b_candidate_too_young_is_rejected_with_idade_baixa_as_the_most_common_reason(self) -> None:
        now = time.time()
        self.storage.pr_upsert_pool("CANDJOVEM", status="verificado", symbol="CANDJOVEM",
                                    info=json.dumps({"criado_ts": now - 3600.0}))   # 1h de idade: <2d
        bars = [Bar(0, 100_000.0, PICO, 950_000.0, 950_000.0, 1.0), Bar(H, 950_000.0, 960_000.0, 148_000.0, 150_000.0, 1.0)]
        self.storage.pr_append_bars("CANDJOVEM", "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume, True) for b in bars])
        self.storage.pr_vaga_descarte_insert(now, "CANDJOVEM")
        con = dv._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            resultado = dv.secao_b(con, now)
        finally:
            con.close()
        self.assertEqual(resultado["passam"], 0)
        self.assertEqual(resultado["reprovados"], 1)
        self.assertEqual(resultado["motivo_mais_comum"], ("idade_baixa", 1))

    def test_b_candidate_with_no_cached_data_is_rejected_as_sem_dados(self) -> None:
        now = time.time()
        self.storage.pr_upsert_pool("CANDSEMDADO", status="verificado", symbol="CANDSEMDADO")
        self.storage.pr_vaga_descarte_insert(now, "CANDSEMDADO")
        con = dv._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            resultado = dv.secao_b(con, now)
        finally:
            con.close()
        self.assertEqual(resultado["motivo_mais_comum"], ("sem_dados", 1))

    # -- C) buckets de horas em sem_fase ------------------------------------------------------------

    def test_c_buckets_count_pools_above_each_threshold(self) -> None:
        self._gravar_pool_ativo("POOLATIVO", _bars_pullback_ativo(n_flat=2))
        self._gravar_pool_ativo("POOLSEMFASE", _bars_nunca_ativo(n=5))
        con = dv._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            from ..pos_runner.params_v1 import load_params_v1
            from ..pos_runner.params_v2 import load_params_v2
            linhas = dv.secao_a(con, load_params_v1(), load_params_v2(), time.time())
        finally:
            con.close()
        c = dv.secao_c(linhas)
        self.assertEqual(c[">24h"], 1)
        self.assertEqual(c[">48h"], 1)
        self.assertEqual(c[">72h"], 1)

    # -- script completo ---------------------------------------------------------------------------

    def test_executar_never_writes_and_includes_all_three_sections(self) -> None:
        self._gravar_pool_ativo("POOLATIVO", _bars_pullback_ativo(n_flat=2))
        now = time.time()
        self.storage.pr_upsert_pool("CANDOK", status="verificado", symbol="CANDOK",
                                    info=json.dumps({"criado_ts": now - 10 * 86400.0}))
        bars = [Bar(0, 100_000.0, PICO, 950_000.0, 950_000.0, 1.0), Bar(H, 950_000.0, 960_000.0, 148_000.0, 150_000.0, 1.0)]
        self.storage.pr_append_bars("CANDOK", "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume, True) for b in bars])
        self.storage.pr_vaga_descarte_insert(now, "CANDOK")

        antes_pools = self.storage._all("SELECT * FROM pr_pools")   # noqa: SLF001
        antes_bars = self.storage._all("SELECT * FROM pr_bars")   # noqa: SLF001
        texto = dv.executar(self.storage.paths.db)
        depois_pools = self.storage._all("SELECT * FROM pr_pools")   # noqa: SLF001
        depois_bars = self.storage._all("SELECT * FROM pr_bars")   # noqa: SLF001
        self.assertEqual([dict(r) for r in antes_pools], [dict(r) for r in depois_pools])
        self.assertEqual([dict(r) for r in antes_bars], [dict(r) for r in depois_bars])

        self.assertIn("## A) pools ativos hoje", texto)
        self.assertIn("POOLATIVO", texto)
        self.assertIn("## B) candidatos sem vaga nas ultimas 48h", texto)
        self.assertIn("candidatos: 1", texto)
        self.assertIn("## C) pools ativos sem_fase", texto)


if __name__ == "__main__":
    unittest.main()
