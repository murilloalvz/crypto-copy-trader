"""Ponta a ponta com mercado simulado: 70 min de mercado em milissegundos, sem rede."""

from __future__ import annotations

import json
import unittest
from typing import Optional

from ..http import ApiError
from ..models import TradesSummary
from ..telegram import OperatorHandler
from ..tracker import Plan, compute_outcome
from .fakes import SOL_TOKEN, T0, SimPool, evm_ok_record
from .helpers import Env


def rising(a: float) -> float:
    """Preco: 1.0x ate 2 min, sobe linear para 1.9x em 6 min, depois fica."""
    return 1.0 + 0.9 * min(1.0, max(0.0, (a - 120.0) / 360.0))


def happy(chain: str = "solana", pool: str = "POOL1", token: str = SOL_TOKEN, symbol: str = "KittyAI", **kw) -> SimPool:
    defaults = dict(
        chain=chain, pool=pool, token=token, symbol=symbol, created_ts=T0,
        vol_m5=lambda a: 0.0 if a < 60 else 12000.0,
        buys=lambda a: 0 if a < 60 else 60, sells=lambda a: 0 if a < 60 else 20,
        buyers=lambda a: 0 if a < 60 else 40, liq=lambda a: 40000.0, price=rising,
    )
    defaults.update(kw)
    return SimPool(**defaults)


class HappyPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Env()
        self.env.gt.add(happy())

    def tearDown(self) -> None:
        self.env.close()

    def run_full_hour(self) -> None:
        self.env.cycle(100)  # 100 x 45 s = 75 min

    def test_alert_is_sent_once_with_latency_and_buttons(self) -> None:
        self.env.cycle(5)
        self.assertEqual(len(self.env.tg.sent), 1)
        text, keyboard = self.env.tg.sent[0]
        self.assertIn("SOL", text)
        self.assertIn("$KittyAI", text)
        self.assertIn("novo", text)
        self.assertIn("GATO", text)
        self.assertIn("IA", text)
        self.assertIn("Plano: TP1 +60% (vende 50%)", text)
        self.assertIn("Lat:", text)
        self.assertIn(f"<code>{SOL_TOKEN}</code>", text)
        rows = keyboard["inline_keyboard"]
        self.assertEqual(rows[0][0]["text"], "Axiom")
        self.assertIn("axiom.trade", rows[0][0]["url"])
        self.assertEqual({b["callback_data"] for b in rows[1]}, {"e|1", "p|1"})
        # mais ciclos nao reenviam
        self.env.cycle(5)
        self.assertEqual(len(self.env.tg.sent), 1)

    def test_row_is_logged_with_versions_and_latency(self) -> None:
        self.env.cycle(5)
        row = self.env.read("sinais.csv")[0]
        self.assertEqual(row["etiqueta"], "novo")
        self.assertEqual(row["chain"], "solana")
        self.assertEqual(row["enviado"], "1")
        self.assertEqual(row["seguranca"], "ok")  # mint/freeze verificados pelo GT (GoPlus sem dado)
        self.assertEqual(row["versao_config"], self.env.cfg.version)
        self.assertEqual(row["versao_meta"], self.env.meta.version)
        self.assertGreaterEqual(float(row["latencia_s"]), 90.0)  # criado em T0, decidido >= 90 s depois
        self.assertEqual(row["tp1_antes_sl"], "pendente")
        self.assertEqual(row["mc_1h"], "")
        self.assertGreaterEqual(float(row["score"]), 60.0)

    def test_followup_finalizes_after_the_window_and_matches_tracker(self) -> None:
        self.run_full_hour()
        row = self.env.read("sinais.csv")[0]
        self.assertEqual(row["tp1_antes_sl"], "sim")
        signal = self.env.storage.get_signal(1)
        self.assertEqual(signal["status"], "finalizado")
        sim = self.env.gt.sims[("solana", "POOL1")]
        plan = Plan.from_dict(json.loads(signal["plano_json"]))
        candles = sim.candles(signal["decision_ts"] - 300, signal["decision_ts"] + 3660)
        expected = compute_outcome(candles, signal["entry_price"], signal["mc"], signal["decision_ts"], plan)
        self.assertAlmostEqual(signal["resultado_liq"], expected.resultado_liq_pct, places=6)
        self.assertGreater(signal["resultado_liq"], 40.0)
        self.assertAlmostEqual(signal["mc_1h"], signal["mc"] * 1.9, delta=signal["mc"] * 0.01)
        self.assertGreater(signal["max_mc"], signal["mc"] * 1.85)
        self.assertLess(signal["min_mc"], signal["mc"] * 1.05)

    def test_nothing_after_decision_leaks_into_the_score_features(self) -> None:
        """O sinal e decidido com a foto do instante: o preco de entrada e o da decisao, nao o do futuro."""
        self.env.cycle(5)
        signal = self.env.storage.get_signal(1)
        sim = self.env.gt.sims[("solana", "POOL1")]
        self.assertAlmostEqual(signal["entry_price"], sim.price0 * sim.price(signal["decision_ts"] - T0), places=12)
        self.assertEqual(signal["decision_ts"], T0 + 90)

    def test_operator_button_and_commands_write_trades_csv(self) -> None:
        self.env.cycle(5)
        handler = OperatorHandler(self.env.tg, self.env.storage, lambda: self.env.engine.cfg, self.env.clock)
        update = {"callback_query": {"id": "cb1", "data": "e|1", "message": {"message_id": 101, "chat": {"id": 42},
                  "reply_markup": {"inline_keyboard": [[{"text": "Axiom", "url": "https://x"}]]}}}}
        handler.process_update(update)
        handler.process_update(update)  # clique repetido nao duplica
        trades = self.env.read("trades_operador.csv")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["acao"], "entrei")
        self.assertEqual(trades[0]["valor"], "100.0")
        self.assertTrue(trades[0]["sinal_relacionado"].endswith("|novo"))
        self.assertEqual(self.env.read("sinais.csv")[0]["operou"], "1")
        self.assertEqual(self.env.tg.answers[-1][1], "ja registrado: entrei")
        self.assertIn("entrei", json.dumps(self.env.tg.edits[0][1], ensure_ascii=False))
        reply = handler.handle_command(f"/sai {SOL_TOKEN} 250,5")
        self.assertIn("sai registrado", reply)
        reply = handler.handle_command(f"/passei {SOL_TOKEN}")
        self.assertIn("passei registrado", reply)
        rows = self.env.read("trades_operador.csv")
        self.assertEqual([r["acao"] for r in rows], ["entrei", "sai", "passei"])
        self.assertEqual(rows[1]["valor"], "250.5")

    def test_restart_keeps_following_up(self) -> None:
        self.env.cycle(5)
        from ..engine import Engine

        self.env.engine = Engine(self.env.cfg, self.env.meta, self.env.storage, self.env.gt, self.env.goplus, self.env.tg,
                                 clock=self.env.clock, sleep=lambda s: None)
        self.env.cycle(95)
        self.assertEqual(self.env.storage.get_signal(1)["status"], "finalizado")
        # o 'novo' NAO foi reenviado depois do restart; o 2o alerta e o sobrevivente20 (20-25 min), legitimo
        labels = [r["etiqueta"] for r in self.env.read("sinais.csv")]
        self.assertEqual(labels, ["novo", "sobrevivente20"])
        self.assertEqual(len(self.env.tg.sent), 2)


class SecurityAndPolicyTest(unittest.TestCase):
    def tearDown(self) -> None:
        self.env.close()

    def bsc_sim(self, **kw) -> SimPool:
        defaults = dict(chain="bsc", pool="0xpool", token="0xtoken", symbol="KittyAI", dex="pancakeswap_v2")
        defaults.update(kw)
        return happy(**defaults)

    def test_honeypot_is_cut_and_logged_with_reason(self) -> None:
        self.env = Env()
        self.env.gt.add(self.bsc_sim())
        self.env.goplus.records["0xtoken"] = evm_ok_record(is_honeypot="1")
        self.env.cycle(5)
        self.assertEqual(self.env.read("sinais.csv"), [])
        rows = self.env.read("descartados.csv")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["etapa"], "seguranca")
        self.assertIn("honeypot", rows[0]["motivo"])
        self.assertEqual(rows[0]["versao_config"], self.env.cfg.version)
        self.assertEqual(self.env.tg.sent, [])

    def test_high_sell_tax_and_unlocked_lp_and_top10_are_cut(self) -> None:
        cases = {
            "taxas": evm_ok_record(sell_tax="0.30"),
            "lp": evm_ok_record(lp_holders=[{"address": "0xdev", "percent": "1.0", "is_locked": 0}]),
            "top10": evm_ok_record(holders=[{"address": "0xwhale", "tag": "", "percent": "0.55", "is_locked": 0}]),
        }
        for etapa_text, record in cases.items():
            with self.subTest(etapa_text):
                self.env = Env()
                self.env.gt.add(self.bsc_sim())
                self.env.goplus.records["0xtoken"] = record
                self.env.cycle(5)
                rows = self.env.read("descartados.csv")
                self.assertEqual(len(rows), 1, rows)
                self.assertIn(etapa_text, rows[0]["motivo"])
                self.assertEqual(self.env.read("sinais.csv"), [])
                self.env.close()

    def test_sem_dado_is_released_with_warning_and_never_marked_ok(self) -> None:
        self.env = Env()
        self.env.gt.add(self.bsc_sim())
        self.env.goplus.records["0xtoken"] = None  # GoPlus ainda nao indexou
        self.env.cycle(5)
        row = self.env.read("sinais.csv")[0]
        self.assertEqual(row["seguranca"], "sem_dado")
        text, _ = self.env.tg.sent[0]
        self.assertIn("SEM DADO", text)
        self.assertNotIn("Segurança: ok", text)
        self.assertIn("pen_seguranca" if False else "pen=", row["componentes_score"])

    def test_strict_mode_discards_sem_dado(self) -> None:
        self.env = Env({"seguranca": {"sem_dado_acao": "descartar"}})
        self.env.gt.add(self.bsc_sim())
        self.env.goplus.records["0xtoken"] = None
        self.env.cycle(5)
        self.assertEqual(self.env.read("sinais.csv"), [])
        rows = self.env.read("descartados.csv")
        self.assertEqual(rows[0]["etapa"], "seguranca")
        self.assertIn("sem_dado", rows[0]["motivo"])

    def test_strict_mode_waits_when_the_api_itself_failed(self) -> None:
        self.env = Env({"seguranca": {"sem_dado_acao": "descartar"}})
        self.env.gt.add(self.bsc_sim())
        self.env.goplus.error = ApiError("timeout")
        self.env.cycle(4)
        self.assertEqual(self.env.read("descartados.csv"), [])  # falha de API != veredito do token
        self.assertEqual(self.env.read("sinais.csv"), [])
        self.env.goplus.error = None
        self.env.goplus.records["0xtoken"] = evm_ok_record()
        self.env.cycle(2)
        self.assertEqual(self.env.read("sinais.csv")[0]["seguranca"], "ok")

    def test_per_chain_override_of_sem_dado_policy(self) -> None:
        self.env = Env({"seguranca": {"sem_dado_acao": "descartar"}, "chains": {"bsc": {"sem_dado_acao": "liberar_com_aviso"}}})
        self.env.gt.add(self.bsc_sim())
        self.env.goplus.records["0xtoken"] = None
        self.env.cycle(5)
        self.assertEqual(self.env.read("sinais.csv")[0]["seguranca"], "sem_dado")

    def test_solana_authority_active_is_cut_even_if_gt_says_ok(self) -> None:
        from .fakes import solana_ok_record

        self.env = Env()
        self.env.gt.add(happy())
        self.env.goplus.records[SOL_TOKEN] = solana_ok_record(mintable={"status": "1", "authority": ["x"]})
        self.env.cycle(5)
        self.assertEqual(self.env.read("sinais.csv"), [])
        self.assertIn("mint", self.env.read("descartados.csv")[0]["motivo"])


class FunnelTest(unittest.TestCase):
    def tearDown(self) -> None:
        self.env.close()

    def test_pool_that_never_triggers_expires_with_reason(self) -> None:
        self.env = Env()
        self.env.gt.add(happy(vol_m5=lambda a: 100.0))  # volume baixo sempre
        self.env.cycle(20)  # > 10 min
        rows = self.env.read("descartados.csv")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["etapa"], "gatilho")
        self.assertIn("expirou (novo)", rows[0]["motivo"])
        self.assertIn("vol_m5", rows[0]["motivo"])
        self.assertEqual(self.env.read("sinais.csv"), [])

    def test_low_liquidity_is_a_logged_cut(self) -> None:
        self.env = Env()
        self.env.gt.add(happy(liq=lambda a: 500.0))
        self.env.cycle(20)
        rows = self.env.read("descartados.csv")
        self.assertEqual(rows[0]["etapa"], "liquidez_minima")
        self.assertEqual(rows[0]["valor"], "500")

    def test_unreliable_liquidity_dex_is_not_cut_and_is_blank_in_csv(self) -> None:
        self.env = Env()
        self.env.gt.add(happy(dex="meteora-dbc", liq=lambda a: 0.0))
        self.env.engine.ctx  # noqa: B018
        self.env.cycle(5)
        row = self.env.read("sinais.csv")[0]
        self.assertEqual(row["liq"], "")  # desconhecida, nao zero

    def test_duplicate_token_on_same_dex_is_discarded(self) -> None:
        self.env = Env()
        self.env.gt.add(happy(pool="POOL1", token=SOL_TOKEN))
        self.env.gt.add(happy(pool="POOL2", token=SOL_TOKEN))
        self.env.cycle(5)
        self.assertEqual(len(self.env.read("sinais.csv")), 1)
        reasons = [r["etapa"] for r in self.env.read("descartados.csv")]
        self.assertEqual(reasons, ["duplicado"])

    def test_reference_pair_is_discarded_immediately(self) -> None:
        self.env = Env()
        self.env.gt.add(happy(both_reference=True))
        self.env.cycle(2)
        rows = self.env.read("descartados.csv")
        self.assertEqual(rows[0]["etapa"], "filtro")
        self.assertIn("referencia", rows[0]["motivo"])

    def test_non_sent_tokens_are_tracked_too(self) -> None:
        self.env = Env({"score": {"minimo_alerta": 99}})
        self.env.gt.add(happy())
        self.env.cycle(100)
        row = self.env.read("sinais.csv")[0]
        self.assertEqual(row["enviado"], "0")
        self.assertEqual(row["tp1_antes_sl"], "sim")  # acompanhado mesmo sem alerta
        self.assertEqual(self.env.tg.sent, [])

    def test_telegram_failure_is_recorded_not_fatal(self) -> None:
        self.env = Env()
        self.env.tg.fail_next = 5
        self.env.gt.add(happy())
        self.env.cycle(5)
        signal = self.env.storage.get_signal(1)
        self.assertEqual(signal["enviado"], 0)
        self.assertIn("falha_telegram", signal["motivo_nao_enviado"])

    def test_stale_alert_is_not_sent(self) -> None:
        self.env = Env({"alertas": {"max_atraso_s": 1}})
        self.env.gt.add(happy())
        original = self.env.engine._process_candidate  # noqa: SLF001

        def slow(*args, **kwargs):
            self.env.clock.advance(30)  # enriquecimento demorou
            return original(*args, **kwargs)

        self.env.engine._process_candidate = slow  # type: ignore[method-assign]
        self.env.cycle(5)
        signal = self.env.storage.get_signal(1)
        self.assertEqual(signal["enviado"], 0)
        self.assertTrue(signal["motivo_nao_enviado"].startswith("atraso_"))


class SurvivorTest(unittest.TestCase):
    def tearDown(self) -> None:
        self.env.close()

    def test_sobrevivente20_fires_in_window_with_initial_price_and_active_buys(self) -> None:
        self.env = Env()
        quiet = lambda a: 0  # noqa: E731
        self.env.gt.add(happy(
            vol_m5=lambda a: 100.0 if a < 20 * 60 else 3000.0,
            buys=lambda a: 2 if a < 20 * 60 else 15, sells=lambda a: 1 if a < 20 * 60 else 5,
            buyers=lambda a: 2 if a < 20 * 60 else 12, price=lambda a: 1.0 if a < 900 else 0.6,
        ))
        _ = quiet
        self.env.cycle(40)  # 30 min
        labels = [r["etiqueta"] for r in self.env.read("sinais.csv")]
        self.assertEqual(labels, ["sobrevivente20"])

    def test_sobrevivente20_rejects_price_below_40_percent(self) -> None:
        self.env = Env()
        self.env.gt.add(happy(
            vol_m5=lambda a: 100.0 if a < 20 * 60 else 3000.0,
            buys=lambda a: 2 if a < 20 * 60 else 15, sells=lambda a: 1 if a < 20 * 60 else 5,
            buyers=lambda a: 2 if a < 20 * 60 else 12, price=lambda a: 1.0 if a < 900 else 0.3,
        ))
        self.env.cycle(40)
        self.assertEqual(self.env.read("sinais.csv"), [])
        motives = " ".join(r["motivo"] for r in self.env.read("descartados.csv"))
        self.assertIn("do inicial", motives)


class ConfigVersioningTest(unittest.TestCase):
    def tearDown(self) -> None:
        self.env.close()

    def test_new_config_version_applies_to_new_rows_only(self) -> None:
        self.env = Env()
        self.env.gt.add(happy(pool="P1", token="T1"))
        self.env.cycle(4)
        old_version = self.env.engine.cfg.version
        from .helpers import config_with

        new_cfg = config_with({"plano": {"sl_pct": 20}})
        self.assertNotEqual(new_cfg.version, old_version)
        self.assertTrue(self.env.engine.set_config(new_cfg))
        self.env.gt.add(happy(pool="P2", token="T2", symbol="KittyAI2", created_ts=self.env.clock()))
        self.env.cycle(5)
        rows = self.env.read("sinais.csv")
        self.assertEqual([r["versao_config"] for r in rows], [old_version, new_cfg.version])
        plans = [json.loads(self.env.storage.get_signal(i)["plano_json"])["sl_pct"] for i in (1, 2)]
        self.assertEqual(plans, [30.0, 20.0])  # cada linha guarda o plano da SUA versao
        self.assertIsNotNone(self.env.storage.config_snapshot(old_version))
        self.assertIsNotNone(self.env.storage.config_snapshot(new_cfg.version))


class LateSecurityTest(unittest.TestCase):
    def tearDown(self) -> None:
        self.env.close()

    def test_late_recheck_is_recorded_without_touching_decision_time_status(self) -> None:
        self.env = Env()
        self.env.gt.add(happy(chain="bsc", pool="0xpool", token="0xtoken", dex="pancakeswap_v2"))
        self.env.goplus.records["0xtoken"] = None
        self.env.cycle(5)
        self.assertEqual(self.env.read("sinais.csv")[0]["seguranca"], "sem_dado")
        self.env.goplus.records["0xtoken"] = evm_ok_record(is_honeypot="1")  # ficou claro depois
        self.env.cycle(100)
        signal = self.env.storage.get_signal(1)
        self.assertEqual(signal["seguranca"], "sem_dado")  # nao reescreve o passado
        late = json.loads(signal["seguranca_tardia"])
        self.assertEqual(late["status"], "falhou")
        self.assertIn("honeypot", late["motivo"])


class StatusTest(unittest.TestCase):
    def test_status_and_summary_text(self) -> None:
        env = Env()
        try:
            env.gt.add(happy())
            env.cycle(100)
            status = env.engine.status_text()
            self.assertIn("config", status)
            summary = env.engine.build_daily_summary()
            self.assertIn("SOL", summary)
            self.assertIn("enviados 1", summary)
            self.assertIn("TP1>SL", summary)
            self.assertIn(env.cfg.version, summary)
        finally:
            env.close()

    def test_daily_summary_is_sent_once_after_the_hour(self) -> None:
        env = Env()
        try:
            env.gt.add(happy())
            env.cycle(5)
            from datetime import datetime

            local = datetime.fromtimestamp(env.clock())
            hour = f"{(local.hour + 1) % 24:02d}:00" if local.hour < 23 else "23:59"
            env.engine.c["resumo_diario"]["hora_local"] = hour
            self.assertFalse(env.engine.maybe_send_daily_summary(env.clock()))
            env.engine.c["resumo_diario"]["hora_local"] = "00:00"
            self.assertTrue(env.engine.maybe_send_daily_summary(env.clock()))
            self.assertFalse(env.engine.maybe_send_daily_summary(env.clock()))
        finally:
            env.close()


_ = Optional, TradesSummary


if __name__ == "__main__":
    unittest.main()
