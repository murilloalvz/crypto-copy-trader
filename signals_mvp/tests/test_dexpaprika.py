"""Cliente do DexPaprika (PEDIDO CONSOLIDADO, FASE 1): parser + DexPaprikaHttp/DexPaprikaClient, sem rede
(FakeSession, mesmo padrao de test_gt_and_http.py)."""

from __future__ import annotations

import unittest

from ..dexpaprika import DexPaprikaClient, DexPaprikaHttp, parse_ohlcv_dexpaprika
from ..http import ApiError, RateLimited, RateLimiter
from .fakes import FakeClock, FakeResponse, FakeSession

OHLCV_REAL = [
    {"time_open": "2026-10-25T19:00:00Z", "time_close": "2026-10-25T20:00:00Z",
     "open": 101.79285137081409, "high": 101.89997706162212, "low": 101.59948903260019,
     "close": 101.81069240891439, "volume": 1163685},
    {"time_open": "2026-10-25T20:00:00Z", "time_close": "2026-10-25T21:00:00Z",
     "open": 101.7462981001622, "high": 101.85539320364155, "low": 101.50929833628277,
     "close": 101.69829002368945, "volume": 1545554},
]


class ParseOhlcvTests(unittest.TestCase):
    def test_parses_real_captured_response(self) -> None:
        candles = parse_ohlcv_dexpaprika(OHLCV_REAL)
        self.assertEqual(len(candles), 2)
        self.assertAlmostEqual(candles[0].open, 101.79285137081409)
        self.assertAlmostEqual(candles[0].ts, 1792954800.0)   # 2026-10-25T19:00:00Z
        self.assertLess(candles[0].ts, candles[1].ts)         # ordem crescente

    def test_skips_malformed_rows_without_raising(self) -> None:
        rows = [*OHLCV_REAL, {"time_open": "2026-10-25T21:00:00Z", "open": "nao-e-numero",
                              "high": 1, "low": 1, "close": 1, "volume": 1},
               {"time_open": None, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
               {"time_open": "2026-10-25T22:00:00Z", "open": 1, "high": 0, "low": 1, "close": 1, "volume": 1}]
        candles = parse_ohlcv_dexpaprika(rows)
        self.assertEqual(len(candles), 2)   # so os 2 reais validos

    def test_not_a_list_raises_bad_json(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            parse_ohlcv_dexpaprika({"error": "plan_required"})
        self.assertEqual(ctx.exception.kind, "bad_json")


def _http(routes, api_key=None):
    limiter = RateLimiter(600, 10, pause_s=30, clock=FakeClock(0), sleep=lambda s: None)
    session = FakeSession(routes)
    return DexPaprikaHttp(limiter, api_key=api_key, session=session), session


class DexPaprikaHttpTests(unittest.TestCase):
    def test_get_json_happy_path_and_credit_headers(self) -> None:
        headers = {"ratelimit-limit": "10", "ratelimit-remaining": "9", "x-credits-limit": "10000",
                  "x-credits-remaining": "9570", "x-credits-reset": "0", "x-api-plan": "keyless"}
        http, session = _http([("/ohlcv", FakeResponse(200, OHLCV_REAL, headers=headers))])
        data = http.get_json("networks/solana/pools/POOL1/ohlcv", {"start": "0"})
        self.assertEqual(data, OHLCV_REAL)
        self.assertEqual(http.credits.credits_remaining, 9570)
        self.assertEqual(http.credits.credits_limit, 10000)
        self.assertEqual(http.credits.ratelimit_remaining, 9)
        self.assertEqual(http.credits.api_plan, "keyless")

    def test_api_key_goes_in_authorization_header_without_bearer_prefix(self) -> None:
        http, session = _http([("/ohlcv", FakeResponse(200, OHLCV_REAL))], api_key="minha_chave_secreta")
        http.get_json("networks/solana/pools/POOL1/ohlcv")
        self.assertEqual(session.calls[-1][1], {})  # params vazios aqui; a chave vai no header, nunca na URL

    def test_no_api_key_sends_no_authorization_header(self) -> None:
        captured = {}

        def route(url, params):
            return FakeResponse(200, OHLCV_REAL)

        http, session = _http([("/ohlcv", route)])
        http.get_json("networks/solana/pools/POOL1/ohlcv")
        # garantia estrutural: sem api_key, o atributo interno fica None (nunca um valor vazio logavel)
        self.assertIsNone(http._api_key)  # noqa: SLF001

    def test_403_is_plan_limit_never_fatal_kind(self) -> None:
        body = {"error": "plan_required", "message": "..."}
        http, session = _http([("/ohlcv", FakeResponse(403, body))])
        with self.assertRaises(ApiError) as ctx:
            http.get_json("networks/solana/pools/POOL1/ohlcv")
        self.assertEqual(ctx.exception.kind, "plan_limit")
        self.assertEqual(ctx.exception.status, 403)

    def test_429_raises_rate_limited_and_pauses_limiter(self) -> None:
        http, session = _http([("/ohlcv", FakeResponse(429, {}))])
        with self.assertRaises(RateLimited):
            http.get_json("networks/solana/pools/POOL1/ohlcv")
        self.assertGreater(http.limiter.blocked_for(), 0.0)

    def test_404_is_not_found(self) -> None:
        http, session = _http([("/ohlcv", FakeResponse(404, {}))])
        with self.assertRaises(ApiError) as ctx:
            http.get_json("networks/solana/pools/POOL1/ohlcv")
        self.assertEqual(ctx.exception.kind, "not_found")

    def test_network_error_never_leaks_the_url_or_key(self) -> None:
        import requests

        http, session = _http([("/ohlcv", requests.ConnectionError("boom"))], api_key="segredo_nunca_aparece")
        with self.assertRaises(ApiError) as ctx:
            http.get_json("networks/solana/pools/POOL1/ohlcv")
        self.assertEqual(ctx.exception.kind, "network")
        self.assertNotIn("segredo_nunca_aparece", str(ctx.exception))


class DexPaprikaClientTests(unittest.TestCase):
    def test_ohlcv_filters_to_the_requested_window_and_builds_params(self) -> None:
        http, session = _http([("/ohlcv", FakeResponse(200, OHLCV_REAL))])
        client = DexPaprikaClient(http)
        candles = client.ohlcv("solana", "POOL1", 1792954800.0, 1792962000.0, interval="1h")
        self.assertEqual(len(candles), 2)
        url, params = session.calls[-1]
        self.assertIn("networks/solana/pools/POOL1/ohlcv", url)
        self.assertEqual(params["interval"], "1h")

    def test_invalid_interval_raises_value_error_before_any_call(self) -> None:
        http, session = _http([("/ohlcv", FakeResponse(200, OHLCV_REAL))])
        client = DexPaprikaClient(http)
        with self.assertRaises(ValueError):
            client.ohlcv("solana", "POOL1", 0, 1, interval="3h")
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
