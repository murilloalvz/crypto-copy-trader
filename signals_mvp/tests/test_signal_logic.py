"""Seguranca (GoPlus), narrativa, metricas, gatilhos e score."""

from __future__ import annotations

import copy
import unittest

from ..geckoterminal import parse_pools_response, parse_token_info
from ..goplus import GoPlusClient, parse_security_response
from ..http import ApiError, HttpClient, RateLimiter
from ..metrics import acceleration, compute_metrics
from ..models import ChainCtx, PoolSnap, WindowTx
from ..narrative import EMPTY_META, match_meta, normalize_words, parse_meta
from ..scoring import score_token
from ..security import evaluate
from ..triggers import check_novo, check_sobrevivente20
from ..util import parse_iso
from .fakes import FakeClock, FakeResponse, FakeSession, evm_ok_record, load_fixture, solana_ok_record
from .helpers import shipped_config

CFG = shipped_config().raw
SEC = CFG["seguranca"]
BSC = ChainCtx("bsc", "evm", "bsc", frozenset({"0x0000000000000000000000000000000000000000", "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c", "0x55d398326f99059ff775485246999027b3197955"}))
SOL = ChainCtx("solana", "solana", "solana", frozenset({"So11111111111111111111111111111111111111112"}), frozenset({"meteora-dbc"}))
NOW = parse_iso("2026-10-13T13:46:00Z")


def pool(**kw) -> PoolSnap:
    base = dict(
        chain="bsc", pool="0xpool", dex="pancakeswap_v2", name="X / WBNB", created_ts=NOW - 240, observed_ts=NOW, token="0xtoken",
        symbol="X", token_name="X", target_side="base", other_token="0xbb", other_symbol="WBNB", other_is_reference=True,
        both_reference=False, price_usd=1e-5, fdv_usd=50_000.0, mcap_usd=None, liq_usd=30_000.0,
        vol={"m5": 5000.0, "h1": 5000.0}, tx={"m5": WindowTx(40, 15, 30, 10)}, price_change={},
    )
    base.update(kw)
    return PoolSnap(**base)


class GoPlusParsingTest(unittest.TestCase):
    def test_absent_token_is_none_not_ok(self) -> None:
        data = load_fixture("goplus_bsc_ok.json")
        tokens = ["0x0ff33f4d07dade0835a33e4b664fb242a701f5e1", "0x27071edc2e8681c97f6682c60e656d304602b99d"]
        out = parse_security_response(data, "evm", tokens)
        self.assertIsNotNone(out[tokens[0]])
        self.assertIsNone(out[tokens[1]])

    def test_checksum_case_is_matched_for_evm(self) -> None:
        data = load_fixture("goplus_bsc_ok.json")
        out = parse_security_response(data, "evm", ["0x0FF33F4D07DADE0835A33E4B664FB242A701F5E1"])
        self.assertIsNotNone(next(iter(out.values())))

    def test_error_payload_raises(self) -> None:
        with self.assertRaises(ApiError):
            parse_security_response({"code": 4029, "message": "limite", "result": None}, "evm", ["0x1"])
        with self.assertRaises(ApiError):
            parse_security_response([], "evm", ["0x1"])

    def test_client_batches_and_reports_partial_failure(self) -> None:
        def answer(url, params):
            if "0xbad" in params["contract_addresses"]:
                return FakeResponse(500, {})
            return FakeResponse(200, {"code": 1, "result": {}})

        limiter = RateLimiter(6000, 100, clock=FakeClock(0), sleep=lambda s: None)
        session = FakeSession([("token_security/56", answer)])
        client = GoPlusClient(HttpClient("https://api.gopluslabs.io/api/v1", limiter, session=session), batch_max=2)
        results, error = client.security("evm", "56", ["0xa", "0xb", "0xbad", "0xc"])
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(set(results), {"0xa", "0xb"})  # o lote que falhou nao aparece (nao foi consultado)
        self.assertIsNotNone(error)
        solana_session = FakeSession([("solana/token_security", FakeResponse(200, {"code": 1, "result": {}}))])
        client = GoPlusClient(HttpClient("https://x", limiter, session=solana_session))
        client.security("solana", "solana", ["Mint1"])
        self.assertTrue(solana_session.calls[0][0].endswith("/solana/token_security"))


class SecurityEvaluationTest(unittest.TestCase):
    def test_real_bsc_record_with_unlocked_lp_fails(self) -> None:
        rec = parse_security_response(load_fixture("goplus_bsc_ok.json"), "evm", ["0x0ff33f4d07dade0835a33e4b664fb242a701f5e1"])
        result = evaluate("evm", next(iter(rec.values())), pool(), SEC)
        self.assertEqual(result.status, "falhou")
        self.assertIn("LP travada/queimada 0%", result.failure_reason())

    def test_real_late_record_is_partial_not_ok(self) -> None:
        rec = parse_security_response(load_fixture("goplus_bsc_hpe_late.json"), "evm", ["0x27071edc2e8681c97f6682c60e656d304602b99d"])
        result = evaluate("evm", next(iter(rec.values())), pool(), SEC)
        self.assertEqual(result.status, "parcial")
        self.assertIn("top10", [c.name for c in result.nodata()])

    def test_real_robinhood_shell_is_sem_dado_even_though_open_source_says_zero(self) -> None:
        data = load_fixture("goplus_rh_shell.json")
        token = next(iter(data["result"]))
        rec = parse_security_response(data, "evm", [token])[token]
        result = evaluate("evm", rec, pool(dex="pons-v2"), SEC)
        self.assertEqual(result.status, "sem_dado")
        self.assertEqual(result.failures(), [])

    def test_real_fourmeme_curve_record(self) -> None:
        data = load_fixture("goplus_fourmeme.json")
        token = next(iter(data["result"]))
        rec = parse_security_response(data, "evm", [token])[token]
        result = evaluate("evm", rec, pool(dex="four-meme", pool=token), SEC)
        self.assertEqual(result.status, "parcial")
        lp = next(c for c in result.checks if c.name == "lp")
        self.assertEqual(lp.status, "na")  # sem LP em curva de bonding

    def test_healthy_evm_record_is_ok(self) -> None:
        result = evaluate("evm", evm_ok_record(), pool(), SEC)
        self.assertEqual(result.status, "ok", [(c.name, c.status, c.detail) for c in result.checks])
        self.assertAlmostEqual(result.top10_pct, 20.0)

    def test_individual_failures(self) -> None:
        cases = {
            "honeypot": evm_ok_record(is_honeypot="1"),
            "taxas": evm_ok_record(buy_tax="0.06"),
            "open_source": evm_ok_record(is_open_source="0"),
            "lp": evm_ok_record(lp_holders=[{"address": "0xdev", "percent": "1", "is_locked": 0}]),
            "top10": evm_ok_record(holders=[{"address": "0xw", "tag": "", "percent": "0.4", "is_locked": 0}]),
            "flag:hidden_owner": evm_ok_record(hidden_owner="1"),
            "flag:cannot_sell_all": evm_ok_record(cannot_sell_all="1"),
        }
        for expected, record in cases.items():
            with self.subTest(expected):
                result = evaluate("evm", record, pool(), SEC)
                self.assertEqual(result.status, "falhou")
                self.assertIn(expected, [c.name for c in result.failures()])

    def test_tax_exactly_at_limit_passes(self) -> None:
        self.assertEqual(evaluate("evm", evm_ok_record(buy_tax="0.05", sell_tax="0.05"), pool(), SEC).status, "ok")

    def test_top10_ignores_pool_pair_and_burn(self) -> None:
        holders = [
            {"address": "0xpool", "tag": "", "percent": "0.60", "is_locked": 0},          # o proprio pool
            {"address": "0xpair", "tag": "", "percent": "0.20", "is_locked": 0},          # par da dex
            {"address": "0x" + "0" * 40, "tag": "Null Address", "percent": "0.05", "is_locked": 1},
            {"address": "0xrouter", "tag": "PancakeSwap Router", "percent": "0.10", "is_locked": 0},
            {"address": "0xa", "tag": "", "percent": "0.03", "is_locked": 0},
            {"address": "0xb", "tag": "", "percent": "0.02", "is_locked": 0},
        ]
        result = evaluate("evm", evm_ok_record(holders=holders), pool(), SEC)
        self.assertEqual(result.status, "ok")
        self.assertAlmostEqual(result.top10_pct, 5.0)

    def test_stale_holder_list_is_no_data_not_a_great_top10(self) -> None:
        stale = evm_ok_record(holder_count="1", holders=[{"address": "0x" + "0" * 40, "tag": "Null Address", "percent": "0.0000002", "is_locked": 1}])
        result = evaluate("evm", stale, pool(), SEC)
        top10 = next(c for c in result.checks if c.name == "top10")
        self.assertEqual(top10.status, "nodata")
        self.assertEqual(result.status, "parcial")
        self.assertIsNone(result.top10_pct)

    def test_owner_and_mintable_options(self) -> None:
        sec = copy.deepcopy(SEC)
        record = evm_ok_record(owner_address="0xowner", is_mintable="1")
        warn = evaluate("evm", record, pool(), sec)
        self.assertEqual(warn.status, "ok")
        self.assertIn("owner ativo", warn.warnings)
        self.assertIn("mintavel", warn.warnings)
        sec["evm"]["exigir_owner_renunciado"] = True
        sec["evm"]["bloquear_mintable"] = True
        strict = evaluate("evm", record, pool(), sec)
        self.assertEqual({c.name for c in strict.failures()}, {"owner", "mintable"})

    def test_lp_check_skipped_on_non_v2_dex(self) -> None:
        record = evm_ok_record(lp_holders=[])
        result = evaluate("evm", record, pool(dex="uniswap-v4-bsc"), SEC)
        self.assertEqual(next(c for c in result.checks if c.name == "lp").status, "na")
        self.assertEqual(result.status, "ok")

    def test_solana_ok_fail_and_gt_fallback(self) -> None:
        sol = pool(chain="solana", dex="pump-fun")
        self.assertEqual(evaluate("solana", solana_ok_record(), sol, SEC).status, "ok")
        self.assertEqual(evaluate("solana", solana_ok_record(freezable={"status": "1"}), sol, SEC).status, "falhou")
        info_ok = parse_token_info(load_fixture("gt_token_info_solana.json"))  # mint/freeze = no/no
        via_gt = evaluate("solana", None, sol, SEC, token_info=info_ok)
        self.assertEqual(via_gt.status, "ok")
        self.assertIn("GeckoTerminal", via_gt.note)
        info_bad = copy.deepcopy(info_ok)
        info_bad.mint_authority = "yes"
        self.assertEqual(evaluate("solana", solana_ok_record(), sol, SEC, token_info=info_bad).status, "falhou")  # qualquer fonte reprova
        sec = copy.deepcopy(SEC)
        sec["solana"]["usar_gt_para_mint_freeze"] = False
        self.assertEqual(evaluate("solana", None, sol, sec, token_info=info_ok).status, "sem_dado")
        self.assertEqual(evaluate("solana", None, sol, SEC).status, "sem_dado")

    def test_solana_extra_flags_fail(self) -> None:
        sol = pool(chain="solana", dex="pump-fun")
        for override in (
            {"closable": {"status": "1"}}, {"non_transferable": "1"}, {"default_account_state": "2"},
            {"transfer_hook": [{"program": "x"}]}, {"transfer_fee": {"current": 5}},
        ):
            with self.subTest(override):
                self.assertEqual(evaluate("solana", solana_ok_record(**override), sol, SEC).status, "falhou")

    def test_real_solana_record(self) -> None:
        data = load_fixture("goplus_sol_ok.json")
        mint = "8qX8SWNaHAjAcDxypPAuvvadw3GW4myQKNJoEK3AEnPX"
        rec = parse_security_response(data, "solana", [mint])[mint]
        self.assertEqual(evaluate("solana", rec, pool(chain="solana", dex="pump-fun"), SEC).status, "ok")

    def test_api_error_note_when_no_record(self) -> None:
        result = evaluate("evm", None, pool(), SEC, goplus_error=ApiError("timeout"))
        self.assertEqual(result.status, "sem_dado")
        self.assertEqual(result.note, "goplus_erro:timeout")

    def test_serialization_roundtrip(self) -> None:
        from ..security import SecurityResult

        result = evaluate("evm", evm_ok_record(), pool(), SEC)
        again = SecurityResult.from_dict(result.to_dict())
        self.assertEqual((again.status, again.top10_pct), (result.status, result.top10_pct))


class NarrativeTest(unittest.TestCase):
    def test_normalization_splits_camel_case_and_strips_accents(self) -> None:
        self.assertEqual(normalize_words("DogeAI Agent"), ["doge", "ai", "agent"])
        self.assertEqual(normalize_words("Gatinho Pretão"), ["gatinho", "pretao"])
        self.assertEqual(normalize_words("买买买 $PEPE"), ["买买买", "pepe"])

    def test_meta_parsing_and_version_ignores_comments_and_order(self) -> None:
        a = parse_meta("# dia 1\nIA: ai, agent\nGATO: cat\n")
        b = parse_meta("GATO: CAT\n\n# outro comentario\nIA: agent, AI\n")
        c = parse_meta("IA: ai, agent, gpt\nGATO: cat\n")
        self.assertEqual(a.version, b.version)
        self.assertNotEqual(a.version, c.version)
        self.assertEqual(parse_meta("trump\n").groups, {"TRUMP": (("trump",),)})
        self.assertTrue(parse_meta("# so comentario\n").empty)
        self.assertEqual(EMPTY_META.version, "vazio")

    def test_matching_rules(self) -> None:
        meta = parse_meta("IA: ai, agent, gpt\nGATO: cat, kitty\nCJK: 买\nFRASE: good boy\n")
        cases = [
            ("KittyAI", "", ["GATO", "IA"]),            # camelCase separa kitty + ai
            ("PAINT", "", []),                          # 'ai' curto so casa palavra inteira
            ("AIAgent", "", ["IA"]),                    # 'agent' (>=4 letras) casa dentro da palavra
            ("Bolsa", "fala de um gato esperto", []),   # 'gato' nao esta no meta
            ("Cool", "a smart kitty", ["GATO"]),        # so na descricao
            ("买买买", "", ["CJK"]),
            ("Good Boy Coin", "", ["FRASE"]),
            ("Boy Good", "", []),                       # ordem importa para expressoes
        ]
        for name, desc, expected in cases:
            with self.subTest(name):
                self.assertEqual(sorted(match_meta(meta, name, name, desc, 4).labels), sorted(expected))

    def test_name_vs_description_hits_are_separated(self) -> None:
        meta = parse_meta("IA: ai\nGATO: kitty\n")
        match = match_meta(meta, "Kitty", "KIT", "the best ai", 4)
        self.assertEqual([h[0] for h in match.name_hits], ["GATO"])
        self.assertEqual([h[0] for h in match.desc_hits], ["IA"])
        self.assertTrue(match.description_known)
        self.assertFalse(match_meta(meta, "Kitty", "KIT", "", 4).description_known)


class MetricsAndTriggersTest(unittest.TestCase):
    def test_acceleration_definition(self) -> None:
        self.assertIsNone(acceleration(1000, 1000, 120))            # < 5 min: sem base
        self.assertAlmostEqual(acceleration(1000, 1000, 480), 1.6)  # tudo no ultimo m5 de um pool de 8 min
        self.assertAlmostEqual(acceleration(1000, 12000, 7200), 1.0)  # ritmo igual ao da ultima hora
        self.assertIsNone(acceleration(1000, 0, 600))
        self.assertIsNone(acceleration(None, 1000, 600))

    def test_metrics_values_and_missing_data(self) -> None:
        metrics = compute_metrics(pool(), 100.0)
        self.assertAlmostEqual(metrics.pos_pct_liq, 100 * 100 / 30000)
        self.assertEqual((metrics.buys, metrics.sells, metrics.tx_total), (40, 15, 55))
        self.assertAlmostEqual(metrics.ticket_medio, 5000 / 55)
        empty = compute_metrics(pool(liq_usd=None, vol={}, tx={}), 100.0)
        self.assertIsNone(empty.pos_pct_liq)
        self.assertIsNone(empty.vol_m5)
        self.assertIsNone(empty.buys)

    def test_novo_gates_in_order(self) -> None:
        rules, filtros = CFG["gatilhos"]["novo"], CFG["filtros"]
        self.assertTrue(check_novo(pool(), filtros, rules, 3000).fired)
        young_but_old = check_novo(pool(created_ts=NOW - 700), filtros, rules, 3000)
        self.assertFalse(young_but_old.fired)
        low_liq = check_novo(pool(liq_usd=1000.0), filtros, rules, 3000)
        self.assertEqual(low_liq.etapa, "liquidez_minima")
        weak = check_novo(pool(vol={"m5": 100.0}), filtros, rules, 3000)
        self.assertEqual(weak.etapa, "gatilho")
        self.assertIn("vol_m5", weak.reason_text)
        self.assertEqual(check_novo(pool(price_usd=None), filtros, rules, 3000).etapa, "filtro")
        self.assertEqual(check_novo(pool(fdv_usd=2e11), filtros, rules, 3000).etapa, "filtro")  # MC absurdo
        self.assertEqual(check_novo(pool(both_reference=True), filtros, rules, 3000).etapa, "filtro")

    def test_unknown_liquidity_is_not_cut(self) -> None:
        rules, filtros = CFG["gatilhos"]["novo"], CFG["filtros"]
        self.assertTrue(check_novo(pool(liq_usd=None, liq_unreliable=True), filtros, rules, 3000).fired)

    def test_sobrevivente_window_price_and_initial_price_reliability(self) -> None:
        rules, filtros = CFG["gatilhos"]["sobrevivente20"], CFG["filtros"]
        base = dict(created_ts=NOW - 22 * 60, price_usd=0.5e-5, vol={"m5": 3000.0}, tx={"m5": WindowTx(15, 5, 12, 4)})
        ok = check_sobrevivente20(pool(**base), filtros, rules, 3000, first_price=1e-5, first_seen_age_s=30)
        self.assertTrue(ok.fired, ok.reason_text)
        self.assertFalse(check_sobrevivente20(pool(**base), filtros, rules, 3000, 2e-5, 30).fired)        # 25% do inicial
        self.assertFalse(check_sobrevivente20(pool(**base), filtros, rules, 3000, 1e-5, 600).fired)       # pool visto tarde demais
        self.assertFalse(check_sobrevivente20(pool(**base), filtros, rules, 3000, None, None).fired)
        self.assertFalse(check_sobrevivente20(pool(**{**base, "created_ts": NOW - 5 * 60}), filtros, rules, 3000, 1e-5, 30).fired)
        no_buys = check_sobrevivente20(pool(**{**base, "tx": {"m5": WindowTx(1, 5, 1, 4)}}), filtros, rules, 3000, 1e-5, 30)
        self.assertFalse(no_buys.fired)


class ScoringTest(unittest.TestCase):
    SC = CFG["score"]

    def score(self, snap: PoolSnap, labels: str = "", security: str = "ok", top10=None):
        meta = parse_meta("IA: ai, agent\nGATO: kitty\n")
        match = match_meta(meta, labels, labels, "", 4)
        return score_token(compute_metrics(snap, 100.0), match, top10, security, self.SC, CFG["seguranca"]["top10_max_pct"])

    def test_bounds_and_weights(self) -> None:
        strong = self.score(pool(vol={"m5": 50000.0, "h1": 60000.0}, tx={"m5": WindowTx(200, 40, 80, 20)}, liq_usd=200000.0,
                                 created_ts=NOW - 1800), "KittyAI", top10=5.0)
        self.assertLessEqual(strong.total, 100.0)
        self.assertGreater(strong.total, 80.0)
        self.assertEqual(strong.narrativa, 25.0)  # 2 matches x 15 -> teto 25
        nothing = self.score(pool(vol={"m5": 0.0, "h1": 0.0}, tx={"m5": WindowTx(0, 0, 0, 0)}, liq_usd=None), security="sem_dado")
        self.assertEqual(nothing.total, 0.0)

    def test_missing_data_gives_zero_points_and_flags_not_guesses(self) -> None:
        result = self.score(pool(), top10=None)
        self.assertIn("top10 s/d", result.flags)
        self.assertEqual(result.parts["top10"], 0.0)
        young = self.score(pool(created_ts=NOW - 100))
        self.assertIn("acel s/d", young.flags)
        self.assertAlmostEqual(young.parts["acel"], self.SC["fluxo"]["pontos_aceleracao"] * self.SC["fluxo"]["acel_sem_base_fracao"])
        unknown_liq = self.score(pool(liq_usd=None, liq_unreliable=True))
        self.assertIn("liq desconhecida", unknown_liq.flags)
        self.assertEqual(unknown_liq.liquidez, 0.0)

    def test_security_status_costs_points(self) -> None:
        ok = self.score(pool(), security="ok").total
        partial = self.score(pool(), security="parcial").total
        unknown = self.score(pool(), security="sem_dado").total
        self.assertGreater(ok, partial)
        self.assertGreater(partial, unknown)
        self.assertAlmostEqual(ok - unknown, self.SC["penalidades"]["pen_seguranca_sem_dado"], places=1)

    def test_suspicious_volume_penalties(self) -> None:
        wash = pool(tx={"m5": WindowTx(812, 815, 195, 198)}, vol={"m5": 17000.0, "h1": 17000.0})  # caso real: ~8 tx por carteira
        result = self.score(wash)
        self.assertIn("poucas carteiras girando", result.flags)
        honeypot_like = self.score(pool(tx={"m5": WindowTx(30, 0, 25, 0)}))
        self.assertIn("sem vendas", honeypot_like.flags)
        dust = self.score(pool(vol={"m5": 30.0, "h1": 30.0}, tx={"m5": WindowTx(40, 20, 30, 10)}))
        self.assertIn("ticket minusculo", dust.flags)
        capped = self.score(pool(tx={"m5": WindowTx(80, 0, 5, 0)}, vol={"m5": 100.0, "h1": 100.0}, liq_usd=500.0))
        self.assertGreaterEqual(capped.parts["pen_volume_suspeito"], -self.SC["penalidades"]["volume_suspeito_max"])

    def test_low_liquidity_penalty_is_linear(self) -> None:
        liq_cfg = self.SC["penalidades"]
        half = self.score(pool(liq_usd=liq_cfg["liq_baixa_usd"] / 2))
        self.assertAlmostEqual(half.parts["pen_liquidez_baixa"], -liq_cfg["pen_liq_baixa_max"] / 2, places=2)

    def test_components_text_format(self) -> None:
        text = self.score(pool()).components_text
        self.assertRegex(text, r"^narr=[\d.]+;fluxo=[\d.]+;dist=[\d.]+;liq=[\d.]+;pen=-?[\d.]+$")


if __name__ == "__main__":
    unittest.main()
