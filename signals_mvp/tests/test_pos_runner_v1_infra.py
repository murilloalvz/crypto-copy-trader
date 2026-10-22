"""POS-RUNNER-V1: BRT, filtro de qualidade (dado_invalido) e as tabelas/CSV novas do storage (pr1_*).
Sem rede."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.brt import hora_brt, na_janela_ouro
from ..pos_runner.candles import Bar
from ..pos_runner.params_v1 import ParamsV1
from ..pos_runner.qualidade_v1 import avaliar_qualidade, l_bc_robusto
from ..storage import POS_RUNNER_V1_COLUMNS, POS_RUNNER_V1_FILTRADOS_COLUMNS, Storage

H = 3600


class BrtTests(unittest.TestCase):
    def test_hora_brt_is_three_hours_behind_utc(self):
        # 2026-01-15T12:00:00Z -> 09:00 BRT (UTC-3, sem horario de verao)
        self.assertEqual(hora_brt(1768478400), "09:00")

    def test_janela_ouro_inclusive_bounds(self):
        ts_0830 = 1768478400 - 3 * 3600 + 30 * 60   # recalculado abaixo com um horario conhecido
        self.assertTrue(na_janela_ouro(1768478400, "08:30", "14:00"))   # 09:00, dentro
        self.assertFalse(na_janela_ouro(1768478400 - 3 * 3600, "08:30", "14:00"))  # 06:00, fora
        _ = ts_0830


class QualidadeV1Tests(unittest.TestCase):
    def test_wick_ratio_above_threshold_is_invalid(self):
        bars = [Bar(0, 100.0, 1_000_000.0, 100.0, 1_000.0, 1.0), Bar(H, 1_000.0, 1_050.0, 950.0, 1_020.0, 1.0)]
        r = avaliar_qualidade(bars, ParamsV1())
        self.assertFalse(r.valido)
        self.assertEqual(r.motivo, "wick")

    def test_l_bc_below_floor_is_invalid(self):
        bars = [Bar(0, 50.0, 55.0, 48.0, 52.0, 1.0), Bar(H, 52.0, 60.0, 50.0, 58.0, 1.0)]
        r = avaliar_qualidade(bars, ParamsV1())
        self.assertFalse(r.valido)
        self.assertEqual(r.motivo, "l_bc_floor")

    def test_l_bc_between_the_old_and_the_new_floor_is_now_invalid(self):
        # revisao FASE 1.1 (2026-10-22): piso subiu de US$100 para US$5.000 -- a menor graduacao legitima
        # medida neste repo (pump.fun, N=8) e ~28k; o checkpoint do operador tem 164 pools com L_bc entre
        # US$14 e US$1.000 (impossivel para uma graduacao real). US$1.000 so caia no piso ANTIGO se fosse <100.
        bars = [Bar(0, 900.0, 950.0, 850.0, 920.0, 1.0), Bar(H, 920.0, 1_000.0, 900.0, 980.0, 1.0)]
        r = avaliar_qualidade(bars, ParamsV1())
        self.assertFalse(r.valido)
        self.assertEqual(r.motivo, "l_bc_floor")

    def test_l_bc_just_above_the_floor_is_valid_but_flagged_suspeito(self):
        bars = [Bar(0, 8_000.0, 8_500.0, 7_800.0, 8_200.0, 1.0), Bar(H, 8_200.0, 9_000.0, 8_000.0, 8_800.0, 1.0)]
        r = avaliar_qualidade(bars, ParamsV1())
        self.assertTrue(r.valido)
        self.assertTrue(r.suspeito)

    def test_l_bc_between_the_suspeito_alto_and_the_ceiling_is_valid_but_flagged_suspeito(self):
        bars = [Bar(0, 600_000.0, 620_000.0, 590_000.0, 610_000.0, 1.0),
               Bar(H, 610_000.0, 650_000.0, 600_000.0, 630_000.0, 1.0)]
        r = avaliar_qualidade(bars, ParamsV1())
        self.assertTrue(r.valido)
        self.assertTrue(r.suspeito)

    def test_l_bc_above_the_sanity_ceiling_is_invalid(self):
        bars = [Bar(0, 20_000_000.0, 21_000_000.0, 19_500_000.0, 20_500_000.0, 1.0),
               Bar(H, 20_500_000.0, 21_500_000.0, 20_000_000.0, 21_000_000.0, 1.0)]
        r = avaliar_qualidade(bars, ParamsV1())
        self.assertFalse(r.valido)
        self.assertEqual(r.motivo, "l_bc_ceiling")

    def test_a_plausible_graduation_is_valid(self):
        bars = [Bar(0, 40_000.0, 42_000.0, 39_000.0, 41_000.0, 1.0), Bar(H, 41_000.0, 45_000.0, 40_500.0, 44_000.0, 1.0)]
        r = avaliar_qualidade(bars, ParamsV1())
        self.assertTrue(r.valido)
        self.assertFalse(r.suspeito)   # dentro do grosso da distribuicao: nem baixo nem alto demais
        self.assertEqual(l_bc_robusto(bars), min(40_000.0, 41_000.0, 41_000.0))

    def test_no_bars_yet_is_valid_by_default(self):
        self.assertTrue(avaliar_qualidade([], ParamsV1()).valido)


class Pr1StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self):
        self.storage.close()

    def _row(self, **over):
        row = {
            "chain": "solana", "pool": "poolA", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "mintA", "symbol": "AAA", "launchpad": "pumpfun", "dex": "pumpswap", "versao_config_v1": "abc123",
            "gatilho": '["power_candle_rompimento"]', "tags": '["na_janela_idade"]', "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "origem": "trending", "event_json": '{"data":{"L_bc":50000,"queda_pct":85.0}}',
            "status": "aberto", "entry_price": 1.0, "stop": 0.9, "topo": 2.0, "s_suporte": 0.95, "r_resistencia": 1.5,
        }
        row.update(over)
        return row

    def test_insert_is_idempotent_on_the_unique_key(self):
        first = self.storage.pr1_insert_signal(self._row())
        self.assertIsNotNone(first)
        second = self.storage.pr1_insert_signal(self._row(symbol="should_be_ignored"))
        self.assertIsNone(second)
        self.assertEqual(len(self.storage.pr1_signals()), 1)

    def test_update_and_lookup_by_key(self):
        sid = self.storage.pr1_insert_signal(self._row())
        self.storage.pr1_update_signal(sid, status="fechado", result_net=0.12, reason="stop", tempo_h=4.0,
                                       tp1_price=1.4, exit_full_price=0.92)
        row = self.storage.pr1_signal_by_key("solana", "poolA", "1h", "ENTRADA", 1_000)
        self.assertEqual(row["status"], "fechado")
        self.assertAlmostEqual(row["result_net"], 0.12)

    def test_filtrados_are_counted_never_silent(self):
        self.storage.pr1_add_filtrado(100.0, "solana", "poolB", "mintB", "BBB", "filtrado_mc_baixo", "50000", "abc123")
        self.storage.pr1_add_filtrado(200.0, "solana", "poolC", "mintC", "CCC", "dado_invalido", "wick", "abc123")
        self.storage.pr1_add_filtrado(300.0, "solana", "poolD", "mintD", "DDD", "dado_invalido", "l_bc_floor", "abc123")
        counts = self.storage.pr1_filtrado_counts(0.0)
        self.assertEqual(counts, {"filtrado_mc_baixo": 1, "dado_invalido": 2})

    def test_uptime_sums_closed_and_open_sessions(self):
        a = self.storage.pr1_uptime_start(0.0)
        self.storage.pr1_uptime_stop(a, 3600.0, "reinicio")
        self.storage.pr1_uptime_start(7200.0)   # sessao ainda aberta
        hours = self.storage.pr1_uptime_hours(0.0, now=10_800.0)
        self.assertAlmostEqual(hours, 1.0 + 1.0)   # 1h fechada + 1h em andamento

    def test_csv_export_matches_the_declared_columns(self):
        sid = self.storage.pr1_insert_signal(self._row())
        self.storage.pr1_update_signal(sid, status="fechado", result_net=0.1, reason="stop", tempo_h=2.0)
        self.storage.pr1_add_filtrado(50.0, "solana", "poolE", "mintE", "EEE", "filtrado_idade", "", "abc123")
        self.storage.export_csvs(force=True)
        header_signals = self.storage.paths.pos_runner_v1_csv.read_text(encoding="utf-8-sig").splitlines()[0]
        self.assertEqual(header_signals.split(","), POS_RUNNER_V1_COLUMNS)
        header_filtrados = self.storage.paths.pos_runner_v1_filtrados_csv.read_text(encoding="utf-8-sig").splitlines()[0]
        self.assertEqual(header_filtrados.split(","), POS_RUNNER_V1_FILTRADOS_COLUMNS)


if __name__ == "__main__":
    unittest.main()
