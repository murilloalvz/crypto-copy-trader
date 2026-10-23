"""Teste de equivalencia da instrumentacao de medicao da POS-RUNNER-V1 (PAPER / so leitura).

Pedido do operador: a instrumentacao (campos de medicao em pr1_signals/CSV, /entrei e /sai com preco
real + slippage, /pulei) NUNCA pode mudar um sinal gerado pelo detector/simulador/banca da V1. Este
teste reproduz o MESMO cenario de `test_pos_runner_v1_live.EntradaTests.
test_tp1_then_stop_closes_the_trade_and_updates_bankroll` (textbook + TP1 + stop) e verifica que os
campos NUCLEARES do sinal (os que existiam ANTES desta revisao -- preco de entrada, stop, topo,
suporte/resistencia, gatilho, tags, status, motivo de saida, resultado liquido, tempo no trade) saiem
BIT A BIT iguais aos valores capturados na branch antes da instrumentacao entrar (ver o commit desta
revisao para o antes/depois completo). As colunas NOVAS (ts_fechamento_candle, ts_alerta,
ts_envio_telegram, retorno_sol_dia, liquidez_usd) sao verificadas separadamente -- elas podem (e devem)
aparecer, mas nunca podem alterar os campos nucleares nem o CSV de banca (pos_runner_v1_banca.csv),
que fica BYTE A BYTE idêntico (nenhuma coluna nova foi acrescentada lá)."""

from __future__ import annotations

import unittest

from ..http import CallBudget
from ..pos_runner.candles import Bar
from ..pos_runner.quotes import REFERENCE_POOLS, SOL_MINT
from .test_pos_runner import GRAD, H, textbook
from .test_pos_runner_live import LiveHarness
from .test_pos_runner_v1_live import start_tracking

# Campos NUCLEARES (existiam antes da instrumentacao) -- capturados rodando este MESMO cenario na
# branch signals-mvp antes desta revisao (commit 0a09926, FASE 3).
GOLDEN_CORE = {
    "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1790089200,
    "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
    "versao_config_v1": "279b79ffa3f0", "gatilho": '["reacao_suporte"]',
    "tags": '["risco_fora_da_faixa", "holders_indisponivel"]', "janela_ouro": "janela_ouro",
    "hora_brt": "12:00", "origem": "pumpswap", "teste_vol_ratio": None, "status": "fechado",
    "entry_price": 240000.0, "stop": 151900.0, "topo": 1000000.0, "s_suporte": 150000.0,
    "r_resistencia": 259999.99999999997, "tp1_price": 700000.0, "exit_full_price": 151900.0,
    "result_net": 0.2557752505264488, "reason": "stop", "tempo_h": 5.0,
    # mint_authority/freeze_authority eram sempre None antes da FASE 2 de medicao/UX (item 2: 1
    # chamada RPC por mint, cacheada) -- nesta fixture nao ha RPC configurado, entao o valor correto
    # e o "indisponivel" explicito (nunca None de novo, e nunca "ativa"/"revogada" adivinhado).
    "holders_tag": "holders_indisponivel", "mint_authority": "indisponivel", "freeze_authority": "indisponivel",
}

GOLDEN_BANCA_CSV = (
    "﻿data_entrada,token,contrato,launchpad,tf,mc_entrada,mc_tp1,mc_saida,motivo_saida,"
    "tempo_no_trade_h,lucro_bruto_%,taxas_%,lucro_liquido_%,tamanho_posicao_usd,resultado_usd,"
    "banca_depois_usd\n"
    "2026-09-22T15:00:00Z,CAT,MINT1,pumpfun,1h,240000.0,700000.0,151900.0,stop,5.0,"
    "31.804166666666678,6.7520898510799565,25.052076815586723,10.0,2.505207681558672,"
    "102.50520768155867\n"
)


class InstrumentacaoNuncaMudaOSinalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def _run_scenario(self) -> None:
        start_tracking(self.h)
        self.h.run_hours(17)
        s = textbook(start_flat=0)
        t = s.bars[-1].ts + H
        extra = [
            Bar(t, 400_000, 420_000, 395_000, 410_000, 1_000.0),
            Bar(t + H, 405_000, 1_050_000, 400_000, 620_000, 1_000.0),
            Bar(t + 2 * H, 700_000, 710_000, 690_000, 705_000, 1_000.0),
            Bar(t + 3 * H, 705_000, 710_000, 151_000, 152_000, 1_000.0),
        ]
        self.h.world.add_series("POOL1", "1h", s.bars + extra)
        self.h.list_pool()
        self.h.tick()
        self.h.verifier.step()
        self.h.tick()
        ref_pool, _side = REFERENCE_POOLS[SOL_MINT]
        self.h.world.series[(ref_pool, "1h")] = [
            Bar(GRAD - 30 * H + k * H, 150.0, 150.0, 150.0, 150.0, 1e6) for k in range(400)
        ]
        for _ in range(27):
            self.h.clock.advance(H)
            self.h.tick()
            self.h.live.http.arm(CallBudget(10), 1, 10)
            self.h.live.quotes.series(SOL_MINT, GRAD, self.h.clock())
            self.h.live.http.disarm()

    def test_core_signal_fields_are_bit_for_bit_identical_to_the_pre_instrumentation_golden(self) -> None:
        self._run_scenario()
        rows = self.h.storage.pr1_signals()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        core = {k: row[k] for k in GOLDEN_CORE}
        self.assertEqual(core, GOLDEN_CORE)

    def test_banca_csv_stays_byte_for_byte_identical(self) -> None:
        self._run_scenario()
        self.h.storage.export_csvs(force=True)
        content = self.h.storage.paths.pos_runner_v1_banca_csv.read_text(encoding="utf-8")
        self.assertEqual(content, GOLDEN_BANCA_CSV)

    def test_new_instrumentation_fields_are_populated_without_touching_the_core(self) -> None:
        self._run_scenario()
        row = self.h.storage.pr1_signals()[0]
        self.assertEqual(row["ts_fechamento_candle"], row["ts_fechamento"])
        self.assertIsNotNone(row["ts_alerta"])
        self.assertIsNotNone(row["ts_envio_telegram"])
        self.assertEqual(row["ts_envio_telegram"], row["alert_ts"])  # mesmo instante, nome mais claro
        # liquidez_usd veio do PoolSnap do radar (zero chamada nova) -- fixture ja fornece 100000.
        self.assertEqual(row["liquidez_usd"], 100_000.0)


if __name__ == "__main__":
    unittest.main()
