"""PEDIDO 2026-10-29 (auditoria+sensibilidade+sombra+radar), item 2: testes de
`scripts/sensibilidade_parametros.py` -- SOMENTE LEITURA, zero chamada de rede."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..scripts import sensibilidade_parametros as sens
from ..storage import Storage
from .test_pos_runner_v1 import CREATED, GRAD, L_BC, params, textbook_v1


class SensibilidadeParametrosTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sensibilidade_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _gravar_pool(self, pool: str, lateral: int) -> None:
        self.storage.pr_upsert_pool(pool, status="ativo", symbol=pool, mint=pool, l_bc=L_BC, grad_ts=GRAD,
                                    info=json.dumps({"criado_ts": CREATED}))
        s = textbook_v1(lateral=lateral)
        self.storage.pr_append_bars(pool, "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume, True) for b in s.bars])

    def test_pool_elegivel_blocks_dado_invalido_and_mc_baixo(self) -> None:
        bars = textbook_v1(lateral=4).bars
        base = params()
        self.assertTrue(sens._pool_elegivel(bars, base))
        # MC atual (ultimo close) do textbook fica no breakout_close=400k -- min_mc_usd bem acima bloqueia.
        acima = params(min_mc_usd=10_000_000.0)
        self.assertFalse(sens._pool_elegivel(bars, acima))

    def test_aplicar_delta_skips_an_invalid_combination(self) -> None:
        base = params(wicks_min=1, wicks_max=1)
        # wicks_min -1 => 0, violaria "wicks_min >= 1" -- __post_init__ recusa, funcao devolve None.
        self.assertIsNone(sens._aplicar_delta(base, "wicks_min", -2))

    def test_rodar_reports_zone_armed_without_entrada_for_a_too_short_box(self) -> None:
        # EXATAMENTE o caso de near-miss: lateral=3 arma a zona (WATCHLIST) mas o rompimento chega
        # 1 candle antes de zone_min_candles=12 -- nunca gera ENTRADA com os parametros padrao.
        s = textbook_v1(lateral=3)
        base = params()
        n_entradas, sem_entrada, com_entrada = sens._rodar(s.bars, base, L_BC, GRAD, CREATED)
        self.assertEqual(n_entradas, 0)
        self.assertEqual(sem_entrada, {1})
        self.assertEqual(com_entrada, set())

    def test_rodar_fires_entrada_for_the_same_zona_once_zone_min_candles_is_relaxed(self) -> None:
        s = textbook_v1(lateral=3)
        relaxado = sens._aplicar_delta(params(), "zone_min_candles", -1)
        self.assertIsNotNone(relaxado)
        n_entradas, _sem_entrada, com_entrada = sens._rodar(s.bars, relaxado, L_BC, GRAD, CREATED)
        self.assertEqual(n_entradas, 1)
        self.assertEqual(com_entrada, {1})

    def test_avaliar_sensibilidade_counts_the_near_miss_for_zone_min_candles(self) -> None:
        self._gravar_pool("POOLNEARMISS", lateral=3)
        con = sens._conectar_ro(self.storage.paths.db)
        try:
            linhas = sens.avaliar_sensibilidade(con, params())
        finally:
            con.close()
        linha = next(l for l in linhas if l["parametro"] == "zone_min_candles")
        self.assertEqual(linha["relaxado"]["delta_sinais"], 1)
        self.assertEqual(linha["relaxado"]["near_miss"], 1)

    def test_executar_produces_a_markdown_table_and_never_writes(self) -> None:
        self._gravar_pool("POOLNEARMISS", lateral=3)
        antes = self.storage._all("SELECT * FROM pr_bars")  # noqa: SLF001
        texto = sens.executar(self.storage.paths.db, "v1")
        depois = self.storage._all("SELECT * FROM pr_bars")  # noqa: SLF001
        self.assertEqual([dict(r) for r in antes], [dict(r) for r in depois])
        self.assertIn("Sensibilidade de parametros", texto)
        self.assertIn("Pools acompanhados com candles em cache: 1", texto)
        self.assertIn("zone_min_candles", texto)
        self.assertIn("atr_period", texto)

    def test_atr_period_has_no_near_miss_label_but_still_reports_delta(self) -> None:
        self._gravar_pool("POOLNEARMISS", lateral=4)   # textbook padrao: ja gera ENTRADA na base
        con = sens._conectar_ro(self.storage.paths.db)
        try:
            linhas = sens.avaliar_sensibilidade(con, params())
        finally:
            con.close()
        linha = next(l for l in linhas if l["parametro"] == "atr_period")
        self.assertIn("relaxado", linha)
        self.assertIsInstance(linha["relaxado"]["delta_sinais"], int)

    def test_age_window_rows_are_present_and_separate_from_the_uniform_list(self) -> None:
        self._gravar_pool("POOLNEARMISS", lateral=4)
        con = sens._conectar_ro(self.storage.paths.db)
        try:
            linhas = sens.avaliar_sensibilidade(con, params())
        finally:
            con.close()
        nomes = {l["parametro"] for l in linhas}
        self.assertIn("age_window_days (minimo)", nomes)
        self.assertIn("age_window_days (maximo)", nomes)


if __name__ == "__main__":
    unittest.main()
