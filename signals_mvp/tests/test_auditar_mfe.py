"""PEDIDO 2026-11-03 (continuacao -- pendente 1): testes de `scripts/auditar_mfe.py` -- prova direta
do caso relatado (MAE -72% com stop em -40%, so possivel pos-saida)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..storage import Storage
from ..scripts import auditar_mfe
from .test_pos_runner_v1 import CREATED, GRAD, L_BC, textbook_v1


def _bars(spec: list[tuple[float, float, float, float]], ts0: int = 0, step: int = 3_600) -> list[tuple]:
    return [(ts0 + i * step, o, h, l, c, 0.0, 0) for i, (o, h, l, c) in enumerate(spec)]


class AuditarMfeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="auditar_mfe_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sinal(self, pool: str, entry_price: float, stop: float, closed_ts: float) -> int:
        return self.storage.pr1_insert_signal({
            "chain": "solana", "pool": pool, "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 0,
            "mint": f"MINT_{pool}", "symbol": pool, "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]",
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
            "entry_price": entry_price, "stop": stop, "reason": "stop", "closed_ts": closed_ts,
        })

    def test_mae_profundo_so_aparece_na_janela_pos_saida_nunca_durante_a_posicao(self) -> None:
        # entrada=100, stop=60 (risco 40%). Durante a posicao (0-2h) o preco nunca passa do stop.
        # Depois que a posicao fecha (closed_ts=2h), o preco despenca pra 28 (-72%) -- EXATAMENTE o
        # caso relatado (MAE -72% < stop -40%): so pode estar na janela pos-saida.
        signal_id = self._sinal("CAT", entry_price=100.0, stop=60.0, closed_ts=7_200.0)
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="CAT", tf="1h", mint="MINT_CAT", symbol="CAT",
            t_entrada=0.0, preco_entrada=100.0, risco_pct=40.0, r_unidade=40.0, fonte_candle="gt",
        )
        bars_rows = _bars([
            (100, 110, 95, 105),    # h=0..1h: durante a posicao, MFE aqui (+10%)
            (105, 108, 90, 95),     # h=1..2h: ainda durante a posicao (closed_ts=2h)
            (95, 96, 28, 30),       # h=2..3h: JA FECHADA -- MAE -72% (28/100-1) acontece aqui
        ])
        self.storage.pr_append_bars("CAT", "1h", bars_rows)
        resultados = auditar_mfe.medir_versao(self.storage, "v1")
        self.assertEqual(len(resultados), 1)
        r = resultados[0]
        durante = r["janelas"]["durante_posicao"]
        pos_saida = r["janelas"]["pos_saida"]
        self.assertIsNotNone(durante["mae"])
        self.assertGreaterEqual(durante["mae"]["pct"], -40.0 - 1e-6)   # nunca passa do stop durante a posicao
        self.assertIsNotNone(pos_saida["mae"])
        self.assertAlmostEqual(pos_saida["mae"]["pct"], -72.0)
        self.assertLess(pos_saida["mae"]["pct"], durante["mae"]["pct"])   # o MAE profundo e SO pos-saida

    def test_risco_abaixo_de_3pct_mostra_pct_mas_nunca_r(self) -> None:
        signal_id = self._sinal("BAIXORISCO", entry_price=100.0, stop=99.9, closed_ts=3_600.0)
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="BAIXORISCO", tf="1h", mint="MINT_BAIXORISCO",
            symbol="BAIXORISCO", t_entrada=0.0, preco_entrada=100.0, risco_pct=0.1, r_unidade=0.1,
            fonte_candle="gt",
        )
        self.storage.pr_append_bars("BAIXORISCO", "1h", _bars([(100, 500, 100, 400)]))
        resultados = auditar_mfe.medir_versao(self.storage, "v1")
        mfe = resultados[0]["janelas"]["pos_entrada_72h"]["mfe"]
        self.assertIsNotNone(mfe)
        self.assertIsNone(mfe["r"])
        self.assertAlmostEqual(mfe["pct"], 400.0)

    def test_contaminado_e_risco_irrealista_ficam_fora(self) -> None:
        self._sinal_tag("CONTAM", '["contaminado_candle"]')
        self._sinal_tag("RISCOIRR", '["risco_irrealista"]')
        resultados = auditar_mfe.medir_versao(self.storage, "v1")
        self.assertEqual(resultados, [])

    def _sinal_tag(self, pool: str, tags: str) -> None:
        signal_id = self.storage.pr1_insert_signal({
            "chain": "solana", "pool": pool, "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 0,
            "mint": f"MINT_{pool}", "symbol": pool, "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": tags,
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
            "entry_price": 100.0, "stop": 80.0, "reason": "stop", "closed_ts": 3_600.0,
        })
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool=pool, tf="1h", mint=f"MINT_{pool}", symbol=pool,
            t_entrada=0.0, preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0, fonte_candle="gt",
        )
        self.storage.pr_append_bars(pool, "1h", _bars([(100, 110, 95, 105)]))

    def test_divergencia_dexpaprika_aparece_so_para_v1(self) -> None:
        signal_id = self._sinal("DIVERG", entry_price=100.0, stop=80.0, closed_ts=3_600.0)
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="DIVERG", tf="1h", mint="MINT_DIVERG", symbol="DIVERG",
            t_entrada=0.0, preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0, fonte_candle="gt",
        )
        self.storage.pr_append_bars("DIVERG", "1h", _bars([(100, 110, 95, 105)]))
        self.storage.pr1_dexpaprika_divergencia_insert(
            0.0, "solana", "DIVERG", "MINT_DIVERG", "DIVERG", "1h", 0, "high", 110.0, 95.0, 15.8, "abc123")
        resultados = auditar_mfe.medir_versao(self.storage, "v1")
        mfe = resultados[0]["janelas"]["pos_entrada_72h"]["mfe"]
        self.assertIn("high", mfe["divergencia_dexpaprika"])
        self.assertIn("GT=110", mfe["divergencia_dexpaprika"])


class ResumoTests(unittest.TestCase):
    def test_conta_lucro_antes_da_saida_mfe_r_mediano_e_r_por_token(self) -> None:
        resultados = [
            {"token": "CAT", "r_oficial": 2.0,
             "janelas": {"durante_posicao": {"mfe": {"pct": 10.0, "r": 2.0}, "mae": None}}},
            {"token": "CAT", "r_oficial": -1.0,
             "janelas": {"durante_posicao": {"mfe": {"pct": -5.0, "r": -1.0}, "mae": None}}},
            {"token": "DOG", "r_oficial": 1.0,
             "janelas": {"durante_posicao": {"mfe": {"pct": 20.0, "r": 4.0}, "mae": None}}},
        ]
        res = auditar_mfe.resumo(resultados)
        self.assertEqual(res["n_fechados"], 3)
        self.assertEqual(res["n_lucraram_antes_da_saida"], 2)   # CAT#1 (+10%) e DOG (+20%)
        self.assertAlmostEqual(res["mfe_r_mediano"], 2.0)   # mediana de (2.0, -1.0, 4.0)
        self.assertEqual(res["n_tokens_distintos"], 2)
        self.assertAlmostEqual(res["r_por_token"]["CAT"]["r_medio"], 0.5)   # media(2.0, -1.0)
        self.assertEqual(res["r_por_token"]["DOG"]["n"], 1)

    def test_sinal_sem_janela_durante_posicao_nunca_entra_no_n_fechados(self) -> None:
        resultados = [{"token": "CAT", "r_oficial": None, "janelas": {"pos_entrada_72h": {"mfe": None, "mae": None}}}]
        res = auditar_mfe.resumo(resultados)
        self.assertEqual(res["n_fechados"], 0)


class FontesBeCTests(unittest.TestCase):
    """PEDIDO 2026-11-04 (FRENTE A): fontes B (coorte retro lote1 admitida) e C (replay V3) usam o
    MESMO fixture ja validado em test_avaliar_v3_retro.py (gera >=1 ENTRADA de verdade, nunca um
    numero fixo chutado)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="auditar_mfe_bc_"))
        storage = Storage(make_paths(self.tmp))
        self.db_path = storage.paths.db
        storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _popular_pool_admitido(self, con: sqlite3.Connection, pool: str, symbol: str) -> None:
        bars = textbook_v1().bars
        added_ts = max(b.ts for b in bars) + 7_200.0   # depois de TODO o historico -- truncamento inclui tudo
        con.execute(
            "INSERT INTO pr_pools (pool, symbol, status, l_bc, grad_ts, added_ts, info) VALUES (?,?,?,?,?,?,?)",
            (pool, symbol, "ativo", L_BC, GRAD, added_ts, json.dumps({"criado_ts": CREATED})),
        )
        con.executemany(
            f"INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES ('{pool}','1h',?,?,?,?,?,?,?)",
            [(b.ts, b.open, b.high, b.low, b.close, b.volume, int(b.filled)) for b in bars],
        )

    def test_medir_v3_replay_sobre_pool_admitido_real_gera_janelas(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        self._popular_pool_admitido(con, "POOL1", "CAT")
        con.commit()
        con.close()
        storage = Storage(make_paths(self.tmp))
        try:
            linhas = auditar_mfe.medir_v3_replay(storage, self.db_path)
        finally:
            storage.close()
        self.assertGreaterEqual(len(linhas), 1)
        for l in linhas:
            self.assertEqual(l["versao"], "v3")
            self.assertEqual(l["origem"], "replay_v3")
            self.assertIn("pos_entrada_72h", l["janelas"])

    def test_medir_retro_admitido_sobre_lote1_real_gera_janelas(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "CREATE TABLE IF NOT EXISTS pr_retro_candidatos (pool TEXT PRIMARY KEY, mint TEXT, symbol TEXT, "
            "launchpad TEXT, l_bc REAL, grad_ts REAL, criado_ts REAL, mc_found REAL, lista_hash TEXT NOT NULL, "
            "congelado_em REAL NOT NULL)"
        )
        con.execute(
            "INSERT INTO pr_retro_candidatos (pool, mint, symbol, launchpad, grad_ts, criado_ts, lista_hash, "
            "congelado_em) VALUES ('POOL1', 'MINT1', 'CAT', 'pumpfun', ?, ?, 'hash123', 0.0)",
            (GRAD, CREATED),
        )
        self._popular_pool_admitido(con, "POOL1", "CAT")
        con.commit()
        con.close()
        storage = Storage(make_paths(self.tmp))
        try:
            linhas = auditar_mfe.medir_retro_admitido(storage, self.db_path)
        finally:
            storage.close()
        self.assertGreaterEqual(len(linhas), 1)
        for l in linhas:
            self.assertIn(l["versao"], ("v1", "v2"))
            self.assertEqual(l["origem"], "retro_lote1")
            self.assertIn("pos_entrada_72h", l["janelas"])


if __name__ == "__main__":
    unittest.main()
