"""SolanaRpc: rodizio de endpoint, erro de transporte e a pausa longa do limite DIARIO do plano (QuickNode
"daily request limit reached" etc, decisao operacional de 2026-10-16) -- sem rede real (callable `post`)."""

from __future__ import annotations

import unittest

from ..pos_runner.solana_rpc import DAILY_LIMIT_CODE, DAILY_LIMIT_PAUSE_S, RpcError, SolanaRpc

QN = "https://quicknode.example/chave/"
PUBLIC = "https://api.mainnet-beta.solana.com"


class FakeClock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def no_sleep(_: float) -> None:
    return None


class DailyLimitTests(unittest.TestCase):
    def test_daily_limit_excludes_the_endpoint_without_wasting_every_attempt_on_it(self):
        """Uma vez que a QuickNode bate o limite diario, as chamadas seguintes vao DIRETO pro RPC publico --
        nao gastam metade das tentativas rodiziando pra um endpoint que ja se sabe fora do ar."""
        calls: list[str] = []

        def post(url, payload):
            calls.append(url)
            if url == QN:
                return {"error": {"code": DAILY_LIMIT_CODE, "message": "daily request limit reached"}}
            return {"result": 123}

        clock = FakeClock()
        rpc = SolanaRpc([QN, PUBLIC], per_min=600, clock=clock, sleep=no_sleep, post=post)
        self.assertEqual(rpc.call("getSlot", []), 123)
        self.assertIn(QN, calls)       # tentou a QuickNode uma vez e aprendeu que esta no limite
        self.assertIn(PUBLIC, calls)
        calls.clear()
        # 2a chamada: nem tenta mais a QuickNode (ja sabe que esta pausada) -- vai direto pro publico
        self.assertEqual(rpc.call("getSlot", []), 123)
        self.assertEqual(calls, [PUBLIC])
        self.assertIn(QN, rpc.daily_limited)

    def test_daily_limit_via_http_429_with_json_body_is_recognized_the_same_way(self):
        """O caso real (QuickNode devolve HTTP 429 com o corpo JSON do erro -32003), nao so o corpo direto."""

        class FakeResponse:
            def __init__(self, status: int, body: dict):
                self.status_code = status
                self._body = body

            def json(self):
                return self._body

        def post(url, payload):
            raise AssertionError("este teste usa o caminho _send via requests, nao o post injetado")

        rpc = SolanaRpc([QN, PUBLIC], per_min=600, clock=FakeClock(), sleep=no_sleep)
        rpc.session = type("S", (), {"post": lambda self, url, json, timeout: (
            FakeResponse(429, {"error": {"code": DAILY_LIMIT_CODE, "message": "daily request limit reached"}})
            if url == QN else FakeResponse(200, {"result": 7})
        )})()
        self.assertEqual(rpc.call("getSlot", []), 7)
        self.assertIn(QN, rpc.daily_limited)

    def test_endpoint_recovers_automatically_after_the_pause_expires(self):
        """Depois da pausa, a QuickNode volta a ser tentada sozinha (sem o operador precisar religar nada)."""
        quicknode_ok = False

        def post(url, payload):
            if url == QN and not quicknode_ok:
                return {"error": {"code": DAILY_LIMIT_CODE, "message": "daily request limit reached"}}
            return {"result": "qn" if url == QN else "public"}

        clock = FakeClock()
        rpc = SolanaRpc([QN, PUBLIC], per_min=600, clock=clock, sleep=no_sleep, post=post)
        rpc.call("getSlot", [])                       # QN pausada agora
        self.assertIn(QN, rpc.daily_limited)
        quicknode_ok = True                           # o provedor "resetou" o limite
        clock.advance(DAILY_LIMIT_PAUSE_S - 1.0)
        calls: list[str] = []
        orig_post = rpc._post
        rpc._post = lambda url, payload: (calls.append(url), orig_post(url, payload))[1]
        rpc.call("getSlot", [])
        self.assertNotIn(QN, calls)                   # ainda dentro da pausa: nao tenta
        clock.advance(2.0)                            # passou da pausa
        calls.clear()
        self.assertEqual(rpc.call("getSlot", []), "qn")
        self.assertIn(QN, calls)                      # sondou de novo e funcionou -- volta ao rodizio normal

    def test_a_transient_429_without_the_daily_limit_code_keeps_retrying_normally(self):
        """Regressao: um 429 comum (sem o codigo do limite diario) continua se recuperando pela AIMD normal,
        nunca pausa o endpoint por 1h a toa."""
        attempts = {"n": 0}

        def post(url, payload):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return {"error": {"code": 429, "message": "slow down"}}
            return {"result": "ok"}

        clock = FakeClock()
        rpc = SolanaRpc([QN], per_min=600, clock=clock, sleep=clock.advance, post=post)
        self.assertEqual(rpc.call("getSlot", []), "ok")
        self.assertEqual(rpc.daily_limited, {})


if __name__ == "__main__":
    unittest.main()
