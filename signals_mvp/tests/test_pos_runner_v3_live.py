"""PEDIDO 2026-11-06 (autorizado, rodada 12, Parte 3): testes do que a V3 ao vivo (`pos_runner/
live.py`) ganhou nesta rodada -- `entry_price_alerta` capturado no instante REAL do envio do alerta
(nunca mais uma copia do preco modelado na deteccao) e a sombra incremental da saida fiel
(`pr3_saidas_sombra`, `_sombra_saida_fiel_v3`). PAPER/READ-ONLY -- nunca altera sinais/alertas/H1/
trajetoria de verdade; so o que a Parte 3 pediu."""

from __future__ import annotations

import json
import types
import unittest

from ..pos_runner.candles import Bar
from ..pos_runner.detector_v1 import EventV1
from .test_pos_runner_live import LiveHarness
from .test_pos_runner_v1 import L_BC


def _bar(ts: float, o: float, h: float, l: float, c: float, v: float = 10.0) -> Bar:
    return Bar(ts=int(ts), open=o, high=h, low=l, close=c, volume=v, filled=False)


def _row(pool: str = "POOL1", mint: str = "MINT1", symbol: str = "CAT") -> dict:
    return {"pool": pool, "mint": mint, "symbol": symbol, "launchpad": "pumpfun", "dex": "pumpswap",
           "l_bc": L_BC, "info": "{}", "supply": None, "found_ts": None}


class EntryPriceAlertaNoInstanteDoEnvioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness(v3_alertas=True)

    def tearDown(self) -> None:
        self.h.close()

    def test_usa_o_ultimo_candle_do_det_no_envio_nunca_a_copia_do_preco_modelado(self) -> None:
        ev = EventV1(kind="ENTRADA", idx=0, ts=0, decision_ts=0,
                    data={"close": 100.0, "stop": 80.0, "TOPO": 200.0, "S": 50.0, "gatilho": []})
        row = _row()
        # det.bars[-1].close=105.0 -- DIFERENTE do close modelado na deteccao (ev.data["close"]=100.0):
        # simula um candle mais novo ja ingerido pelo detector no instante REAL do envio (ex.: alerta
        # atrasado, ou reenviado num restart que repete candles ja persistidos).
        det = types.SimpleNamespace(
            bars=[_bar(0, 100, 101, 99, 100), _bar(3600, 100, 101, 99, 101), _bar(7200, 105, 106, 104, 105)],
            step=3600)
        self.h.live._entry_v3(row, "1h", det, ev, now=10.0)
        signal = self.h.storage.pr3_signal_by_key("solana", "POOL1", "1h", "ENTRADA", 0)
        self.assertIsNotNone(signal)
        self.assertIsNotNone(signal["tg_message_id"])   # alerta saiu (v3_alertas=True, nada bloqueou)
        self.assertEqual(signal["entry_price_alerta"], 105.0)
        self.assertNotEqual(signal["entry_price_alerta"], ev.data["close"])
        self.assertEqual(signal["entry_price"], 100.0)   # entry_price (provisorio) nunca e tocado aqui

    def test_sem_alerta_enviado_entry_price_alerta_fica_no_valor_provisorio_do_insert(self) -> None:
        # v3_alertas=False -- o INSERT ainda grava o valor provisorio (ev.data["close"]), mas o
        # trecho que sobrescreve no envio real nunca roda (sem envio, sem sobrescrita).
        h2 = LiveHarness(v3_alertas=False)
        try:
            ev = EventV1(kind="ENTRADA", idx=0, ts=0, decision_ts=0,
                        data={"close": 100.0, "stop": 80.0, "TOPO": 200.0, "S": 50.0, "gatilho": []})
            row = _row()
            det = types.SimpleNamespace(bars=[_bar(0, 100, 101, 99, 100)], step=3600)
            h2.live._entry_v3(row, "1h", det, ev, now=10.0)
            signal = h2.storage.pr3_signal_by_key("solana", "POOL1", "1h", "ENTRADA", 0)
            self.assertIsNotNone(signal)
            self.assertIsNone(signal["tg_message_id"])
            self.assertEqual(signal["entry_price_alerta"], 100.0)   # valor provisorio do INSERT
        finally:
            h2.close()


class SombraSaidaFielV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def _inserir_sinal_confirmado(self, bars: list[Bar], stop: float, topo: float) -> int:
        ev = EventV1(kind="ENTRADA", idx=0, ts=bars[0].ts, decision_ts=bars[0].ts,
                    data={"close": bars[1].open, "stop": stop, "TOPO": topo, "S": 0.0})
        from ..pos_runner.live import event_v1_to_json
        signal_id = self.h.storage.pr3_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA",
            "ts_fechamento": int(bars[0].ts), "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun",
            "dex": "pumpswap", "versao_config_v3": self.h.live.version_v3, "gatilho": "[]", "tags": "[]",
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "aberto",
            "entry_price": bars[1].open, "stop": stop, "topo": topo, "s_suporte": 0.0,
            "event_json": event_v1_to_json(ev),
        })
        self.h.storage.pr_trajetoria_upsert("v3", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                            mint="MINT1", symbol="CAT", t_entrada=float(bars[1].ts),
                                            preco_entrada=bars[1].open, risco_pct=10.0, r_unidade=10.0,
                                            fonte_candle="gt")
        return signal_id

    def test_grava_uma_linha_por_horizonte_com_status_e_tp1(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 102, 96, 101),     # entry=100
            _bar(7200, 101, 102, 70, 75),      # low=70 <= stop(80) -- fecha aqui, nunca viu TP1
        ]
        signal_id = self._inserir_sinal_confirmado(bars, stop=80.0, topo=10_000.0)
        det = types.SimpleNamespace(bars=bars)
        self.h.live._sombra_saida_fiel_v3(_row(), "1h", det, now=bars[1].ts + 73 * 3600.0)
        r72 = self.h.storage.pr3_saidas_sombra_get(signal_id, "72h")
        self.assertIsNotNone(r72)
        self.assertEqual(r72["status"], "resolvido")
        self.assertEqual(r72["tp1_realizado"], 0)
        self.assertLess(r72["r_mult"], 0.0)
        r7d = self.h.storage.pr3_saidas_sombra_get(signal_id, "7d")
        self.assertIsNotNone(r7d)

    def test_horizonte_nao_decorrido_fica_pendente_e_nunca_crasha(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(3600, 100, 102, 96, 101)]
        signal_id = self._inserir_sinal_confirmado(bars, stop=80.0, topo=10_000.0)
        det = types.SimpleNamespace(bars=bars)
        self.h.live._sombra_saida_fiel_v3(_row(), "1h", det, now=bars[1].ts + 1.0)
        r = self.h.storage.pr3_saidas_sombra_get(signal_id, "72h")
        self.assertIsNotNone(r)
        self.assertEqual(r["status"], "pendente")
        self.assertIsNone(r["r_mult"])

    def test_sem_trajetoria_confirmada_nunca_calcula_nada(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(3600, 100, 102, 96, 101)]
        from ..pos_runner.live import event_v1_to_json
        ev = EventV1(kind="ENTRADA", idx=0, ts=bars[0].ts, decision_ts=bars[0].ts,
                    data={"close": bars[1].open, "stop": 80.0, "TOPO": 10_000.0, "S": 0.0})
        signal_id = self.h.storage.pr3_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA",
            "ts_fechamento": int(bars[0].ts), "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun",
            "dex": "pumpswap", "versao_config_v3": self.h.live.version_v3, "gatilho": "[]", "tags": "[]",
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "aberto",
            "entry_price": bars[1].open, "stop": 80.0, "topo": 10_000.0, "s_suporte": 0.0,
            "event_json": event_v1_to_json(ev),
        })
        det = types.SimpleNamespace(bars=bars)
        self.h.live._sombra_saida_fiel_v3(_row(), "1h", det, now=bars[1].ts + 50 * 3600.0)
        self.assertEqual(self.h.storage.pr3_saidas_sombra_all(signal_id), [])


if __name__ == "__main__":
    unittest.main()
