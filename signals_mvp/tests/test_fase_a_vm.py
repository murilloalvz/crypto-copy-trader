"""RODADA 22: `scripts/fase_a_vm.py` -- garante SO-LEITURA (banco byte a byte igual, escrita falha),
contagens da secao (a), casos da (b), recusa da (c) sem plano registrado e aborto da (d) no 1o 429."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..scripts import fase_a_vm as fa
from ..storage import Storage

T0 = 1_762_000_000 // 3600 * 3600


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FaseAVmTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        paths = make_paths(self.tmp)
        st = Storage(paths)
        db = st._db
        db.execute("INSERT INTO pr_pools (pool, mint, symbol, status, grad_ts, l_bc, motivo, checked_ts) VALUES "
                   "('P1','M1','AAA','ativo',?,1000,NULL,NULL), ('P2','M2','PEAK','encerrado',?,1000,'idade maxima',?)",
                   (T0 - 86400, T0 - 2 * 86400, T0 + 10 * 3600))
        ins = ("INSERT INTO pr3_signals (id, chain, pool, tf, evento, ts_fechamento, mint, symbol, versao_config_v3, "
               "status, entry_price, stop, topo, s_suporte, result_net, reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
        # stop com gap (abre abaixo do stop) e stop limpo, risco 20%
        db.execute(ins, (1, "solana", "P1", "1h", "ENTRADA", T0, "M1", "AAA", "x", "fechado", 100.0, 80.0, 300.0,
                         85.0, -0.30, "stop"))
        db.execute(ins, (2, "solana", "P1", "1h", "ENTRADA", T0 + 5 * 3600, "M1", "AAA", "x", "fechado", 100.0,
                         80.0, 300.0, 85.0, -0.226, "stop"))
        db.execute(ins, (3, "solana", "P2", "1h", "ENTRADA", T0, "M2", "PEAK", "x", "perdido_offline", 100.0,
                         80.0, 300.0, 85.0, None, None))
        for eid, t in ((1, T0 + 3600), (2, T0 + 6 * 3600), (3, T0 + 3600)):
            db.execute("INSERT INTO pr_trajetoria (versao, entry_id, chain, pool, tf, t_entrada, criado_ts, "
                       "atualizado_ts) VALUES ('v3', ?, 'solana', ?, '1h', ?, 0, 0)",
                       (eid, "P2" if eid == 3 else "P1", t))
        bars = [(T0 + 3600, 100, 101, 99, 100), (T0 + 7200, 75, 76, 70, 72),          # gap: open 75 < stop 80
                (T0 + 6 * 3600, 100, 101, 95, 99), (T0 + 7 * 3600, 99, 99, 79, 82)]   # sem gap
        for ts, o, h, l, c in bars:
            db.execute("INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES ('P1','1h',?,?,?,?,?,1,0)",
                       (ts, o, h, l, c))
        db.execute("INSERT INTO pr_baseline (versao, entry_id, chain, pool, tf, criado_ts, atualizado_ts) VALUES "
                   "('v3', 3, 'solana', 'P2', '1h', 0, 0)")
        db.execute("INSERT INTO pr_horizonte_fixo (versao, origem, entry_key, horizonte, calculado_ts, status, r_mult, "
                   "candle_marca_ts) VALUES ('v3','ao_vivo','3','72h',0,'marcado',-0.4,?)", (T0 + 9 * 3600,))
        db.execute("INSERT INTO pr_funil_marcos (pool, versao, etapa, ts) VALUES ('P1','v3','runner',0)")
        db.close()
        self.db = paths.db

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_relatorio_nao_altera_o_banco_e_conta_stops_e_casos(self) -> None:
        for sufixo in ("-wal", "-shm"):
            Path(str(self.db) + sufixo).unlink(missing_ok=True)
        antes = _sha(self.db)
        texto = fa.executar(self.db, now=T0 + 30 * 86400)
        self.assertEqual(antes, _sha(self.db))
        self.assertIn("V3: stops=2 sinais / 1 tokens distintos", texto)
        self.assertIn("R < -1,2R: 1/2", texto)
        self.assertIn("gap(open<stop)=1 sem_gap=1", texto)
        self.assertIn("V3#3 PEAK | sinal=perdido_offline | pool=encerrado (idade maxima", texto)
        self.assertIn("excluido (dif_pareada NULL", texto)
        self.assertIn("72h:marcado R=-0.40", texto)
        self.assertIn("AUSENTE do script", texto)              # P2 sem candles -> some da carteira
        self.assertIn("RECUSADO: plano nao registrado", texto)  # nunca registra o plano por conta propria
        self.assertIn("tokens (mint) distintos em QUALQUER tabela com coluna `mint`: 2", texto)
        self.assertIn("pools runner V3=1; com caixa=0; com >=1 ENTRADA=1 -> 100.0%", texto)

    def test_placar_v1_v2_usa_rodar_h1_quando_o_plano_esta_registrado(self) -> None:
        from ..analise import condicional as cond
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (cond.META_KEY_HASH, cond.hash_do_plano()))
        con.commit()
        con.close()
        texto = fa.executar(self.db, now=T0 + 30 * 86400)
        self.assertIn("- V1 [legado fechado-apenas", texto)
        self.assertIn("status=AMOSTRA_INSUFICIENTE n_tokens=0", texto)
        self.assertIn("- V2 [horizonte fixo 72h", texto)

    def test_storage_somente_leitura_recusa_escrita(self) -> None:
        con = fa.conectar_ro(self.db)
        try:
            st = fa._storage_somente_leitura(con)
            with self.assertRaises(sqlite3.OperationalError):
                st.set_meta("x", "y")
        finally:
            con.close()

    def test_piso_do_modelo_bate_com_a_tabela_do_relatorio(self) -> None:
        self.assertAlmostEqual(fa.r_stop_limpo_modelo(0.12), -1.497, places=3)
        self.assertAlmostEqual(fa.r_stop_limpo_modelo(0.33), -1.138, places=3)


class CarteirasTests(unittest.TestCase):
    def test_contagem_pre_pos_e_parada_na_janela(self) -> None:
        cong, ini = 1000, 500
        paginas = [[{"blockTime": 1200, "err": None, "signature": "a"}, {"blockTime": 1100, "err": {"x": 1}, "signature": "b"},
                    {"blockTime": 900, "err": None, "signature": "c"}, {"blockTime": 400, "err": None, "signature": "d"}]]
        res = fa.contar_carteira(lambda before: paginas.pop(0), cong, ini, max_paginas=5)
        self.assertEqual((res["pos"], res["pre"], res["completo"]), (1, 1, True))

    def test_429_aborta_a_coleta_e_preserva_checkpoint(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            lista = tmp / "lista.json"
            lista.write_text(json.dumps([{"trackedWalletAddress": "1" * 32, "name": "a1"},
                                         {"trackedWalletAddress": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                                          "name": "b"}]))
            chamadas: list[str] = []

            def rpc(url: str, endereco: str, before):
                chamadas.append(endereco)
                if len(chamadas) == 1:
                    return []
                raise fa.RateLimitAbort("HTTP 429")
            ckpt = tmp / "ckpt.json"
            out = "\n".join(fa.secao_d("https://exemplo.invalid", ckpt, now=fa.CONGELAMENTO_LISTA_TS + 86400,
                                       max_paginas=3, max_chamadas=10, lista_path=lista, chamar_rpc=rpc,
                                       dormir=lambda _s: None))
            self.assertEqual(len(chamadas), 2)
            self.assertIn("ABORTADA", out)
            self.assertEqual(len(json.loads(ckpt.read_text())["carteiras"]), 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
