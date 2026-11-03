"""PEDIDO 2026-11-03 (continuacao -- pendente 4): testes de `scripts/event_study.py` -- bootstrap
por token (funcoes puras, sem banco), pareamento sinal/controles e smoke test integrado."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.candles import Bar
from ..storage import Storage
from ..scripts import event_study


class BootstrapPorTokenTests(unittest.TestCase):
    def test_um_so_token_devolve_a_media_exata_sem_variancia(self) -> None:
        # So 1 token -- toda reamostragem (com reposicao) usa o MESMO conjunto de valores inteiro,
        # entao a media bootstrap e SEMPRE igual a media observada (zero variancia).
        media, limite, n_tokens = event_study._bootstrap_media_por_token({"CAT": [1.0, 2.0, 3.0]}, n_bootstrap=200)
        self.assertAlmostEqual(media, 2.0)
        self.assertAlmostEqual(limite, 2.0)
        self.assertEqual(n_tokens, 1)

    def test_tokens_vazios_devolve_zero_sem_crash(self) -> None:
        media, limite, n_tokens = event_study._bootstrap_media_por_token({})
        self.assertEqual((media, limite, n_tokens), (0.0, 0.0, 0))

    def test_dois_tokens_opostos_media_zero_mas_limite_inferior_reflete_o_risco(self) -> None:
        media, limite, n_tokens = event_study._bootstrap_media_por_token(
            {"CAT": [10.0], "DOG": [-10.0]}, n_bootstrap=5_000)
        self.assertAlmostEqual(media, 0.0)
        self.assertEqual(n_tokens, 2)
        self.assertLess(limite, 0.0)   # com so 2 tokens, o bloco "so DOG" pesa no limite inferior


class EfeitoPareadoPorHorizonteTests(unittest.TestCase):
    def test_efeito_e_sinal_menos_controle_agregado_por_token(self) -> None:
        resultados = [
            {"token": "CAT", "versao": "v1",
             "retorno_sinal": {1: 20.0, 6: None, 24: None, 72: None},
             "retorno_controles_medio": {1: 5.0, 6: None, 24: None, 72: None},
             "n_controles": {1: 3, 6: 0, 24: 0, 72: 0}},
            {"token": "DOG", "versao": "v1",
             "retorno_sinal": {1: 10.0, 6: None, 24: None, 72: None},
             "retorno_controles_medio": {1: 0.0, 6: None, 24: None, 72: None},
             "n_controles": {1: 2, 6: 0, 24: 0, 72: 0}},
        ]
        efeitos = event_study.efeito_pareado_por_horizonte(resultados)
        self.assertEqual(efeitos[1]["n_sinais"], 2)
        self.assertEqual(efeitos[1]["n_tokens"], 2)
        self.assertAlmostEqual(efeitos[1]["media"], 12.5)   # media((20-5), (10-0)) = media(15,10) = 12.5
        self.assertEqual(efeitos[6]["n_sinais"], 0)

    def test_sinal_sem_controle_valido_fica_fora_do_efeito(self) -> None:
        resultados = [{"token": "CAT", "versao": "v1",
                      "retorno_sinal": {1: 20.0, 6: None, 24: None, 72: None},
                      "retorno_controles_medio": {1: None, 6: None, 24: None, 72: None},
                      "n_controles": {1: 0, 6: 0, 24: 0, 72: 0}}]
        efeitos = event_study.efeito_pareado_por_horizonte(resultados)
        self.assertEqual(efeitos[1]["n_sinais"], 0)


class MedirSinalIntegradoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="event_study_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sinal_limpo_com_controles_elegiveis_gera_retorno_pareado(self) -> None:
        H = 3600
        bars_spec: list[Bar] = []
        # pico no candle 0 (1_000_000), 2 quedas >=80%/MC>=100k (candidatos a controle, idx 5 e 10),
        # entrada real no candle 21 (preco 200_000, dentro da janela de idade), sobe para 220_000 em
        # +1h (candle 22).
        for i in range(100):
            price = 1_000_000.0 if i == 0 else 200_000.0
            bars_spec.append(Bar(i * H, price, price, price, price, 1.0))
        bars_spec[5] = Bar(5 * H, 150_000.0, 150_000.0, 150_000.0, 150_000.0, 1.0)
        bars_spec[10] = Bar(10 * H, 120_000.0, 120_000.0, 120_000.0, 120_000.0, 1.0)
        # entrada no OPEN deste candle (200_000); +1h = o FECHAMENTO do MESMO candle (mesma aritmetica
        # de evidencia.calcular_trajetoria: offset=1 -> idx=entry_idx) -- fecha em 220_000 (+10%).
        bars_spec[21] = Bar(21 * H, 200_000.0, 220_000.0, 200_000.0, 220_000.0, 1.0)

        signal_id = self.storage.pr1_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 20 * H,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]",
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
            "entry_price": 200_000.0, "stop": 190_000.0, "reason": "stop", "closed_ts": 93 * H,
        })
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h", mint="MINT1", symbol="CAT",
            t_entrada=21 * H, preco_entrada=200_000.0, risco_pct=5.0, r_unidade=5.0, fonte_candle="gt",
        )
        self.storage.pr_upsert_pool("POOL1", status="ativo", info='{"criado_ts": 0}')
        self.storage.pr_append_bars("POOL1", "1h", [
            (b.ts, b.open, b.high, b.low, b.close, b.volume, 0) for b in bars_spec])

        resultados = event_study.medir_versao(self.storage, "v1")
        self.assertEqual(len(resultados), 1)
        r = resultados[0]
        self.assertEqual(r["token"], "CAT")
        self.assertAlmostEqual(r["retorno_sinal"][1], 10.0)   # 220_000/200_000 - 1 = +10%
        self.assertGreaterEqual(r["n_controles"][1], 1)   # candidatos 5 e 10 estao elegiveis

    def test_contaminado_candle_fica_fora_do_event_study(self) -> None:
        self.storage.pr1_insert_signal({
            "chain": "solana", "pool": "POOL2", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 0,
            "mint": "MINT2", "symbol": "DOG", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": '["contaminado_candle"]',
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
            "entry_price": 100.0, "stop": 80.0, "closed_ts": 3600.0,
        })
        self.assertEqual(event_study.medir_versao(self.storage, "v1"), [])


class ExecutarSmokeTests(unittest.TestCase):
    def test_banco_vazio_nunca_crasha(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="event_study_vazio_"))
        try:
            storage = Storage(make_paths(tmp))
            db_path = storage.paths.db
            storage.close()
            texto = event_study.executar(db_path)
            self.assertIn(event_study.AVISO, texto)
            self.assertNotIn("Traceback", texto)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
