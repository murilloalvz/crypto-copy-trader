"""PEDIDO 2026-11-12 (autorizado, rodada 18, item 3): testes de `pos_runner/entrada_suporte.py` --
o hash-freeze do pre-registro (MESMO padrao de `saida_fiel`) e `localizar_revisitas_suporte` (a
reconstrucao causal da caixa + a lista de revisitas ao suporte apos WATCHLIST e antes do gatilho
real). EXPLORATORIO -- so confere a mecanica/wiring, nunca testa edge economica."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.candles import Bar
from ..pos_runner.entrada_suporte import (
    PreregistroAlteradoError,
    garantir_entrada_suporte_registrada,
    garantir_suporte_forward_registrada,
    hash_do_preregistro,
    hash_do_preregistro_forward,
    localizar_revisitas_suporte,
    toque_causal,
)
from ..pos_runner.params_v3 import load_params_v3
from ..storage import Storage

H = 3600
T0 = 1_790_000_000 - (1_790_000_000 % H)
L_BC = 50_000.0
CREATED = T0 - 3 * 86400


def _bar(ts: float, o: float, h: float, l: float, c: float, v: float = 10.0) -> Bar:
    return Bar(ts=int(ts), open=o, high=h, low=l, close=c, volume=v, filled=False)


class Series:
    def __init__(self, start: int = T0):
        self.bars: list[Bar] = []
        self.t = start

    def add(self, o: float, h: float, l: float, c: float, v: float = 1_000.0) -> "Series":
        self.bars.append(Bar(self.t, o, h, l, c, v))
        self.t += H
        return self

    def flat(self, price: float, n: int = 1, v: float = 1_000.0) -> "Series":
        for _ in range(n):
            self.bars.append(Bar(self.t, price, price * 1.01, price * 0.99, price, v))
            self.t += H
        return self


def _bars_com_2_revisitas() -> list[Bar]:
    """MESMA mecanica de `test_pos_runner_v3.
    test_zone_min_candles_4_generates_a_signal_that_12_never_would_on_the_same_short_box` (zona
    armada com `ParamsV3` default, zone_min_candles=4), estendida pra ter uma 2a revisita (idx19)
    ESTRITAMENTE entre o WATCHLIST (idx17, 1o teste/revisita) e o gatilho real (ENTRADA, idx20) --
    verificado por `python -c` antes de travar este fixture no teste (ver rodada 18 item 3)."""
    s = Series()
    s.flat(60_000, 2)                                          # 0-1
    for p in (150_000, 300_000, 600_000, 900_000):              # 2-5
        s.add(p * 0.9, p * 1.02, p * 0.88, p)
    s.add(900_000, 1_000_000, 880_000, 950_000)                 # 6: pico (P_peak=1.000.000)
    for p in (800_000, 600_000, 400_000, 250_000):              # 7-10
        s.add(p * 1.1, p * 1.12, p * 0.97, p)
    s.add(250_000, 255_000, 155_000, 165_000)                   # 11: queda -> FASE2
    s.add(165_000, 170_000, 150_000, 155_000)                   # 12: fundo (S=150k, anchor)
    s.add(155_000, 260_000, 154_000, 250_000)                   # 13: 1o repique -> R=260k
    s.add(240_000, 245_000, 200_000, 210_000)                   # 14
    s.add(210_000, 212_000, 200_000, 205_000)                   # 15
    s.add(205_000, 208_000, 200_000, 204_000)                   # 16
    s.add(204_000, 206_000, 152_000, 200_000)                   # 17: 1o teste (dentro de 157,5k) -> WATCHLIST
    s.add(200_000, 205_000, 198_000, 201_000)                   # 18: vermelho, sem gatilho, sem novo toque
    s.add(201_000, 203_000, 151_000, 198_000)                   # 19: 2a revisita (apos o WATCHLIST)
    s.add(198_000, 220_000, 196_000, 215_000)                   # 20: recupera -> ENTRADA (reacao_suporte)
    s.add(215_000, 230_000, 210_000, 225_000)                   # 21
    s.add(225_000, 350_000, 220_000, 340_000, v=10_000.0)       # 22
    return s.bars


class LocalizarRevisitasSuporteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.params = load_params_v3()
        self.bars = _bars_com_2_revisitas()

    def test_acha_a_revisita_estritamente_entre_watchlist_e_gatilho(self) -> None:
        revisitas = localizar_revisitas_suporte(self.bars, "1h", L_BC, CREATED, self.params,
                                                zona_alvo=1, gatilho_idx=20)
        self.assertEqual(len(revisitas), 1)
        r = revisitas[0]
        self.assertEqual(r.idx, 19)
        self.assertAlmostEqual(r.low, 151_000.0)
        self.assertAlmostEqual(r.s_no_momento, 150_000.0)
        self.assertAlmostEqual(r.stop, 150_000.0 * (1.0 - self.params.stop_below_wick_pct))

    def test_vazia_quando_watchlist_e_gatilho_sao_adjacentes(self) -> None:
        """MESMO fixture, mas pedindo o gatilho no proprio candle do WATCHLIST (idx17) -- nenhum
        candle sobra estritamente entre os 2, logo NAO ELEGIVEL (nunca inventa uma revisita)."""
        revisitas = localizar_revisitas_suporte(self.bars, "1h", L_BC, CREATED, self.params,
                                                zona_alvo=1, gatilho_idx=17)
        self.assertEqual(revisitas, [])

    def test_vazia_para_zona_que_nunca_existiu(self) -> None:
        revisitas = localizar_revisitas_suporte(self.bars, "1h", L_BC, CREATED, self.params,
                                                zona_alvo=99, gatilho_idx=20)
        self.assertEqual(revisitas, [])


class GarantirEntradaSuporteRegistradaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="entrada_suporte_hash_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_1a_chamada_registra_o_hash_atual(self) -> None:
        atual = hash_do_preregistro()
        registrado = garantir_entrada_suporte_registrada(self.storage)
        self.assertEqual(registrado, atual)
        self.assertEqual(self.storage.get_meta("entrada_suporte_preregistro_hash"), atual)

    def test_2a_chamada_com_hash_igual_nao_recusa(self) -> None:
        garantir_entrada_suporte_registrada(self.storage)
        de_novo = garantir_entrada_suporte_registrada(self.storage)
        self.assertEqual(de_novo, hash_do_preregistro())

    def test_recusa_se_o_hash_registrado_divergir(self) -> None:
        self.storage.set_meta("entrada_suporte_preregistro_hash", "0" * 12)
        with self.assertRaises(PreregistroAlteradoError):
            garantir_entrada_suporte_registrada(self.storage)


class GarantirSuporteForwardRegistradaTests(unittest.TestCase):
    """RODADA 19 item 2: MESMA disciplina, hash SEPARADO (`entrada_suporte_forward_preregistro_hash`)
    -- pre-registro da coleta FORWARD, nunca confundido com o do retrospectivo (rodada 18) acima."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="suporte_forward_hash_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_1a_chamada_registra_o_hash_atual(self) -> None:
        atual = hash_do_preregistro_forward()
        registrado = garantir_suporte_forward_registrada(self.storage)
        self.assertEqual(registrado, atual)
        self.assertEqual(self.storage.get_meta("entrada_suporte_forward_preregistro_hash"), atual)

    def test_2a_chamada_com_hash_igual_nao_recusa(self) -> None:
        garantir_suporte_forward_registrada(self.storage)
        de_novo = garantir_suporte_forward_registrada(self.storage)
        self.assertEqual(de_novo, hash_do_preregistro_forward())

    def test_recusa_se_o_hash_registrado_divergir(self) -> None:
        self.storage.set_meta("entrada_suporte_forward_preregistro_hash", "0" * 12)
        with self.assertRaises(PreregistroAlteradoError):
            garantir_suporte_forward_registrada(self.storage)

    def test_hash_forward_e_diferente_do_hash_do_retrospectivo(self) -> None:
        self.assertNotEqual(hash_do_preregistro_forward(), hash_do_preregistro())


class ToqueCausalTests(unittest.TestCase):
    """RODADA 19 item 1: `toque_causal` (nova mecanica -- `live.py` nao pode importar
    `scripts/varredura_v3._toque_causal`, reusa esta copia dedicada em `pos_runner/`)."""

    def test_stop_decide_quando_low_toca_antes_do_alvo(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100), _bar(H, 100, 101, 99, 101),
            _bar(2 * H, 101, 102, 70, 75),   # low=70<=stop(80)
        ]
        self.assertEqual(toque_causal(bars, 1, 100.0, 80.0, 2.0), "stop")

    def test_alvo_decide_quando_high_toca_antes_do_stop(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100), _bar(H, 100, 101, 99, 101),
            _bar(2 * H, 101, 121, 99, 115),   # high=121 >= alvo (entry 100 + 1x risco 20 = 120)
        ]
        self.assertEqual(toque_causal(bars, 1, 100.0, 80.0, 1.0), "alvo")

    def test_indefinido_quando_a_serie_acaba_sem_decidir(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(H, 100, 101, 99, 101)]
        self.assertIsNone(toque_causal(bars, 1, 100.0, 80.0, 5.0))

    def test_risco_nao_positivo_devolve_none(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100)]
        self.assertIsNone(toque_causal(bars, 0, 100.0, 100.0, 2.0))
