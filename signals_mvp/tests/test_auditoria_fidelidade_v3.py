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


class ResumoB3bVariantesSaidaTests(unittest.TestCase):
    """PEDIDO 2026-11-06 (rodada 11, continuacao -- item B3b): TP1 no 1o power candle ou no topo da
    caixa, breakeven, fundo estrutural/tendencia de alta."""

    @staticmethod
    def _params():
        from ..pos_runner.params_v3 import load_params_v3
        return load_params_v3()

    def test_tp1_no_power_candle_e_blend_30_70_com_breakeven(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100)]              # idx0 gatilho
        bars.append(_bar(3600, 100, 101, 99, 100))       # idx1 = j0 entrada
        for i in range(2, 22):
            bars.append(_bar(i * 3600, 100, 101, 99, 100))   # idx2..21, flat (ATR baixo)
        bars.append(_bar(22 * 3600, 100, 140, 98, 135))      # idx22: power candle -- dispara TP1
        bars.append(_bar(23 * 3600, 135, 136, 134, 135))     # idx23: leg1 sai no open=135
        bars.append(_bar(24 * 3600, 135, 136, 90, 92))       # idx24: low=90 <= breakeven(100) -- sai
        s = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0, r_caixa=500.0)
        r = afv._r_b3b_variante(s, 72.0 * 3600.0, now=1e12, params=self._params())
        # r_leg1=(135-100)/10=3.5 (30%) ; r_leg2=(100-100)/10=0.0 (70%, breakeven) -> 0.3*3.5+0.7*0=1.05
        self.assertAlmostEqual(r, 1.05, places=6)

    def test_nunca_dispara_tp1_fica_fora_da_amostra(self) -> None:
        bars = [_bar(i * 3600, 100, 101, 99, 100) for i in range(25)]   # nunca sobe, nunca e power
        s = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0, r_caixa=500.0)
        r = afv._r_b3b_variante(s, 72.0 * 3600.0, now=1e12, params=self._params())
        self.assertIsNone(r)

    def test_toca_o_topo_da_caixa_tambem_dispara_tp1(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(3600, 100, 101, 99, 100)]
        bars.append(_bar(7200, 100, 120, 99, 110))   # toca r_caixa=110 -- dispara TP1 mesmo sem power
        bars.append(_bar(10800, 110, 111, 109, 110))   # leg1 sai no open=110
        bars.append(_bar(14400, 110, 111, 50, 55))     # crash -- toca breakeven(100)
        s = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0, r_caixa=110.0)
        r = afv._r_b3b_variante(s, 72.0 * 3600.0, now=1e12, params=self._params())
        self.assertIsNotNone(r)

    def test_resumo_agrega_fracao_tp1_e_pareamento_por_horizonte(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100)]
        bars.append(_bar(3600, 100, 101, 99, 100))
        for i in range(2, 22):
            bars.append(_bar(i * 3600, 100, 101, 99, 100))
        bars.append(_bar(22 * 3600, 100, 140, 98, 135))
        bars.append(_bar(23 * 3600, 135, 136, 134, 135))
        bars.append(_bar(24 * 3600, 135, 136, 90, 92))
        s = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0, r_caixa=500.0)
        resumo = afv.resumo_b3b_variantes_saida([s], now=1e12, params=self._params())
        self.assertIn("72h", resumo)
        self.assertIn("7d", resumo)
        self.assertEqual(resumo["72h"].n_sinais, 1)
        self.assertEqual(resumo["72h"].n_tp1_realizado, 1)
        self.assertAlmostEqual(resumo["72h"].frac_tp1_pct, 100.0)
        self.assertEqual(resumo["72h"].pareamento.n, 1)


class ResumoB3bVariantesTodosTests(unittest.TestCase):
    """PEDIDO 2026-11-06 (rodada 12, Parte 4a): `_r_b3b_variante_todos`/`resumo_b3b_variantes_saida.
    pareamento_todos` -- nunca descarta quem bate o stop antes do TP1 ou quem nunca dispara TP1
    dentro do corte do horizonte (o calculo condicionado em `_r_b3b_variante` fica intocado)."""

    @staticmethod
    def _params():
        from ..pos_runner.params_v3 import load_params_v3
        return load_params_v3()

    def test_stop_batido_antes_do_tp1_conta_como_resolvido_sem_tp1(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(3600, 100, 102, 96, 101)]   # idx1=j0, entry=100
        bars.append(_bar(7200, 101, 102, 70, 75))   # low=70 <= stop(90) -- fecha aqui, nunca viu TP1
        s = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0, r_caixa=500.0)
        r = afv._r_b3b_variante_todos(s, 72.0 * 3600.0, now=1e12, params=self._params())
        self.assertEqual(r.status, "resolvido")
        self.assertFalse(r.tp1_realizado)
        self.assertIsNotNone(r.r_mult)
        self.assertLess(r.r_mult, 0.0)
        # o calculo CONDICIONADO (intocado) continua devolvendo None pra este mesmo sinal.
        self.assertIsNone(afv._r_b3b_variante(s, 72.0 * 3600.0, now=1e12, params=self._params()))

    def test_tp1_realizado_bate_com_o_calculo_condicionado(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100)]
        bars.append(_bar(3600, 100, 101, 99, 100))
        for i in range(2, 22):
            bars.append(_bar(i * 3600, 100, 101, 99, 100))
        bars.append(_bar(22 * 3600, 100, 140, 98, 135))
        bars.append(_bar(23 * 3600, 135, 136, 134, 135))
        bars.append(_bar(24 * 3600, 135, 136, 90, 92))
        s = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0, r_caixa=500.0)
        r_condicional = afv._r_b3b_variante(s, 72.0 * 3600.0, now=1e12, params=self._params())
        r_todos = afv._r_b3b_variante_todos(s, 72.0 * 3600.0, now=1e12, params=self._params())
        self.assertEqual(r_todos.status, "resolvido")
        self.assertTrue(r_todos.tp1_realizado)
        self.assertAlmostEqual(r_todos.r_mult, r_condicional, places=6)

    def test_nunca_dispara_tp1_mas_horizonte_vencido_marca_a_mercado(self) -> None:
        bars = [_bar(i * 3600, 100, 101, 99, 100) for i in range(5)]   # nunca sobe, nunca e power
        s = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0, r_caixa=500.0)
        ts_corte = s.t_entrada + 72.0 * 3600.0
        r = afv._r_b3b_variante_todos(s, 72.0 * 3600.0, now=ts_corte + 1.0, params=self._params())
        self.assertEqual(r.status, "marcado")
        self.assertFalse(r.tp1_realizado)
        self.assertIsNotNone(r.r_mult)
        # o calculo CONDICIONADO (intocado) continua fora da amostra pra este mesmo sinal.
        self.assertIsNone(afv._r_b3b_variante(s, 72.0 * 3600.0, now=ts_corte + 1.0, params=self._params()))

    def test_horizonte_nao_decorrido_fica_pendente(self) -> None:
        bars = [_bar(i * 3600, 100, 101, 99, 100) for i in range(5)]
        s = _sinal(bars, gatilho_idx=0, entry_price=100.0, stop=90.0, r_caixa=500.0)
        r = afv._r_b3b_variante_todos(s, 72.0 * 3600.0, now=s.t_entrada + 1.0, params=self._params())
        self.assertEqual(r.status, "pendente")

    def test_resumo_agrega_condicional_e_todos_separadamente(self) -> None:
        bars_stop = [_bar(0, 100, 101, 99, 100), _bar(3600, 100, 102, 96, 101),
                    _bar(7200, 101, 102, 70, 75)]
        s_stop = _sinal(bars_stop, gatilho_idx=0, entry_price=100.0, stop=90.0, r_caixa=500.0,
                        token="DOG")
        bars_tp1 = [_bar(0, 100, 101, 99, 100), _bar(3600, 100, 101, 99, 100)]
        for i in range(2, 22):
            bars_tp1.append(_bar(i * 3600, 100, 101, 99, 100))
        bars_tp1.append(_bar(22 * 3600, 100, 140, 98, 135))
        bars_tp1.append(_bar(23 * 3600, 135, 136, 134, 135))
        bars_tp1.append(_bar(24 * 3600, 135, 136, 90, 92))
        s_tp1 = _sinal(bars_tp1, gatilho_idx=0, entry_price=100.0, stop=90.0, r_caixa=500.0, token="CAT")
        resumo = afv.resumo_b3b_variantes_saida([s_stop, s_tp1], now=1e12, params=self._params())
        r = resumo["72h"]
        self.assertEqual(r.n_tp1_realizado, 1)       # condicional: so s_tp1
        self.assertEqual(r.pareamento.n, 1)
        self.assertEqual(r.n_vencido_todos, 2)        # todos: s_stop (resolvido) + s_tp1 (resolvido)
        self.assertEqual(r.pareamento_todos.n, 2)
        self.assertAlmostEqual(r.frac_tp1_pct_sobre_vencidos, 50.0)


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
