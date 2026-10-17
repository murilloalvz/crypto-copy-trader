"""Parsers do GeckoTerminal (respostas reais capturadas em 2026-10-13) + limitador/cliente HTTP."""

from __future__ import annotations

import copy
import unittest

import requests

from ..geckoterminal import GtClient, parse_network_ids, parse_ohlcv, parse_pools_response, parse_token_info, summarize_trades
from ..http import ApiError, CallBudget, HttpClient, RateLimited, RateLimiter
from ..models import ChainCtx
from ..util import parse_iso
from .fakes import FakeClock, FakeResponse, FakeSession, load_fixture

SOL_REF = frozenset({"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"})
BSC_REF = frozenset({"0x0000000000000000000000000000000000000000", "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c", "0x55d398326f99059ff775485246999027b3197955"})
SOL = ChainCtx("solana", "solana", "solana", SOL_REF, frozenset({"meteora-dbc"}))
BSC = ChainCtx("bsc", "evm", "bsc", BSC_REF)
NOW = parse_iso("2026-10-13T13:46:00Z")


class PoolParsingTest(unittest.TestCase):
    def test_solana_pools_real_shape(self) -> None:
        pools = {p.symbol: p for p in parse_pools_response(load_fixture("gt_new_pools_solana.json"), SOL, NOW)}
        burn = pools["BURN"]
        self.assertEqual(burn.token, "8qX8SWNaHAjAcDxypPAuvvadw3GW4myQKNJoEK3AEnPX")
        self.assertEqual(burn.dex, "pump-fun")
        self.assertEqual(burn.target_side, "base")
        self.assertIsNone(burn.mcap_usd)
        self.assertAlmostEqual(burn.mc_usd, burn.fdv_usd)  # MC cai para FDV quando o GT nao tem market cap
        self.assertGreater(burn.liq_usd, 3000)
        self.assertEqual((burn.window("m5").buys, burn.window("m5").sells, burn.window("m5").buyers), (9, 10, 9))
        self.assertAlmostEqual(burn.window("m5").buy_pct, 100 * 9 / 19)
        raw_item = next(p for p in load_fixture("gt_new_pools_solana.json")["data"] if p["attributes"]["address"] == burn.pool)
        self.assertEqual(burn.created_ts, parse_iso(raw_item["attributes"]["pool_created_at"]))

    def test_non_reference_quote_is_flagged(self) -> None:
        pools = {p.symbol: p for p in parse_pools_response(load_fixture("gt_new_pools_solana.json"), SOL, NOW)}
        self.assertTrue(pools["SPERPS"].other_is_reference)      # quote USDC
        self.assertFalse(pools["嘉年华S"].other_is_reference)      # quote ANTFUN (token meme)

    def test_evm_addresses_are_lowercased_and_native_quote_detected(self) -> None:
        pools = {p.symbol: p for p in parse_pools_response(load_fixture("gt_new_pools_bsc.json"), BSC, NOW)}
        feet = pools["feetcoin"]
        self.assertEqual(feet.token, feet.token.lower())
        self.assertTrue(feet.other_is_reference)  # BNB nativo 0x000...0
        self.assertEqual(feet.dex, "four-meme")

    def test_target_is_the_quote_token_when_base_is_a_reference_asset(self) -> None:
        data = copy.deepcopy(load_fixture("gt_new_pools_solana.json"))
        item = data["data"][0]
        rel = item["relationships"]
        rel["base_token"], rel["quote_token"] = rel["quote_token"], rel["base_token"]
        attrs = item["attributes"]
        attrs["base_token_price_usd"], attrs["quote_token_price_usd"] = attrs["quote_token_price_usd"], attrs["base_token_price_usd"]
        original_m5 = copy.deepcopy(attrs["transactions"]["m5"])
        pool = parse_pools_response(data, SOL, NOW)[0]
        self.assertEqual(pool.target_side, "quote")
        self.assertEqual(pool.symbol, "BURN")
        self.assertEqual(pool.price_usd, float(attrs["quote_token_price_usd"]))
        # compra do alvo = venda do lado base: contagens trocadas
        self.assertEqual((pool.window("m5").buys, pool.window("m5").sells), (original_m5["sells"], original_m5["buys"]))

    def test_pair_of_two_reference_assets(self) -> None:
        data = copy.deepcopy(load_fixture("gt_new_pools_solana.json"))
        ref = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"}
        item = next(p for p in data["data"] if p["attributes"]["name"] == "SPERPS / USDC")
        for i in data["included"]:
            if i["id"] == item["relationships"]["base_token"]["data"]["id"]:
                i["attributes"]["address"] = "So11111111111111111111111111111111111111112"
        pool = next(p for p in parse_pools_response(data, SOL, NOW) if p.pool == item["attributes"]["address"])
        self.assertTrue(pool.both_reference)
        _ = ref

    def test_zero_liquidity_on_curve_dex_is_unknown_not_zero(self) -> None:
        data = copy.deepcopy(load_fixture("gt_new_pools_solana.json"))
        item = next(p for p in data["data"] if p["relationships"]["dex"]["data"]["id"] == "meteora-dbc")
        item["attributes"]["reserve_in_usd"] = "0"
        pool = next(p for p in parse_pools_response(data, SOL, NOW) if p.pool == item["attributes"]["address"])
        self.assertIsNone(pool.liq_usd)
        self.assertTrue(pool.liq_unreliable)
        # numa DEX confiavel, liquidez 0 continua sendo 0 (cortada pelo minimo)
        item["relationships"]["dex"]["data"]["id"] = "raydium"
        pool = next(p for p in parse_pools_response(data, SOL, NOW) if p.pool == item["attributes"]["address"])
        self.assertEqual(pool.liq_usd, 0.0)

    def test_missing_fields_become_none_and_bad_items_are_skipped(self) -> None:
        data = {"data": [{"id": "solana_X", "attributes": {"address": "X"}, "relationships": {}}, "lixo"], "included": []}
        self.assertEqual(parse_pools_response(data, SOL, NOW), [])
        with self.assertRaises(ApiError):
            parse_pools_response({"foo": 1}, SOL, NOW)

    def test_multi_has_launchpad_details(self) -> None:
        pools = parse_pools_response(load_fixture("gt_multi_solana.json"), SOL, NOW)
        self.assertEqual({p.symbol for p in pools}, {"BURN", "买买买"})
        self.assertIsNotNone(pools[0].launchpad)


class OtherParsersTest(unittest.TestCase):
    def test_ohlcv_is_returned_in_ascending_order(self) -> None:
        candles = parse_ohlcv(load_fixture("gt_ohlcv_solana.json"))
        self.assertEqual(len(candles), 11)
        self.assertEqual([c.ts for c in candles], sorted(c.ts for c in candles))
        self.assertTrue(all(c.low <= c.open <= c.high and c.low <= c.close <= c.high for c in candles))

    def test_ohlcv_drops_invalid_rows(self) -> None:
        data = {"data": {"attributes": {"ohlcv_list": [[60, 1, 2, 0.5, 1.5, 10], [120, 0, 1, 1, 1, 1], [180, "x", 1, 1, 1, 1], [240, 1, 0.5, 2, 1, 1], [1]]}}}
        self.assertEqual([c.ts for c in parse_ohlcv(data)], [60.0])
        with self.assertRaises(ApiError):
            parse_ohlcv({"data": {}})

    def test_token_info(self) -> None:
        burn = parse_token_info(load_fixture("gt_token_info_solana.json"))
        self.assertEqual((burn.symbol, burn.mint_authority, burn.freeze_authority, burn.is_honeypot), ("BURN", "no", "no", "unknown"))
        self.assertIsNone(burn.top10_pct_gt)
        bonk = parse_token_info(load_fixture("gt_token_info_bonk.json"))
        self.assertEqual(bonk.top10_pct_gt, 38.3018)
        self.assertEqual(bonk.holders_count, 1024748)
        self.assertIn("dog-themed", bonk.description)

    def test_network_ids(self) -> None:
        self.assertEqual(parse_network_ids(load_fixture("gt_networks_p1_trim.json")), {"solana", "bsc", "eth"})
        self.assertEqual(parse_network_ids(load_fixture("gt_networks_p2_trim.json")), {"robinhood"})

    def test_trades_summary_orientation_and_window(self) -> None:
        data = load_fixture("gt_trades_solana.json")
        target = "2rbX6Z998s8zGKs34uCD57EKcyR29jABCycnoEPzmRet"
        newest = max(parse_iso(t["attributes"]["block_timestamp"]) for t in data["data"])
        summary = summarize_trades(data, target, "solana", newest, 300)
        self.assertEqual(summary.n_trades, 30)
        self.assertAlmostEqual(summary.buy_usd + summary.sell_usd, sum(float(t["attributes"]["volume_in_usd"]) for t in data["data"]), places=6)
        self.assertGreater(summary.buy_usd, 0)
        self.assertGreater(summary.sell_usd, 0)
        # token que nao participa das trades => nada contabilizado
        other = summarize_trades(data, "OutroTokenQualquer1111111111111111111111111", "solana", newest, 300)
        self.assertEqual(other.n_trades, 0)

    def test_trades_window_is_causal_and_flags_truncation(self) -> None:
        data = load_fixture("gt_trades_solana.json")
        target = "2rbX6Z998s8zGKs34uCD57EKcyR29jABCycnoEPzmRet"
        newest = max(parse_iso(t["attributes"]["block_timestamp"]) for t in data["data"])
        # decisao 60 s antes da trade mais nova: trades posteriores nao entram
        early = summarize_trades(data, target, "solana", newest - 60, 300)
        late = summarize_trades(data, target, "solana", newest, 300)
        self.assertLess(early.n_trades, late.n_trades)
        # lista cheia (300) cuja trade mais antiga e mais nova que a janela => janela incompleta
        many = {"data": [copy.deepcopy(data["data"][i % 30]) for i in range(300)]}
        stamp = parse_iso("2026-10-13T14:00:00Z")
        for i, trade in enumerate(many["data"]):
            from ..util import iso_utc

            trade["attributes"]["block_timestamp"] = iso_utc(stamp - i // 60)  # 300 trades em ~5 s
        summary = summarize_trades(many, target, "solana", stamp, 300)
        self.assertFalse(summary.complete)
        self.assertLess(summary.covered_s, 10)


class RateLimiterTest(unittest.TestCase):
    def make(self, per_min: float = 60, burst: int = 2, pause: float = 30, pause_max: float = 120):
        clock = FakeClock(1000.0)
        slept: list[float] = []

        def sleep(seconds: float) -> None:
            slept.append(seconds)
            clock.advance(seconds)

        return RateLimiter(per_min, burst, pause, pause_max, clock=clock, sleep=sleep), clock, slept

    def test_burst_then_paced(self) -> None:
        limiter, clock, slept = self.make(per_min=60, burst=2)
        limiter.acquire()
        limiter.acquire()
        self.assertEqual(slept, [])
        limiter.acquire()  # sem fichas: espera ~1 s (60/min)
        self.assertAlmostEqual(sum(slept), 1.0, places=3)

    def test_wait_longer_than_allowed_raises_budget_error_without_sleeping(self) -> None:
        limiter, clock, slept = self.make(per_min=6, burst=1)  # 1 ficha a cada 10 s
        limiter.acquire()
        with self.assertRaises(ApiError) as ctx:
            limiter.acquire(max_wait_s=2.0)
        self.assertEqual(ctx.exception.kind, "budget")
        self.assertEqual(slept, [])

    def test_429_pause_doubles_and_resets_on_success(self) -> None:
        limiter, clock, slept = self.make(pause=30, pause_max=100)
        self.assertEqual(limiter.on_429(), 30)
        self.assertEqual(limiter.on_429(), 60)
        self.assertEqual(limiter.on_429(), 100)  # teto
        with self.assertRaises(RateLimited):
            limiter.acquire()
        clock.advance(101)
        limiter.acquire()
        limiter.on_success()
        self.assertEqual(limiter.on_429(), 30)


class HttpClientTest(unittest.TestCase):
    def client(self, routes, **kw):
        limiter = RateLimiter(600, 10, pause_s=30, clock=FakeClock(0), sleep=lambda s: None)
        session = FakeSession(routes)
        return HttpClient("https://api.example/v2", limiter, session=session, name="X", **kw), session

    def test_ok_and_url_building(self) -> None:
        http, session = self.client([("/networks", FakeResponse(200, {"data": []}))])
        self.assertEqual(http.get_json("networks", {"page": 1}), {"data": []})
        self.assertEqual(session.calls[0], ("https://api.example/v2/networks", {"page": 1}))

    def test_status_mapping(self) -> None:
        cases = [
            (FakeResponse(429, {}), RateLimited),
            (FakeResponse(404, {}), ApiError),
            (FakeResponse(500, {}), ApiError),
            (FakeResponse(200, raw="<html>"), ApiError),
            (requests.Timeout("x"), ApiError),
            (requests.ConnectionError("tem a url secreta"), ApiError),
        ]
        expected_kind = ["rate_limited", "not_found", "http", "bad_json", "timeout", "network"]
        for (answer, exc_type), kind in zip(cases, expected_kind):
            with self.subTest(kind):
                http, _ = self.client([("/p", answer)])
                with self.assertRaises(exc_type) as ctx:
                    http.get_json("p")
                self.assertEqual(ctx.exception.kind, kind)
                self.assertNotIn("secreta", str(ctx.exception))  # mensagem original da lib nunca vaza

    def test_429_blocks_following_calls_until_pause_ends(self) -> None:
        http, _ = self.client([("/p", FakeResponse(429, {}))])
        with self.assertRaises(RateLimited):
            http.get_json("p")
        with self.assertRaises(RateLimited):  # segunda chamada nem sai: limitador em pausa
            http.get_json("p")
        self.assertEqual(http.calls, 1)


class ClockSkewTest(unittest.TestCase):
    def http(self, date_header):
        limiter = RateLimiter(6000, 100, clock=FakeClock(0), sleep=lambda s: None)
        session = FakeSession([("/x", FakeResponse(200, {}, headers={"Date": date_header} if date_header else {}))])
        return HttpClient("https://a.example", limiter, session=session, name="X")

    def test_skew_is_local_minus_server(self) -> None:
        import time
        from email.utils import formatdate

        http = self.http(formatdate(time.time() - 30, usegmt=True))  # servidor 30 s atras => PC adiantado
        self.assertIsNone(http.clock_skew_s())
        http.get_json("x")
        self.assertAlmostEqual(http.clock_skew_s(), 30.0, delta=2.5)

    def test_missing_or_garbage_header_is_ignored(self) -> None:
        http = self.http(None)
        http.get_json("x")
        self.assertIsNone(http.clock_skew_s())
        http = self.http("isto nao e uma data")
        http.get_json("x")
        self.assertIsNone(http.clock_skew_s())

    def test_warning_message_thresholds(self) -> None:
        from ..worker import clock_skew_message

        self.assertIsNone(clock_skew_message(None))
        self.assertIsNone(clock_skew_message(3.0))
        self.assertIsNone(clock_skew_message(-10.0))
        self.assertIn("ADIANTADO", clock_skew_message(45.0))
        self.assertIn("ATRASADO", clock_skew_message(-120.0))
        self.assertIn("latencia_s", clock_skew_message(45.0))


class GtClientTest(unittest.TestCase):
    def make(self, routes):
        limiter = RateLimiter(6000, 100, clock=FakeClock(0), sleep=lambda s: None)
        session = FakeSession(routes)
        http = HttpClient("https://api.geckoterminal.com/api/v2", limiter, session=session, name="GT")
        return GtClient(http, clock=lambda: NOW), session

    def test_new_pools_request_and_observed_clock(self) -> None:
        gt, session = self.make([("/new_pools", FakeResponse(200, load_fixture("gt_new_pools_bsc.json")))])
        pools = gt.new_pools(BSC, 2)
        self.assertEqual(len(pools), 5)
        self.assertTrue(all(p.observed_ts == NOW for p in pools))
        url, params = session.calls[0]
        self.assertTrue(url.endswith("/networks/bsc/new_pools"))
        self.assertEqual(params, {"page": 2, "include": "base_token,quote_token,dex"})

    def test_multi_is_capped_at_30(self) -> None:
        gt, session = self.make([("/pools/multi/", FakeResponse(200, {"data": [], "included": []}))])
        gt.pools_multi(BSC, [f"0x{i:040x}" for i in range(45)])
        self.assertEqual(session.calls[0][0].split("/multi/")[1].count(","), 29)
        self.assertEqual(gt.pools_multi(BSC, []), [])

    def test_ohlcv_params(self) -> None:
        gt, session = self.make([("/ohlcv/minute", FakeResponse(200, load_fixture("gt_ohlcv_solana.json")))])
        candles = gt.ohlcv(SOL, "POOL", "quote", 1791898600.0, 1791899300.0)
        self.assertGreater(len(candles), 0)
        params = session.calls[0][1]
        self.assertEqual((params["aggregate"], params["token"], params["currency"]), (1, "quote", "usd"))
        self.assertEqual(params["before_timestamp"], 1791899360)
        self.assertGreaterEqual(params["limit"], 12)

    def test_network_ids_stops_at_the_page_that_returns_400(self) -> None:
        def answer(url, params):
            page = params["page"]
            if page == 1:
                return FakeResponse(200, load_fixture("gt_networks_p1_trim.json"))
            if page == 2:
                return FakeResponse(200, load_fixture("gt_networks_p2_trim.json"))
            return FakeResponse(400, {"errors": []})

        gt, session = self.make([("/networks", answer)])
        self.assertEqual(gt.network_ids(), {"solana", "bsc", "eth", "robinhood"})
        self.assertEqual(len(session.calls), 3)


class CallBudgetTest(unittest.TestCase):
    def test_reserve_and_exhaust(self) -> None:
        budget = CallBudget(5)
        self.assertTrue(budget.take(2, keep=2))   # sobra 3 -> ok
        self.assertTrue(budget.take(1, keep=2))   # usa 3 de 5; ainda deixa 2
        self.assertFalse(budget.take(1, keep=2))  # a reserva e intocavel
        self.assertTrue(budget.take(2))           # quem nao reserva pode gastar a reserva
        self.assertEqual(budget.left(), 0)
        budget = CallBudget(5)
        budget.exhaust()
        self.assertFalse(budget.take())


if __name__ == "__main__":
    unittest.main()
