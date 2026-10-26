"""POS-RUNNER-V1 + DexPaprika (PEDIDO CONSOLIDADO, FASE 1): circuit breaker, orcamento de creditos,
atraso de seguranca, fallback (volume sempre zerado) e conferencia cruzada (so log). Sem rede."""

from __future__ import annotations

import unittest

from ..http import ApiError, RateLimited
from ..pos_runner.candles import Bar
from ..pos_runner.dexpaprika_v1 import CircuitBreaker, DexPaprikaProvider, comparar_candle
from .fakes import FakeClock


class _FakeDpHttp:
    """Duble minimo do DexPaprikaHttp: so o atributo `credits` que `orcamento_ok` le."""

    class _Credits:
        def __init__(self, limit=None, remaining=None):
            self.credits_limit = limit
            self.credits_remaining = remaining

    def __init__(self, limit=None, remaining=None):
        self.credits = self._Credits(limit, remaining)


class _FakeDpClient:
    """Duble do DexPaprikaClient: `respostas` e uma fila de (candles|Exception) consumida a cada chamada."""

    def __init__(self, respostas, credits_limit=None, credits_remaining=None):
        self.respostas = list(respostas)
        self.http = _FakeDpHttp(credits_limit, credits_remaining)
        self.chamadas: list[tuple] = []

    def ohlcv(self, network, pool, start_ts, end_ts, interval="1h", limit=1000):
        self.chamadas.append((network, pool, start_ts, end_ts, interval))
        item = self.respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _provider(respostas, **kwargs):
    client = _FakeDpClient(respostas, credits_limit=kwargs.pop("credits_limit", None),
                           credits_remaining=kwargs.pop("credits_remaining", None))
    clock = FakeClock(0)
    provider = DexPaprikaProvider(client, breaker=CircuitBreaker(limiar_falhas=kwargs.pop("limiar_falhas", 3),
                                                                 pausa_s=kwargs.pop("pausa_s", 300.0), clock=clock),
                                  clock=clock, **kwargs)
    return provider, client, clock


class CircuitBreakerTests(unittest.TestCase):
    def test_fecha_permite_chamadas(self) -> None:
        cb = CircuitBreaker(clock=FakeClock(0))
        self.assertTrue(cb.permitido())

    def test_abre_depois_do_limiar_de_falhas_seguidas(self) -> None:
        clock = FakeClock(0)
        cb = CircuitBreaker(limiar_falhas=3, pausa_s=60.0, clock=clock)
        cb.registrar_falha()
        cb.registrar_falha()
        self.assertTrue(cb.permitido())   # ainda nao chegou no limiar
        cb.registrar_falha()
        self.assertFalse(cb.permitido())  # 3a falha seguida: abre

    def test_fecha_de_novo_apos_a_pausa(self) -> None:
        clock = FakeClock(0)
        cb = CircuitBreaker(limiar_falhas=1, pausa_s=60.0, clock=clock)
        cb.registrar_falha()
        self.assertFalse(cb.permitido())
        clock.advance(60.0)
        self.assertTrue(cb.permitido())

    def test_sucesso_reseta_a_contagem_de_falhas(self) -> None:
        cb = CircuitBreaker(limiar_falhas=3, clock=FakeClock(0))
        cb.registrar_falha()
        cb.registrar_falha()
        cb.registrar_sucesso()
        cb.registrar_falha()
        cb.registrar_falha()
        self.assertTrue(cb.permitido())   # 2 falhas depois do reset: ainda nao abriu


class OrcamentoDeCreditosTests(unittest.TestCase):
    def test_sem_header_ainda_deixa_tentar(self) -> None:
        provider, _client, _clock = _provider([], credits_limit=None, credits_remaining=None)
        self.assertTrue(provider.orcamento_ok())

    def test_abaixo_do_teto_libera(self) -> None:
        provider, _client, _clock = _provider([], credits_limit=10_000, credits_remaining=3_000,
                                              creditos_teto_pct=0.8)
        self.assertTrue(provider.orcamento_ok())   # usado 70% < teto 80%

    def test_acima_do_teto_bloqueia(self) -> None:
        provider, _client, _clock = _provider([], credits_limit=10_000, credits_remaining=1_000,
                                              creditos_teto_pct=0.8)
        self.assertFalse(provider.orcamento_ok())   # usado 90% >= teto 80%


class AtrasoDeSegurancaTests(unittest.TestCase):
    def test_aceita_so_depois_do_atraso_minimo(self) -> None:
        provider, _client, _clock = _provider([], atraso_min_s=120.0)
        self.assertFalse(provider.aceitar_ts(candle_fecha_ts=1000.0, now=1100.0))   # 100s < 120s
        self.assertTrue(provider.aceitar_ts(candle_fecha_ts=1000.0, now=1120.0))    # 120s >= 120s


class CandlesFallbackTests(unittest.TestCase):
    def test_desabilitado_nunca_chama(self) -> None:
        provider, client, _clock = _provider([], habilitado=False)
        out = provider.candles_fallback("solana", "POOL1", "1h", 0.0, 10_000.0)
        self.assertEqual(out, [])
        self.assertEqual(client.chamadas, [])

    def test_tf_sem_interval_equivalente_nunca_chama(self) -> None:
        provider, client, _clock = _provider([])
        out = provider.candles_fallback("solana", "POOL1", "4h", 0.0, 10_000.0)
        self.assertEqual(out, [])
        self.assertEqual(client.chamadas, [])

    def test_volume_sempre_zerado_e_respeita_atraso(self) -> None:
        from ..models import Candle

        candles = [Candle(ts=0.0, open=1.0, high=1.1, low=0.9, close=1.05, volume=999.0),
                  Candle(ts=3600.0, open=1.05, high=1.2, low=1.0, close=1.1, volume=888.0)]
        provider, client, _clock = _provider([candles], atraso_min_s=120.0)
        # 1o candle fecha em 3600 (ts=0 + step 1h); so ele teve >= 120s de atraso em now=3720; o 2o fecha em
        # 7200, bem mais recente que o atraso minimo permite.
        bars = provider.candles_fallback("solana", "POOL1", "1h", since_ts=-1.0, now=3720.0)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].ts, 0.0)
        self.assertEqual(bars[0].volume, 0.0)   # NUNCA usa o volume do DexPaprika (unidade nao confirmada)

    def test_plan_limit_nunca_abre_o_circuit_breaker(self) -> None:
        provider, client, _clock = _provider([ApiError("plan_limit", "fora do plano", 403)] * 5, limiar_falhas=2)
        for _ in range(5):
            self.assertEqual(provider.candles_fallback("solana", "POOL1", "1h", 0.0, 10_000.0), [])
        self.assertTrue(provider.breaker.permitido())   # plan_limit nao conta como falha de disponibilidade

    def test_timeout_abre_o_circuit_breaker_apos_o_limiar(self) -> None:
        provider, client, _clock = _provider([ApiError("timeout", "sem resposta")] * 3, limiar_falhas=2)
        provider.candles_fallback("solana", "POOL1", "1h", 0.0, 10_000.0)
        self.assertTrue(provider.breaker.permitido())
        provider.candles_fallback("solana", "POOL1", "1h", 0.0, 10_000.0)
        self.assertFalse(provider.breaker.permitido())   # 2a falha seguida: abre
        # breaker aberto: a 3a tentativa nao gasta a resposta enfileirada (nem chama o cliente)
        self.assertEqual(provider.candles_fallback("solana", "POOL1", "1h", 0.0, 10_000.0), [])
        self.assertEqual(len(client.chamadas), 2)

    def test_429_conta_como_falha(self) -> None:
        provider, client, _clock = _provider([RateLimited(30.0)], limiar_falhas=1)
        out = provider.candles_fallback("solana", "POOL1", "1h", 0.0, 10_000.0)
        self.assertEqual(out, [])
        self.assertFalse(provider.breaker.permitido())


class ConferenciaCruzadaTests(unittest.TestCase):
    def test_amostragem_1_em_cada_n(self) -> None:
        provider, _client, _clock = _provider([], amostra_cada_n=3)
        resultados = [provider.deve_conferir() for _ in range(6)]
        self.assertEqual(resultados, [False, False, True, False, False, True])

    def test_compara_candle_so_reporta_alem_da_tolerancia(self) -> None:
        gt = Bar(ts=0, open=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0)

        class _Dp:
            open, high, low, close, volume = 100.5, 101.0, 99.0, 100.5, 1000.0

        divergencias = comparar_candle(gt, _Dp(), tolerancia_pct=1.0)
        self.assertEqual(divergencias, [])   # 0,5% de diferenca no open, dentro da tolerancia de 1%

        class _DpDivergente:
            open, high, low, close, volume = 110.0, 101.0, 99.0, 100.5, 1000.0

        divergencias = comparar_candle(gt, _DpDivergente(), tolerancia_pct=1.0)
        self.assertEqual(len(divergencias), 1)
        self.assertEqual(divergencias[0].campo, "open")

    def test_conferir_nunca_levanta_e_devolve_vazio_em_falha(self) -> None:
        provider, _client, _clock = _provider([ApiError("timeout", "sem resposta")])
        gt = Bar(ts=0, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)
        self.assertEqual(provider.conferir("solana", "POOL1", "1h", gt), [])

    def test_conferir_devolve_vazio_quando_desabilitado(self) -> None:
        provider, client, _clock = _provider([], habilitado=False)
        gt = Bar(ts=0, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)
        self.assertEqual(provider.conferir("solana", "POOL1", "1h", gt), [])
        self.assertEqual(client.chamadas, [])


if __name__ == "__main__":
    unittest.main()
