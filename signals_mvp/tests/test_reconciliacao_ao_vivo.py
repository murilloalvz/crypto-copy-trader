"""RODADA 23: `scripts/reconciliacao_ao_vivo.py` -- so leitura (banco byte a byte igual), stop
reproduzido com profundidade conhecida, pool morto com sensibilidade -100% e classificacao de
divergencia contra o horizonte fixo persistido."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..scripts import reconciliacao_ao_vivo as rv
from ..storage import Storage

T0 = 1_762_000_000 // 3600 * 3600
H = 3600


class ReconciliacaoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        paths = make_paths(self.tmp)
        db = Storage(paths)._db
        db.execute("INSERT INTO pr_pools (pool, mint, symbol, status, grad_ts, l_bc, motivo) VALUES "
                   "('P1','M1','AAA','ativo',?,1000,NULL), ('P2','M2','PEAK','encerrado',?,1000,'idade maxima'), "
                   "('P3','M3','RUG','encerrado',?,1000,'estagnado')", (T0 - 86400, T0 - 86400, T0 - 86400))
        ins = ("INSERT INTO pr3_signals (id, chain, pool, tf, evento, ts_fechamento, mint, symbol, dex, versao_config_v3, "
               "status, entry_price, stop, topo, s_suporte, result_net, reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
        db.execute(ins, (1, "solana", "P1", "1h", "ENTRADA", T0 + H, "M1", "AAA", "pumpswap", "x", "fechado",
                         100.0, 80.0, 300.0, 85.0, -0.27, "stop"))
        db.execute(ins, (2, "solana", "P2", "1h", "ENTRADA", T0 + H, "M2", "PEAK", "pumpswap", "x", "perdido_offline",
                         100.0, 80.0, 300.0, 85.0, None, None))
        db.execute(ins, (3, "solana", "P3", "1h", "ENTRADA", T0 + H, "M3", "RUG", "pumpswap", "x", "perdido_offline",
                         100.0, 80.0, 300.0, 85.0, None, None))
        p1 = [(T0, 98, 101, 97, 99), (T0 + H, 100, 101, 99, 100), (T0 + 2 * H, 95, 96, 70, 72)]
        p2 = [(T0, 98, 101, 97, 99), (T0 + H, 100, 101, 99, 100), (T0 + 2 * H, 100, 104, 99, 103),
              (T0 + 3 * H, 103, 105, 101, 102)]
        for pool, bars in (("P1", p1), ("P2", p2), ("P3", p2[:3])):
            for ts, o, h, l, c in bars:
                db.execute("INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES (?,'1h',?,?,?,?,?,1,0)",
                           (pool, ts, o, h, l, c))
        for k in range(3, 33):   # P3: 30h so de candle preenchido (volume 0) -> pool morto
            db.execute("INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES ('P3','1h',?,103,103,103,103,0,1)",
                       (T0 + k * H,))
        db.execute("INSERT INTO pr_baseline (versao, entry_id, chain, pool, tf, r_sinal, dif_pareada, criado_ts, "
                   "atualizado_ts) VALUES ('v3', 1, 'solana', 'P1', '1h', -1.5, -0.5, 0, 0)")
        db.execute("INSERT INTO pr_horizonte_fixo (versao, origem, entry_key, horizonte, calculado_ts, status) "
                   "VALUES ('v3','ao_vivo','2','72h',0,'pendente')")
        db.close()
        self.db = paths.db
        for sufixo in ("-wal", "-shm"):
            Path(str(self.db) + sufixo).unlink(missing_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_relatorio_somente_leitura_com_stop_e_pool_morto(self) -> None:
        antes = hashlib.sha256(self.db.read_bytes()).hexdigest()
        csv_path = self.tmp / "rec.csv"
        texto = rv.executar(self.db, now=T0 + 30 * 86400, csv_path=csv_path)
        self.assertEqual(antes, hashlib.sha256(self.db.read_bytes()).hexdigest())
        self.assertIn("### V3: 3 sinais / 3 tokens", texto)
        self.assertIn("persistido_desatualizado", texto)          # 72h persistido como pendente
        self.assertIn("nao_persistido", texto)                    # sinal 1 nunca calculado
        self.assertIn("| 2 | PEAK | s | perdido_offline | encerrado (idade maxima) |", texto)
        self.assertIn("| cens / cens |", texto)                   # PEAK: rastreio parou com pool negociando
        self.assertIn("| 3 | RUG | s | perdido_offline | encerrado (estagnado) |", texto)
        self.assertIn("-5.00 / -5.00", texto)                     # RUG morto: restante vale 0 -> -1/risco(20%)
        self.assertIn("candle reproduzido offline=1; com gap (open<stop)=0", texto)
        self.assertIn("profundidade % min=+12.50", texto)         # (80-70)/80
        self.assertTrue(csv_path.exists())
        self.assertIn("fila pendente+verificado=0/60", texto)

    def test_meio_e_low_pioram_o_r_do_stop(self) -> None:
        con = rv.conectar_ro(self.db)
        try:
            st = rv._storage_somente_leitura(con)
            stops = rv.profundidade_stops(st, con, rv.reconciliar(st, con, T0 + 30 * 86400))
        finally:
            con.close()
        s = stops[0]
        self.assertTrue(s.reproduzido)
        self.assertGreater(s.r_oficial_offline, s.r_meio)
        self.assertGreater(s.r_meio, s.r_low)


if __name__ == "__main__":
    unittest.main()
