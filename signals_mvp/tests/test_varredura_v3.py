"""PEDIDO 2026-11-05 (autorizado, Parte B): testes de `scripts/varredura_v3.py` -- toque causal
(+1R/+2R/+3R antes de -1R, prioridade do stop no mesmo candle, candle corrompido nunca decide),
dedup por token, check de RAM, e smoke end-to-end (banco vazio, pool admitido real, --csv,
RAM insuficiente). EXPLORATORIO -- nunca testa "edge" (isso e H1)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.candles import Bar
from ..pos_runner.detector_v1 import EventV1
from ..storage import Storage
from ..scripts import varredura_v3 as vv3
from .test_pos_runner_v1 import CREATED, GRAD, L_BC, textbook_v1


def _bar(ts: float, o: float, h: float, l: float, c: float, v: float = 10.0) -> Bar:
    return Bar(ts=int(ts), open=o, high=h, low=l, close=c, volume=v)


def _sinal(bars: list[Bar], ev_idx: int = 0, stop: float = 90.0, topo: float = 1000.0,
          s_val: float = 50.0, token: str = "CAT", pool: str = "P1", tf: str = "1h",
          t_entrada: float | None = None, entry_price: float = 100.0,
          created_ts: float | None = None, origem: str = "universo_admitido") -> vv3.SinalVarredura:
    ev = EventV1(kind="ENTRADA", idx=ev_idx, ts=bars[ev_idx].ts, decision_ts=bars[ev_idx].ts,
                data={"stop": stop, "TOPO": topo, "S": s_val})
    risk_frac = (entry_price - stop) / entry_price
    t = t_entrada if t_entrada is not None else float(bars[ev_idx + 1].ts)
    return vv3.SinalVarredura(
        token=token, mint=token, pool=pool, tf=tf, origem=origem, bars=bars, ev=ev, dex="pumpswap",
        l_bc=L_BC, created_ts=created_ts, supply=None, t_entrada=t, entry_price=entry_price,
        entrada_corrigida=False, stop=stop, topo=topo, s_val=s_val, risk_frac=risk_frac,
        volume_gatilho=None, volume_entrada=None, volume_medio_24h=None, n_pavios=3,
    )


class RamTests(unittest.TestCase):
    def test_ram_disponivel_mb_devolve_float_ou_none(self) -> None:
        v = vv3.ram_disponivel_mb()
        self.assertTrue(v is None or isinstance(v, float))

    def test_checar_ram_ou_abortar_nunca_dispara_com_minimo_zero(self) -> None:
        vv3.checar_ram_ou_abortar(0.0)   # nao deve lancar

    def test_checar_ram_ou_abortar_dispara_com_minimo_absurdo(self) -> None:
        disponivel = vv3.ram_disponivel_mb()
        if disponivel is None:
            self.skipTest("ram_disponivel_mb indisponivel neste ambiente (nao-Linux)")
        with self.assertRaises(vv3.RamInsuficienteError):
            vv3.checar_ram_ou_abortar(10 ** 9)


class DeduplicarPorTokenTests(unittest.TestCase):
    def test_agrupa_por_token_e_remove_evento_repetido(self) -> None:
        bars = [_bar(i * 3600, 100, 105, 95, 100) for i in range(5)]
        s1 = _sinal(bars, token="CAT", pool="P1", t_entrada=3600.0)
        s2 = _sinal(bars, token="CAT", pool="P1", t_entrada=3600.0)   # mesmo (pool,tf,t_entrada) -- dup
        s3 = _sinal(bars, token="CAT", pool="P2", t_entrada=3600.0)   # pool diferente -- conta
        s4 = _sinal(bars, token="DOG", pool="P3", t_entrada=3600.0)
        por_token = vv3.deduplicar_por_token([s1, s2, s3, s4])
        self.assertEqual(set(por_token), {"CAT", "DOG"})
        self.assertEqual(len(por_token["CAT"]), 2)   # s1 e s3 (s2 e dup de s1)
        self.assertEqual(len(por_token["DOG"]), 1)


class PrimeiroToqueTests(unittest.TestCase):
    def test_toque_no_alvo_antes_do_stop(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 105, 95, 100),     # entrada, sem toque
            _bar(7200, 100, 111, 96, 105),     # toca +1R (110) antes do stop (90)
        ]
        s = _sinal(bars, ev_idx=0, stop=90.0, entry_price=100.0)
        self.assertEqual(vv3._primeiro_toque(s, 1.0), "alvo")

    def test_toque_no_stop_tem_prioridade_no_mesmo_candle(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 111, 89, 105),     # mesmo candle toca os dois -- stop ganha
        ]
        s = _sinal(bars, ev_idx=0, stop=90.0, entry_price=100.0)
        self.assertEqual(vv3._primeiro_toque(s, 1.0), "stop")

    def test_indefinido_quando_a_serie_acaba_sem_decidir(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 102, 98, 100),
        ]
        s = _sinal(bars, ev_idx=0, stop=90.0, entry_price=100.0)
        self.assertIsNone(vv3._primeiro_toque(s, 1.0))

    def test_candle_corrompido_nunca_decide(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 101, 99, 100),          # entrada limpa, sem toque
            _bar(7200, 100, 50, 10, 10, v=0.0),      # corrompido (volume 0); low<=stop, mas ignorado
            _bar(10800, 100, 111, 96, 105),          # toca o alvo de verdade
        ]
        s = _sinal(bars, ev_idx=0, stop=90.0, entry_price=100.0)
        self.assertEqual(vv3._primeiro_toque(s, 1.0), "alvo")


class ResumoToquesTests(unittest.TestCase):
    def test_compara_contra_equilibrio_e_conta_indefinidos(self) -> None:
        bars_alvo = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 105, 95, 100),
            _bar(7200, 100, 111, 96, 105),
        ]
        bars_indef = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 102, 98, 100),
        ]
        s_alvo = _sinal(bars_alvo, ev_idx=0, stop=90.0, entry_price=100.0, pool="P1")
        s_indef = _sinal(bars_indef, ev_idx=0, stop=90.0, entry_price=100.0, pool="P2")
        out = vv3.resumo_toques([s_alvo, s_indef])
        d = out[1.0]
        self.assertEqual(d["n_decididos"], 1)
        self.assertEqual(d["n_indefinido"], 1)
        self.assertEqual(d["n_alvo"], 1)
        self.assertAlmostEqual(d["p_observado_pct"], 100.0)
        self.assertAlmostEqual(d["equilibrio_pct"], 50.0)   # 100/(1+1)
        self.assertAlmostEqual(d["delta_pct"], 50.0)


class ExecutarSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="varredura_v3_"))
        storage = Storage(make_paths(self.tmp))
        self.db_path = storage.paths.db
        storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha(self) -> None:
        texto = vv3.executar(self.db_path, progresso=False)
        self.assertIn(vv3.AVISO, texto)
        self.assertNotIn("Traceback", texto)

    def test_pool_admitido_real_gera_sinais_no_relatorio(self) -> None:
        # Mesmo fixture ja usado por test_avaliar_v3_retro.py -- gera >=1 ENTRADA sob ParamsV3
        # (sem lookahead, zero historico sintetico pensado pra este teste).
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "INSERT INTO pr_pools (pool, symbol, status, l_bc, grad_ts, info) VALUES (?,?,?,?,?,?)",
            ("POOL1", "CAT", "ativo", L_BC, GRAD, json.dumps({"criado_ts": CREATED})),
        )
        bars = textbook_v1().bars
        con.executemany(
            "INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES ('POOL1','1h',?,?,?,?,?,?,?)",
            [(b.ts, b.open, b.high, b.low, b.close, b.volume, int(b.filled)) for b in bars],
        )
        con.commit()
        con.close()
        texto = vv3.executar(self.db_path, progresso=False)
        self.assertIn("## universo_admitido", texto)
        self.assertNotIn("Traceback", texto)

    def test_csv_path_grava_arquivo_quando_ha_resultado(self) -> None:
        csv_path = self.tmp / "out.csv"
        texto = vv3.executar(self.db_path, csv_path=csv_path, progresso=False)
        self.assertTrue(csv_path.exists())
        self.assertIn(str(csv_path), texto)

    def test_ram_insuficiente_levanta_e_nunca_roda(self) -> None:
        disponivel = vv3.ram_disponivel_mb()
        if disponivel is None:
            self.skipTest("ram_disponivel_mb indisponivel neste ambiente (nao-Linux)")
        with self.assertRaises(vv3.RamInsuficienteError):
            vv3.executar(self.db_path, min_ram_mb=10 ** 9)


if __name__ == "__main__":
    unittest.main()
