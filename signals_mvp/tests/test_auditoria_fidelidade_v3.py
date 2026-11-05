"""PEDIDO 2026-11-05 (autorizado, rodada 11, Parte B): testes de
`scripts/auditoria_fidelidade_v3.py` -- Clopper-Pearson (contra valores de referencia conhecidos),
toque causal por preco absoluto, B1 (topo anterior), B2 (cauda), B3 (gestao dos 70%), B4 (local da
entrada), B5 (fill_gaps), B6 (power candle), B8 (maturacao), carregamento de ao_vivo, e smoke
end-to-end. EXPLORATORIO -- nunca testa "edge" (isso e H1)."""

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
from ..scripts import auditoria_fidelidade_v3 as afv
from .test_pos_runner_v1 import CREATED, GRAD, L_BC, textbook_v1


def _bar(ts: float, o: float, h: float, l: float, c: float, v: float = 10.0, filled: bool = False) -> Bar:
    return Bar(ts=int(ts), open=o, high=h, low=l, close=c, volume=v, filled=filled)


def _sinal(bars: list[Bar], gatilho_idx: int = 0, entry_price: float = 100.0, stop: float = 90.0,
          topo: float = 1000.0, r_caixa: float | None = 500.0, s_val: float | None = 80.0,
          caixa_candles: int | None = 10, caixa_horas: float | None = 10.0, box_inicio_idx: int | None = None,
          n_testes: int | None = 2, gatilhos: tuple[str, ...] = ("reacao_suporte",), idade_dias: float | None = 3.0,
          token: str = "CAT", origem: str = "replay_v3") -> afv.SinalAuditoria:
    risk_frac = (entry_price - stop) / entry_price
    return afv.SinalAuditoria(
        token=token, origem=origem, bars=bars, gatilho_idx=gatilho_idx,
        t_entrada=float(bars[gatilho_idx + 1].ts), entry_price=entry_price, stop=stop, topo=topo,
        r_caixa=r_caixa, s_val=s_val, caixa_candles=caixa_candles, caixa_horas=caixa_horas,
        box_inicio_idx=box_inicio_idx if box_inicio_idx is not None else max(0, gatilho_idx - (caixa_candles or 0)),
        n_testes=n_testes, gatilhos=gatilhos, idade_dias=idade_dias, volume_gatilho=None,
        volume_medio_24h=None, risk_frac=risk_frac, dex="pumpswap", l_bc=L_BC,
    )


class ClopperPearsonTests(unittest.TestCase):
    def test_valores_de_referencia_conhecidos(self) -> None:
        lo, hi = afv.clopper_pearson(5, 10, 0.95)
        self.assertAlmostEqual(lo, 0.18708602844739863, places=6)
        self.assertAlmostEqual(hi, 0.8129139715526013, places=6)

    def test_zero_sucessos_limite_inferior_e_zero(self) -> None:
        lo, hi = afv.clopper_pearson(0, 10, 0.95)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.3084971078187607, places=6)

    def test_todos_sucessos_limite_superior_e_um(self) -> None:
        lo, hi = afv.clopper_pearson(10, 10, 0.95)
        self.assertAlmostEqual(lo, 0.6915028921812392, places=6)
        self.assertEqual(hi, 1.0)

    def test_n_zero_devolve_none(self) -> None:
        self.assertEqual(afv.clopper_pearson(0, 0, 0.95), (None, None))


class ToquePrecoCausalTests(unittest.TestCase):
    def test_toca_alvo_antes_do_stop(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(3600, 100, 111, 96, 105)]
        self.assertEqual(afv._toque_preco_causal(bars, 1, 90.0, 110.0), "alvo")

    def test_stop_tem_prioridade_no_mesmo_candle(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(3600, 100, 111, 89, 105)]
        self.assertEqual(afv._toque_preco_causal(bars, 1, 90.0, 110.0), "stop")

    def test_corte_de_horizonte_para_antes_de_decidir(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(3600, 100, 102, 98, 100), _bar(7200, 100, 111, 96, 105)]
        # alvo so e tocado no 3o candle (ts=7200) -- com corte em ts=3600, nunca chega la.
        self.assertIsNone(afv._toque_preco_causal(bars, 1, 90.0, 110.0, horizonte_ts=3600.0))
        self.assertEqual(afv._toque_preco_causal(bars, 1, 90.0, 110.0, horizonte_ts=7200.0), "alvo")

    def test_candle_corrompido_nunca_decide(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(3600, 100, 101, 99, 100),
               _bar(7200, 100, 50, 10, 10, v=0.0), _bar(10800, 100, 111, 96, 105)]
        self.assertEqual(afv._toque_preco_causal(bars, 1, 90.0, 110.0), "alvo")


class ResumoB1Tests(unittest.TestCase):
    def test_distancia_e_calculada_e_toque_respeita_horizonte(self) -> None:
        bars = [_bar(i * 3600, 100, 101, 99, 100) for i in range(3)]
        bars.append(_bar(3 * 3600, 100, 210, 96, 105))   # toca o topo=200 no 4o candle
        s = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0, topo=200.0)
        r = afv.resumo_b1_topo_anterior([s])
        self.assertEqual(r.n, 1)
        self.assertAlmostEqual(r.distancia_pct_media, 100.0)   # (200-100)/100
        self.assertAlmostEqual(r.distancia_r_media, 10.0)      # (200-100)/(100-90)
        self.assertEqual(r.por_horizonte["ultimo_dado_limpo"]["n_alvo"], 1)


class ResumoB2CaudaTests(unittest.TestCase):
    def test_equilibrio_e_1_sobre_1_mais_n(self) -> None:
        bars = [_bar(i * 3600, 100, 101, 99, 100) for i in range(5)]
        s = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0)
        out = afv.resumo_b2_cauda([s])
        self.assertAlmostEqual(out["72h"][2.0]["equilibrio_pct"], 100.0 / 3.0)
        self.assertAlmostEqual(out["72h"][1.0]["equilibrio_pct"], 50.0)


class ResumoB3GestaoTests(unittest.TestCase):
    def test_trailing_preserva_mais_que_breakeven_preserva_mais_que_atual(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100),          # gatilho (idx 0)
            _bar(3600, 100, 105, 95, 102),       # j0=1, entrada -- sem toque
            _bar(7200, 102, 112, 100, 110),      # sem toque ainda (+2R=120)
            _bar(10800, 110, 122, 108, 118),     # toca +2R=120 -- idx_atingiu=3
            _bar(14400, 118, 130, 112, 128),
            _bar(18000, 128, 135, 125, 132),
            _bar(21600, 132, 133, 50, 55),        # CRASH
        ]
        s = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0)
        r = afv._r_horizonte_sob_regra(s, 2.0, "atual", now=1e12)
        b = afv._r_horizonte_sob_regra(s, 2.0, "breakeven", now=1e12)
        t = afv._r_horizonte_sob_regra(s, 2.0, "trailing", now=1e12)
        self.assertAlmostEqual(r, -1.0, places=6)
        self.assertAlmostEqual(b, 0.0, places=6)
        self.assertAlmostEqual(t, 2.5, places=6)

    def test_resumo_agrega_as_3_regras_pro_mesmo_alvo(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100), _bar(3600, 100, 105, 95, 102), _bar(7200, 102, 112, 100, 110),
            _bar(10800, 110, 122, 108, 118), _bar(14400, 118, 130, 112, 128),
            _bar(18000, 128, 135, 125, 132), _bar(21600, 132, 133, 50, 55),
        ]
        s = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0)
        resumo = afv.resumo_b3_gestao([s], now=1e12)
        r2 = resumo[2.0]
        self.assertEqual(r2.n_atingiu, 1)
        self.assertAlmostEqual(r2.media_r_atual, -1.0, places=6)
        self.assertAlmostEqual(r2.media_r_breakeven, 0.0, places=6)
        self.assertAlmostEqual(r2.media_r_trailing, 2.5, places=6)

    def test_nunca_atinge_o_alvo_fica_fora_da_amostra(self) -> None:
        bars = [_bar(i * 3600, 100, 101, 99, 100) for i in range(5)]   # nunca sobe
        s = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0)
        resumo = afv.resumo_b3_gestao([s], now=1e12)
        self.assertEqual(resumo[2.0].n_atingiu, 0)


class ResumoB4Tests(unittest.TestCase):
    def test_agrupa_por_gatilho_e_marca_entrada_acima_do_topo(self) -> None:
        bars = [_bar(i * 3600, 100, 101, 99, 100) for i in range(3)]
        # entry_price=100 > r_caixa=90 -- entrou ACIMA do topo da caixa.
        s_acima = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0, r_caixa=90.0, s_val=60.0,
                         gatilhos=("rompimento_volume",))
        s_dentro = _sinal(bars, gatilho_idx=0, entry_price=70.0, stop=60.0, r_caixa=90.0, s_val=60.0,
                          gatilhos=("rompimento_volume",))
        out = afv.resumo_b4_local_entrada([s_acima, s_dentro])
        chave = "rompimento_volume"
        self.assertIn(chave, out)
        self.assertEqual(out[chave].n, 2)
        self.assertEqual(out[chave].n_acima_topo_caixa, 1)

    def test_sem_gatilho_registrado_cai_no_grupo_proprio(self) -> None:
        bars = [_bar(i * 3600, 100, 101, 99, 100) for i in range(3)]
        s = _sinal(bars, gatilho_idx=0, gatilhos=())
        out = afv.resumo_b4_local_entrada([s])
        self.assertIn("(sem_gatilho_registrado)", out)


class ResumoB5FillGapsTests(unittest.TestCase):
    def test_detecta_candle_preenchido_dentro_da_caixa(self) -> None:
        bars = [_bar(i * 3600, 100, 101, 99, 100) for i in range(5)]
        bars[2] = _bar(2 * 3600, 100, 101, 99, 100, filled=True)   # preenchido, dentro da caixa [0..3]
        s = _sinal(bars, gatilho_idx=3, box_inicio_idx=0, caixa_candles=3)
        r = afv.resumo_b5_fill_gaps([s])
        self.assertEqual(r.n_com_candle_preenchido_na_caixa, 1)
        self.assertEqual(r.tokens_afetados, ["CAT"])

    def test_sem_candle_preenchido_nunca_conta(self) -> None:
        bars = [_bar(i * 3600, 100, 101, 99, 100) for i in range(5)]
        s = _sinal(bars, gatilho_idx=3, box_inicio_idx=0, caixa_candles=3)
        r = afv.resumo_b5_fill_gaps([s])
        self.assertEqual(r.n_com_candle_preenchido_na_caixa, 0)


class CarregarAoVivoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="afv_aovivo_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_carrega_sinal_persistido_com_caixa_preservada(self) -> None:
        ts0 = 0
        signal_id = self.storage.pr3_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": ts0,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v3": "abc123", "gatilho": json.dumps(["reacao_suporte"]), "tags": "[]",
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "aberto", "entry_price": 100.0,
            "stop": 90.0, "topo": 200.0, "s_suporte": 80.0, "r_resistencia": 95.0, "n_pavios": 2,
            "caixa_candles": 5, "caixa_horas": 5.0, "idade_dias": 3.0,
        })
        self.storage.pr_trajetoria_upsert("v3", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                          mint="MINT1", symbol="CAT", t_entrada=3600.0, preco_entrada=100.0,
                                          risco_pct=10.0, r_unidade=10.0, fonte_candle="gt")
        bars = [_bar(i * 3600, 100, 101, 99, 100) for i in range(10)]
        self.storage.pr_append_bars("POOL1", "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume,
                                                     int(b.filled)) for b in bars])
        self.storage.pr_upsert_pool("POOL1", status="ativo", l_bc=L_BC)
        sinais = afv.carregar_ao_vivo(self.storage.paths.db)
        self.assertEqual(len(sinais), 1)
        s = sinais[0]
        self.assertEqual(s.origem, "ao_vivo")
        self.assertEqual(s.topo, 200.0)
        self.assertEqual(s.r_caixa, 95.0)
        self.assertEqual(s.s_val, 80.0)
        self.assertEqual(s.caixa_candles, 5)
        self.assertEqual(s.gatilhos, ("reacao_suporte",))
        self.assertEqual(s.box_inicio_idx, s.gatilho_idx - 5)


class ExecutarSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="afv_smoke_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha(self) -> None:
        texto = afv.executar(self.storage.paths.db, progresso=False)
        self.assertIn(afv.AVISO, texto)
        self.assertNotIn("Traceback", texto)

    def test_pool_admitido_real_gera_relatorio_completo(self) -> None:
        con = sqlite3.connect(str(self.storage.paths.db))
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
        texto = afv.executar(self.storage.paths.db, progresso=False)
        self.assertIn("## replay_v3", texto)
        self.assertIn("### B1", texto)
        self.assertIn("### B6", texto)
        self.assertNotIn("Traceback", texto)


if __name__ == "__main__":
    unittest.main()
