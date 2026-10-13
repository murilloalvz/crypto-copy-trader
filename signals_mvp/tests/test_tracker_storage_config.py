"""Acompanhamento (simulacao do plano), storage/CSV, config e utilitarios."""

from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from ..config import ConfigError, build_config, load_config, make_paths
from ..models import Candle
from ..storage import DESCARTADOS_COLUMNS, SINAIS_COLUMNS, TRADES_COLUMNS, Storage
from ..tracker import CHECKPOINTS_MIN, Plan, _ceil_minute, compute_outcome
from ..util import (
    atomic_write_csv, canonical_json, clean_text, csv_safe, fmt_age, fmt_money, fmt_pct, fmt_usd, iso_utc, lerp01,
    load_env, parse_iso, redact, short_hash, to_float,
)
from .helpers import config_with, read_csv, shipped_config

PLAN = Plan(posicao_usd=100, tp1_pct=60, tp1_venda_pct=50, sl_pct=30, tempo_min=15, sl_apos_tp1="mantem", taxa_terminal_pct=1.0, fee_rede_usd=0.15)
T0 = 60_000.0 + 20  # decisao no segundo :20 do minuto
FIRST = _ceil_minute(T0)


def candle(i: float, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(FIRST + 60 * i, o, h, l, c, 100.0)


def flat(n: int, price: float = 1.0) -> list[Candle]:
    return [candle(i, price, price, price, price) for i in range(n)]


class TrackerTest(unittest.TestCase):
    def outcome(self, candles, plan=PLAN, mc=10_000.0):
        return compute_outcome(candles, 1.0, mc, T0, plan)

    def test_flat_price_costs_only_fees(self) -> None:
        out = self.outcome(flat(14))
        self.assertEqual(out.tp1_antes_sl, "nenhum")
        # entrada: 1% + 0.15 => 98.85 em token; saida: 98.85 x (1 - 1%) - 0.15 = 97.7115  => -2.2885%
        self.assertAlmostEqual(out.resultado_liq_pct, -2.2885, places=4)
        self.assertEqual((out.mc_5m, out.mc_15m, out.mc_1h), (10_000.0, 10_000.0, 10_000.0))

    def test_tp1_then_time_exit(self) -> None:
        out = self.outcome([candle(0, 1, 1.7, 1, 1.6)] + [candle(i, 1.6, 1.9, 1.5, 1.8) for i in range(1, 14)])
        self.assertEqual(out.tp1_antes_sl, "sim")
        self.assertAlmostEqual(out.resultado_liq_pct, 66.06, places=1)
        self.assertEqual([leg["motivo"] for leg in out.detail["pernas"]], ["tp1", "tempo"])

    def test_sl_only_and_gap_through_stop(self) -> None:
        sl = self.outcome([candle(0, 1, 1.0, 0.65, 0.7)])
        self.assertEqual(sl.tp1_antes_sl, "nao")
        self.assertAlmostEqual(sl.resultado_liq_pct, -31.65, places=1)
        gap = self.outcome([candle(0, 1, 1, 1, 1), candle(1, 0.5, 0.5, 0.4, 0.45)])
        self.assertAlmostEqual(gap.resultado_liq_pct, -51.22, places=1)  # saiu na abertura, pior que o stop

    def test_ambiguous_candle_assumes_worst_case(self) -> None:
        out = self.outcome([candle(0, 1, 1.7, 0.6, 1.0)])
        self.assertEqual(out.tp1_antes_sl, "ambiguo")
        self.assertAlmostEqual(out.resultado_liq_pct, -31.65, places=1)  # SL primeiro
        self.assertIn("ambiguo_sl_primeiro", out.detail["flags"])

    def test_stop_after_tp1_and_breakeven_option(self) -> None:
        candles = [candle(0, 1, 1.65, 1.0, 1.6), candle(1, 1.6, 1.6, 0.6, 0.7)]
        keep = self.outcome(candles)
        self.assertEqual(keep.tp1_antes_sl, "sim")
        self.assertAlmostEqual(keep.resultado_liq_pct, 12.24, places=1)
        be = self.outcome(candles, Plan(**{**PLAN.to_dict(), "sl_apos_tp1": "breakeven"}))
        self.assertAlmostEqual(be.resultado_liq_pct, 26.92, places=1)

    def test_candles_before_the_decision_are_ignored_for_the_path(self) -> None:
        """Candle que COMECA antes da decisao (inclusive o que a contem) nao entra na simulacao nem em max/min."""
        before = Candle(FIRST - 120, 1, 9, 0.1, 1, 100.0)       # pico enorme antes da decisao
        containing = Candle(FIRST - 60, 1, 9, 0.1, 1, 100.0)    # contem a decisao (comeca 40 s antes)
        out = self.outcome([before, containing] + flat(14))
        self.assertEqual(out.tp1_antes_sl, "nenhum")
        self.assertAlmostEqual(out.max_mc, 10_000.0)
        self.assertAlmostEqual(out.min_mc, 10_000.0)

    def test_unclosed_candle_at_the_time_stop_is_not_used(self) -> None:
        # prazo de 15 min: o candle que ainda estaria aberto em T0+900 nao pode decidir o resultado
        candles = flat(14) + [candle(14, 1, 5, 1, 5)]
        out = self.outcome(candles)
        self.assertEqual(out.tp1_antes_sl, "nenhum")

    def test_checkpoints_use_last_closed_candle_and_forward_fill(self) -> None:
        candles = [candle(i, 1 + i * 0.01, 1 + i * 0.01, 1 + i * 0.01, 1 + i * 0.01) for i in range(5)]  # so 5 min de trades
        out = self.outcome(candles)
        # +5 min: ultimo candle FECHADO ate T0+300 e o de indice 3 (fecha em FIRST+240 <= T0+300? T0+300 = FIRST+240)
        self.assertAlmostEqual(out.mc_5m, 10_000.0 * 1.03, places=3)
        self.assertAlmostEqual(out.mc_15m, 10_000.0 * 1.04, places=3)   # sem trades depois: carrega o ultimo close
        self.assertAlmostEqual(out.mc_1h, 10_000.0 * 1.04, places=3)
        self.assertEqual(CHECKPOINTS_MIN, (5, 15, 60))

    def test_missing_data_is_explicit(self) -> None:
        out = compute_outcome([], 1.0, 10_000.0, T0, PLAN)
        self.assertEqual(out.tp1_antes_sl, "sem_dado")
        self.assertIsNone(out.resultado_liq_pct)
        self.assertIsNone(out.mc_1h)
        no_mc = compute_outcome(flat(14), 1.0, None, T0, PLAN)
        self.assertIsNone(no_mc.mc_5m)
        self.assertIsNotNone(no_mc.resultado_liq_pct)  # o resultado do plano nao depende do MC

    def test_no_trades_after_decision_is_flagged(self) -> None:
        out = self.outcome([Candle(FIRST - 180, 1, 1, 1, 1, 10.0)])
        self.assertIn("sem_trades_na_janela", out.detail["flags"])
        self.assertEqual(out.tp1_antes_sl, "nenhum")
        self.assertIsNone(out.max_mc)


class StorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.paths = make_paths(self.tmp)
        self.st = Storage(self.paths)

    def tearDown(self) -> None:
        self.st.close()

    def signal(self, **kw) -> dict:
        base = dict(chain="bsc", pool="0xp", token="0xt", symbol="TKN", etiqueta="novo", decision_ts=1_791_900_000.0, score=70.0,
                    componentes="narr=1", mc=1000.0, seguranca="ok", enviado=1, versao_config="c", versao_meta="m")
        base.update(kw)
        return base

    def test_csv_headers_are_the_stable_contract(self) -> None:
        self.st.export_csvs(force=True)
        for name, columns in (("sinais.csv", SINAIS_COLUMNS), ("descartados.csv", DESCARTADOS_COLUMNS), ("trades_operador.csv", TRADES_COLUMNS)):
            header = (self.paths.dados / name).read_text(encoding="utf-8-sig").splitlines()[0]
            self.assertEqual(header.split(","), columns)
        self.assertEqual(",".join(SINAIS_COLUMNS), (
            "data,chain,token,contrato,etiqueta,score,componentes_score,mc,liq,vol_m5,acel_vol,compras,vendas,top10,seguranca,"
            "narrativa_match,enviado,operou,mc_5m,mc_15m,mc_1h,max,min,tp1_antes_sl,resultado_liq,latencia_s,versao_config,versao_meta"))
        self.assertEqual(",".join(DESCARTADOS_COLUMNS), "data,chain,token,contrato,etapa,motivo,valor,versao_config")
        self.assertEqual(",".join(TRADES_COLUMNS), "data,chain,contrato,acao,valor,sinal_relacionado")

    def test_signal_unique_per_pool_and_label(self) -> None:
        self.assertEqual(self.st.insert_signal(self.signal()), 1)
        self.assertIsNone(self.st.insert_signal(self.signal()))
        second = self.st.insert_signal(self.signal(etiqueta="sobrevivente20"))
        self.assertIsNotNone(second)  # (ids nao precisam ser contiguos: o SQLite consome um id no INSERT OR IGNORE ignorado)
        self.assertGreater(second, 1)
        with self.assertRaises(KeyError):
            self.st.insert_signal({"coluna_inventada": 1})
        with self.assertRaises(KeyError):
            self.st.update_signal(1, score=1)  # score nao e atualizavel depois

    def test_operou_is_derived_from_operator_trades(self) -> None:
        sid = self.st.insert_signal(self.signal())
        self.st.export_csvs()
        self.assertEqual(read_csv(self.paths.sinais_csv)[0]["operou"], "0")
        self.st.add_operator_trade(1_791_900_100.0, "bsc", "0xt", "passei", None, sid, "botao")
        self.st.export_csvs()
        self.assertEqual(read_csv(self.paths.sinais_csv)[0]["operou"], "0")
        self.st.add_operator_trade(1_791_900_200.0, "bsc", "0xt", "entrei", 50.0, sid, "comando")
        self.st.export_csvs()
        self.assertEqual(read_csv(self.paths.sinais_csv)[0]["operou"], "1")
        trades = read_csv(self.paths.trades_csv)
        self.assertEqual([t["acao"] for t in trades], ["passei", "entrei"])
        self.assertEqual(trades[0]["valor"], "")
        self.assertEqual(trades[1]["sinal_relacionado"], "2026-10-13T14:00:00Z|novo")

    def test_missing_values_are_blank_not_zero(self) -> None:
        self.st.insert_signal(self.signal(liq=None, vol_m5=None, acel_vol=None, compras=None))
        self.st.export_csvs()
        row = read_csv(self.paths.sinais_csv)[0]
        for column in ("liq", "vol_m5", "acel_vol", "compras", "vendas", "top10", "mc_5m", "resultado_liq", "latencia_s"):
            self.assertEqual(row[column], "", column)
        self.assertEqual(row["tp1_antes_sl"], "pendente")

    def test_formula_injection_is_neutralised(self) -> None:
        self.st.insert_signal(self.signal(symbol='=HYPERLINK("http://x")', narrativa="@evil"))
        self.st.add_discard(1.0, "bsc", "+cmd|x", "0xt", "seguranca", "-1+1", "", "c")
        self.st.export_csvs()
        self.assertTrue(read_csv(self.paths.sinais_csv)[0]["token"].startswith("'="))
        self.assertTrue(read_csv(self.paths.descartados_csv)[0]["token"].startswith("'+"))
        self.assertTrue(read_csv(self.paths.descartados_csv)[0]["motivo"].startswith("'-"))

    def test_locked_csv_is_retried_next_cycle_without_losing_data(self) -> None:
        self.st.insert_signal(self.signal())
        with mock.patch("signals_mvp.util.os.replace", side_effect=PermissionError("aberto no Excel")):
            self.assertEqual(self.st.export_csvs(), [])
        self.assertFalse(self.paths.sinais_csv.exists())
        written = self.st.export_csvs()
        self.assertIn("sinais.csv", written)
        self.assertEqual(len(read_csv(self.paths.sinais_csv)), 1)
        self.assertEqual(list(self.paths.dados.glob("*.tmp")), [])  # sem temporarios sobrando

    def test_state_survives_reopening(self) -> None:
        sid = self.st.insert_signal(self.signal(fin_proxima_ts=5.0))
        self.st.set_meta("tg_offset", "77")
        self.st.close()
        self.st = Storage(self.paths)
        self.assertEqual(self.st.get_signal(sid)["token"], "0xt")
        self.assertEqual(self.st.get_meta("tg_offset"), "77")
        self.assertEqual(len(self.st.signals_due(10.0)), 1)

    def test_labels_windows_and_expiry_queries(self) -> None:
        from .test_signal_logic import pool

        snap = pool(created_ts=1000.0, observed_ts=1030.0)
        self.assertTrue(self.st.add_pool_if_new(snap, ("novo", "sobrevivente20"), 1030.0))
        self.assertFalse(self.st.add_pool_if_new(snap, ("novo", "sobrevivente20"), 1040.0))
        row = self.st.get_pool("bsc", "0xpool")
        self.assertEqual((row["first_seen_age_s"], row["first_price"]), (30.0, snap.price_usd))
        # idade 100 s: so 'novo' ativo; idade 21 min: so 'sobrevivente20'; idade 40 min: nada ativo, ambos vencidos
        def active(now):
            return [r["etiqueta"] for r in self.st.pools_to_refresh(now, 600, 1200, 1500)]

        self.assertEqual(active(1100.0), ["novo"])
        self.assertEqual(active(1000.0 + 1260), ["sobrevivente20"])
        self.assertEqual(active(1000.0 + 2400), [])
        self.assertEqual([r["etiqueta"] for r in self.st.expired_labels(1000.0 + 700, 600, 1500)], ["novo"])
        self.st.finalize_label("bsc", "0xpool", "novo", "avaliado", 1500.0)
        self.assertEqual(self.st.open_labels("bsc", "0xpool"), ["sobrevivente20"])
        self.assertEqual(len(self.st.expired_labels(1000.0 + 2400, 600, 1500)), 1)

    def test_security_cache_only_keeps_final_verdicts(self) -> None:
        self.st.cache_security("bsc", "0xt", 100.0, "ok", {"status": "ok"})
        self.assertEqual(self.st.cached_security("bsc", "0xt", 150.0, 100.0), {"status": "ok"})
        self.assertIsNone(self.st.cached_security("bsc", "0xt", 300.0, 100.0))  # expirou
        self.st.cache_security("bsc", "0xu", 100.0, "parcial", {"status": "parcial"})
        self.assertIsNone(self.st.cached_security("bsc", "0xu", 110.0, 100.0))  # parcial nunca e cacheado como final


class ConfigTest(unittest.TestCase):
    def test_shipped_config_is_valid_and_hash_is_stable(self) -> None:
        a, b = shipped_config(), shipped_config()
        self.assertEqual(a.version, b.version)
        self.assertEqual(len(a.version), 12)
        self.assertEqual(set(a.enabled_chains()), {"solana", "bsc", "robinhood"})

    def test_comments_and_formatting_do_not_change_the_version_but_values_do(self) -> None:
        text = (Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8")
        base = build_config(yaml.safe_load(text)).version
        commented = build_config(yaml.safe_load("# comentario novo\n" + text.replace("minimo_alerta: 60", "minimo_alerta: 60   # ok"))).version
        self.assertEqual(base, commented)
        changed = build_config(yaml.safe_load(text.replace("minimo_alerta: 60", "minimo_alerta: 61"))).version
        self.assertNotEqual(base, changed)

    def test_every_problem_is_reported_at_once(self) -> None:
        raw = copy.deepcopy(shipped_config().raw)
        raw["score"]["pesos"]["fluxo"] = 40
        raw["plano"]["sl_pct"] = 0
        del raw["gt"]["burst"]
        raw["chains"]["bsc"]["terminal"] = "outro"
        raw["resumo_diario"]["hora_local"] = "25:00"
        raw["links"]["gmgn"] = "https://x/{inexistente}"
        raw["plano"]["tempo_min"] = 90
        with self.assertRaises(ConfigError) as ctx:
            build_config(raw)
        message = str(ctx.exception)
        for fragment in ("score.pesos", "plano.sl_pct", "gt.burst", "chains.bsc.terminal", "hora_local", "links.gmgn", "plano.tempo_min"):
            self.assertIn(fragment, message)

    def test_needs_at_least_one_enabled_chain_and_sane_stall_guard(self) -> None:
        raw = copy.deepcopy(shipped_config().raw)
        for chain in raw["chains"].values():
            chain["ligada"] = False
        with self.assertRaises(ConfigError):
            build_config(raw)
        with self.assertRaises(ConfigError):
            config_with({"ciclo": {"stall_guard_s": 40}})  # < 2x o intervalo de 45 s

    def test_invalid_yaml_file_and_encoding_fallback(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        bad = tmp / "config.yaml"
        bad.write_text("modo: [paper\n", encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_config(bad)
        ansi = tmp / "ansi.yaml"
        ansi.write_bytes((Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8").replace("po,", "pó,").encode("cp1252"))
        self.assertEqual(len(load_config(ansi).version), 12)  # salvo pelo Bloco de Notas em ANSI

    def test_make_paths_honours_env_home(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {"SIGNALS_MVP_HOME": str(tmp)}):
            self.assertEqual(make_paths().dados, tmp / "dados")


class UtilTest(unittest.TestCase):
    def test_numbers(self) -> None:
        self.assertEqual(to_float("1.5"), 1.5)
        for bad in (None, "", "abc", float("nan"), float("inf"), True):
            self.assertIsNone(to_float(bad))
        self.assertEqual(lerp01(5, 0, 10), 0.5)
        self.assertEqual(lerp01(5, 10, 0), 0.5)   # menor e melhor
        self.assertEqual(lerp01(None, 0, 10), 0.0)
        self.assertEqual(lerp01(99, 0, 10), 1.0)

    def test_formatting(self) -> None:
        self.assertEqual(fmt_usd(85000), "85k")
        self.assertEqual(fmt_usd(8500), "8,5k")
        self.assertEqual(fmt_usd(1_234_567), "1,2M")
        self.assertEqual(fmt_usd(950), "950")
        self.assertEqual(fmt_usd(None), "s/d")
        self.assertEqual(fmt_age(45), "45 s")
        self.assertEqual(fmt_age(240), "4 min")
        self.assertEqual(fmt_age(3900), "1 h 05")
        self.assertEqual(fmt_pct(22.4), "22%")
        self.assertEqual(fmt_money(1234.5), "1.234,50")

    def test_time_roundtrip(self) -> None:
        self.assertEqual(iso_utc(1_791_900_000.0), "2026-10-13T14:00:00Z")
        self.assertEqual(parse_iso("2026-10-13T14:00:00Z"), 1_791_900_000.0)
        self.assertIsNone(parse_iso("nao e data"))
        self.assertEqual(iso_utc(None), "")

    def test_hash_is_order_independent(self) -> None:
        self.assertEqual(short_hash({"a": 1, "b": [1, 2]}), short_hash({"b": [1, 2], "a": 1}))
        self.assertNotEqual(short_hash({"a": 1}), short_hash({"a": 2}))
        self.assertEqual(canonical_json({"b": 1, "a": 2}), '{"a":2,"b":1}')

    def test_redaction_removes_the_bot_token_everywhere(self) -> None:
        token = "123456789:AAH-fake_token_for_unit_tests_0123"
        for text in (f"erro https://api.telegram.org/bot{token}/sendMessage falhou", f"token={token}", f"x {token} y"):
            cleaned = redact(text, [token])
            self.assertNotIn(token, cleaned)
            self.assertNotIn("AAH-fake", cleaned)
        self.assertNotIn("AAH-fake", redact(f"/bot{token}/getUpdates"))  # mesmo sem saber o segredo (regex)

    def test_untrusted_text(self) -> None:
        self.assertEqual(clean_text("a\nb\r\tc\x00d", 20), "a b  c d")
        self.assertEqual(len(clean_text("x" * 500, 80)), 80)
        self.assertEqual(csv_safe("=1+1"), "'=1+1")
        self.assertEqual(csv_safe("-5"), "'-5")
        self.assertEqual(csv_safe("normal"), "normal")

    def test_env_loader_does_not_override_and_returns_only_names(self) -> None:
        tmp = Path(tempfile.mkdtemp()) / ".env"
        tmp.write_text("# c\nSIG_A=1\nSIG_B='dois'\nSIG_C=\nSIG_EXISTE=novo\nlinha invalida\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"SIG_EXISTE": "antigo"}, clear=False):
            for key in ("SIG_A", "SIG_B", "SIG_C"):
                os.environ.pop(key, None)
            loaded = load_env(tmp)
            self.assertEqual(sorted(loaded), ["SIG_A", "SIG_B"])
            self.assertEqual(os.environ["SIG_B"], "dois")
            self.assertEqual(os.environ["SIG_EXISTE"], "antigo")
            for key in ("SIG_A", "SIG_B"):
                os.environ.pop(key, None)

    def test_atomic_csv_roundtrip_with_unicode(self) -> None:
        path = Path(tempfile.mkdtemp()) / "x.csv"
        atomic_write_csv(path, ["a", "b"], [["买买买", "\U0001f4a9"], ["linha, com virgula", 'aspas "x"']])
        rows = read_csv(path)
        self.assertEqual(rows[0]["a"], "买买买")
        self.assertEqual(rows[1], {"a": "linha, com virgula", "b": 'aspas "x"'})


if __name__ == "__main__":
    unittest.main()
