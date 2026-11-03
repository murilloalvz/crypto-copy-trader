"""PEDIDO 2026-11-03 (continuacao -- pendente 1): testes de `scripts/auditar_mfe.py` -- prova direta
do caso relatado (MAE -72% com stop em -40%, so possivel pos-saida)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..storage import Storage
from ..scripts import auditar_mfe


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


if __name__ == "__main__":
    unittest.main()
