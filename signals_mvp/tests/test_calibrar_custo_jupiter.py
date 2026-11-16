"""RODADA 22: `scripts/calibrar_custo_jupiter.py` -- conta por perna, aborto em 429, exportacao so-leitura
(banco byte a byte igual) e ida+volta com cotacao falsa (zero rede)."""

from __future__ import annotations

import csv
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..scripts import calibrar_custo_jupiter as cj
from ..storage import Storage


class _JupFalsa:
    def __init__(self, respostas):
        self.respostas = list(respostas)

    def chamar(self, url):
        return self.respostas.pop(0)


class CalibrarCustoTests(unittest.TestCase):
    def test_custo_por_perna_e_raiz_da_ida_e_volta(self) -> None:
        self.assertAlmostEqual(cj.custo_por_perna(1 - (1 - 0.0345) ** 2), 0.0345, places=9)

    def test_ida_e_volta_com_cotacao_falsa(self) -> None:
        jup = _JupFalsa([(200, {"outAmount": "5000", "priceImpactPct": "0.01"}),
                         (200, {"outAmount": str(int(0.9 * 10 / 100 * 1e9)), "priceImpactPct": "0.02"})])
        r = cj.cotar_ida_e_volta("MINT", 10.0, 100.0, jup)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["ida_e_volta"], 0.10, places=6)

    def test_sem_rota_e_explicito(self) -> None:
        r = cj.cotar_ida_e_volta("MINT", 10.0, 100.0, _JupFalsa([(400, {"errorCode": "COULD_NOT_FIND_ANY_ROUTE"})]))
        self.assertEqual((r["status"], r["erro"]), ("sem_rota_compra", "COULD_NOT_FIND_ANY_ROUTE"))

    def test_tres_429_seguidos_abortam(self) -> None:
        ritmo = cj.Ritmo(0.0, dormir=lambda _s: None)
        with self.assertRaises(cj.Abortar):
            ritmo.chamar("https://x.invalid/q", get=lambda _u: (429, None))

    def test_exportar_amostra_nao_altera_o_banco(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            st = Storage(make_paths(tmp))
            for i in range(6):
                st._db.execute("INSERT INTO pr_pools (pool, mint, status, grad_ts, info) VALUES (?,?,?,?,?)",
                               (f"P{i}", f"M{i}", "ativo", 1_000_000 - i * 3 * 86400, '{"liq_usd": 1000}'))
            st._db.close()
            db = make_paths(tmp).db
            for sufixo in ("-wal", "-shm"):
                Path(str(db) + sufixo).unlink(missing_ok=True)
            antes = hashlib.sha256(db.read_bytes()).hexdigest()
            destino = tmp / "amostra.csv"
            cont = cj.exportar_amostra(db, destino, n=4, semente=1, agora=1_000_000)
            self.assertEqual(antes, hashlib.sha256(db.read_bytes()).hexdigest())
            linhas = list(csv.DictReader(destino.open()))
            self.assertEqual(len(linhas), sum(cont.values()))
            self.assertEqual(linhas[0]["liq_found"], "1000")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
