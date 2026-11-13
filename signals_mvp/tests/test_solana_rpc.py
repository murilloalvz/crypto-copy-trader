"""SolanaRpc: rodizio de endpoint, erro de transporte e a pausa longa do limite DIARIO do plano (QuickNode
"daily request limit reached" etc, decisao operacional de 2026-10-16) -- sem rede real (callable `post`)."""

from __future__ import annotations

import unittest

import requests

from ..pos_runner.solana_rpc import (
    CLASSE_AUTENTICACAO,
    CLASSE_CONEXAO,
    CLASSE_GENERICO,
    CLASSE_MUITAS_CONTAS,
    CLASSE_RATE_LIMIT,
    CONEXAO_FALHAS_PARA_MARCAR,
    DAILY_LIMIT_CODE,
    DAILY_LIMIT_PAUSE_S,
    RpcError,
    SolanaRpc,
    classificar_erro,
)

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


class CircuitBreakerTests(unittest.TestCase):
    """BUG PRIORITARIO (2026-10-22): antes, cada tentativa de `call_raw` podia esperar até 300s fixos no
    limitador local (`max_wait_s`), e com `max_attempts` tentativas isso deixava uma Única chamada de RPC
    -- `SolanaAdapter.holders()`, que roda no ciclo PRINCIPAL, nunca numa thread separada -- bloqueada por
    minutos (o suficiente pra disparar o watchdog de stall). Agora cada tentativa tem um teto bem menor
    (`max_wait_s`, padrão 20s) e a chamada INTEIRA desiste após `max_total_wait_s` de parede (padrão 30s),
    mesmo com tentativas de sobra."""

    def test_call_raw_gives_up_on_the_wall_clock_budget_before_exhausting_every_attempt(self) -> None:
        calls = {"n": 0}

        def post(url, payload):
            calls["n"] += 1
            return {"error": {"code": 429, "message": "slow down"}}   # 429 pra sempre: nunca se recupera

        clock = FakeClock()
        rpc = SolanaRpc([QN], per_min=600, clock=clock, sleep=clock.advance, post=post,
                        max_attempts=20, max_wait_s=20.0, max_total_wait_s=30.0)
        with self.assertRaises(RpcError) as ctx:
            rpc.call_raw("getSlot", [])
        self.assertEqual(ctx.exception.kind, "exhausted")
        self.assertLess(calls["n"], 20, "tinha que desistir pelo teto de parede, nao por esgotar as tentativas")
        self.assertLess(clock.t, 60.0, f"tempo simulado nao pode disparar muito alem do teto (30s), ficou em {clock.t}")

    def test_default_max_wait_s_is_small_not_the_old_300s(self) -> None:
        rpc = SolanaRpc([QN])
        self.assertLessEqual(rpc.max_wait_s, 30.0)
        self.assertLessEqual(rpc.max_total_wait_s, 60.0)

    def test_slow_call_logs_a_warning(self) -> None:
        calls = {"n": 0}

        def post(url, payload):
            calls["n"] += 1
            clock.advance(25.0)   # mais que SLOW_CALL_WARN_S (20s)
            return {"result": "ok"}

        clock = FakeClock()
        rpc = SolanaRpc([QN], per_min=600, clock=clock, sleep=clock.advance, post=post)
        with self.assertLogs("signals_mvp.pos_runner.rpc", level="WARNING") as ctx:
            self.assertEqual(rpc.call("getSlot", []), "ok")
        self.assertTrue(any("lenta" in msg for msg in ctx.output))


class ClassificarErroTests(unittest.TestCase):
    """HANDOFF 2026-11-12/13: classificacao da causa REAL de uma falha de RPC -- nunca mais tudo
    virando "RateLimited" no log/instrumentacao (achado real na VM: QuickNode morto por TLS ficou
    2 dias rotulado assim, mascarando a causa real)."""

    def test_connection_error_antes_de_qualquer_resposta_e_classe_conexao(self) -> None:
        exc = requests.exceptions.SSLError("HTTPSConnectionPool(...): Max retries exceeded")
        self.assertEqual(classificar_erro(exc), CLASSE_CONEXAO)

    def test_timeout_tambem_e_classe_conexao(self) -> None:
        self.assertEqual(classificar_erro(requests.exceptions.ConnectTimeout("timeout")), CLASSE_CONEXAO)

    def test_http_401_e_classe_autenticacao(self) -> None:
        self.assertEqual(classificar_erro(RpcError("transport", "HTTP 401", 401)), CLASSE_AUTENTICACAO)

    def test_http_403_e_classe_autenticacao(self) -> None:
        self.assertEqual(classificar_erro(RpcError("transport", "HTTP 403", 403)), CLASSE_AUTENTICACAO)

    def test_429_real_e_classe_rate_limit(self) -> None:
        self.assertEqual(classificar_erro(RpcError("transport", "HTTP 429", 429)), CLASSE_RATE_LIMIT)

    def test_limite_diario_e_classe_rate_limit(self) -> None:
        self.assertEqual(classificar_erro(RpcError("transport", "limite diario", DAILY_LIMIT_CODE)),
                         CLASSE_RATE_LIMIT)

    def test_too_many_accounts_e_classe_muitas_contas(self) -> None:
        exc = RpcError("app", "getTokenLargestAccounts: Too many accounts requested")
        self.assertEqual(classificar_erro(exc), CLASSE_MUITAS_CONTAS)

    def test_erro_de_app_desconhecido_e_classe_generico(self) -> None:
        self.assertEqual(classificar_erro(RpcError("app", "algo inesperado")), CLASSE_GENERICO)


class FalhaDeConexaoTests(unittest.TestCase):
    """HANDOFF 2026-11-12/13: falha de CONEXAO (TLS/DNS/timeout) nunca pode virar "RateLimited" no
    log final, nunca pode gastar `max_attempts` tentativas full no MESMO endpoint morto, e nunca
    pode deixar a URL/api-key (que vem embutida na str() da excecao real do requests, ex.: "Max
    retries exceeded with url: /?api-key=SEGREDO123") escapar pro log ou pro RpcError final."""

    SEGREDO = "api-key=SEGREDO123"

    def _post_morto(self, url, payload):
        raise requests.exceptions.ConnectionError(
            f"HTTPSConnectionPool(host='rpc.helius.xyz', port=443): Max retries exceeded with "
            f"url: /?{self.SEGREDO} (Caused by SSLError(...))")

    def test_classe_final_e_conexao_nunca_rate_limit(self) -> None:
        clock = FakeClock()
        rpc = SolanaRpc([QN], per_min=600, clock=clock, sleep=clock.advance, post=self._post_morto,
                        max_attempts=6, max_total_wait_s=30.0)
        with self.assertRaises(RpcError) as ctx:
            rpc.call_raw("getTokenLargestAccounts", ["mint"])
        self.assertEqual(ctx.exception.classe, CLASSE_CONEXAO)
        self.assertNotEqual(ctx.exception.classe, CLASSE_RATE_LIMIT)

    def test_endpoint_marcado_inalcancavel_apos_poucas_falhas_de_conexao(self) -> None:
        # 1 endpoint so (caso real do handoff: QuickNode era o UNICO POS_RUNNER_RPC_URLS) -- as
        # `max_attempts` tentativas repetem o MESMO endpoint morto ate `CONEXAO_FALHAS_PARA_MARCAR`.
        clock = FakeClock()
        rpc = SolanaRpc([QN], per_min=600, clock=clock, sleep=clock.advance, post=self._post_morto,
                        max_attempts=6, max_total_wait_s=30.0)
        with self.assertRaises(RpcError):
            rpc.call_raw("getTokenLargestAccounts", ["mint"])
        self.assertIn(QN, rpc.unreachable, "depois de >=CONEXAO_FALHAS_PARA_MARCAR falhas no MESMO "
                                           "endpoint, ele tem que sair do rodizio (nunca mais de "
                                           f"{CONEXAO_FALHAS_PARA_MARCAR} tentativas full nele)")

    def test_segredo_da_url_nunca_aparece_no_log_nem_na_excecao_final(self) -> None:
        clock = FakeClock()
        rpc = SolanaRpc([QN], per_min=600, clock=clock, sleep=clock.advance, post=self._post_morto,
                        max_attempts=4, max_total_wait_s=30.0)
        with self.assertLogs("signals_mvp.pos_runner.rpc", level="DEBUG") as ctx:
            with self.assertRaises(RpcError) as exc_ctx:
                rpc.call_raw("getTokenLargestAccounts", ["mint"])
        self.assertNotIn(self.SEGREDO, str(exc_ctx.exception))
        for linha in ctx.output:
            self.assertNotIn(self.SEGREDO, linha)


if __name__ == "__main__":
    unittest.main()
