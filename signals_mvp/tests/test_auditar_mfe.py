"""PEDIDO 2026-11-03 (continuacao -- pendente 1): testes de `scripts/auditar_mfe.py` -- prova direta
do caso relatado (MAE -72% com stop em -40%, so possivel pos-saida)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from typing import Optional
from pathlib import Path

from ..config import make_paths
from ..storage import Storage
from ..scripts import auditar_mfe
from .test_pos_runner_v1 import CREATED, GRAD, L_BC, textbook_v1


def _bars(spec: list[tuple[float, float, float, float]], ts0: int = 0, step: int = 3_600,
         volume: float = 100.0) -> list[tuple]:
    # PEDIDO 2026-11-05: volume>0 por padrao -- candle volume=0 agora e `candle_corrompido_provavel`
    # e NUNCA concorre ao MFE/MAE (testes que precisam do candle real continuam precisando de volume).
    return [(ts0 + i * step, o, h, l, c, volume, 0) for i, (o, h, l, c) in enumerate(spec)]


class AuditarMfeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="auditar_mfe_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sinal(self, pool: str, entry_price: float, stop: float, closed_ts: float) -> int:
        return self.storage.pr1_insert_signal({
            "chain": "solana", "pool": pool, "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 0,
            "mint": f"MINT_{pool}", "symbol": pool, "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]",
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
            "entry_price": entry_price, "stop": stop, "reason": "stop", "closed_ts": closed_ts,
        })

    def test_mae_profundo_so_aparece_na_janela_pos_saida_nunca_durante_a_posicao(self) -> None:
        # entrada=100, stop=60 (risco 40%). Durante a posicao (0-2h) o preco nunca passa do stop.
        # Depois que a posicao fecha (closed_ts=2h), o preco despenca pra 28 (-72%) -- EXATAMENTE o
        # caso relatado (MAE -72% < stop -40%): so pode estar na janela pos-saida.
        signal_id = self._sinal("CAT", entry_price=100.0, stop=60.0, closed_ts=7_200.0)
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="CAT", tf="1h", mint="MINT_CAT", symbol="CAT",
            t_entrada=0.0, preco_entrada=100.0, risco_pct=40.0, r_unidade=40.0, fonte_candle="gt",
        )
        bars_rows = _bars([
            (100, 110, 95, 105),    # h=0..1h: durante a posicao, MFE aqui (+10%)
            (105, 108, 90, 95),     # h=1..2h: ainda durante a posicao (closed_ts=2h)
            (95, 96, 28, 30),       # h=2..3h: JA FECHADA -- MAE -72% (28/100-1) acontece aqui
        ])
        self.storage.pr_append_bars("CAT", "1h", bars_rows)
        resultados = auditar_mfe.medir_versao(self.storage, "v1")
        self.assertEqual(len(resultados), 1)
        r = resultados[0]
        durante = r["janelas"]["durante_posicao"]
        pos_saida = r["janelas"]["pos_saida"]
        self.assertIsNotNone(durante["mae"])
        self.assertGreaterEqual(durante["mae"]["pct"], -40.0 - 1e-6)   # nunca passa do stop durante a posicao
        self.assertIsNotNone(pos_saida["mae"])
        self.assertAlmostEqual(pos_saida["mae"]["pct"], -72.0)
        self.assertLess(pos_saida["mae"]["pct"], durante["mae"]["pct"])   # o MAE profundo e SO pos-saida

    def test_risco_abaixo_de_3pct_mostra_pct_mas_nunca_r(self) -> None:
        signal_id = self._sinal("BAIXORISCO", entry_price=100.0, stop=99.9, closed_ts=3_600.0)
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="BAIXORISCO", tf="1h", mint="MINT_BAIXORISCO",
            symbol="BAIXORISCO", t_entrada=0.0, preco_entrada=100.0, risco_pct=0.1, r_unidade=0.1,
            fonte_candle="gt",
        )
        self.storage.pr_append_bars("BAIXORISCO", "1h", _bars([(100, 500, 100, 400)]))
        resultados = auditar_mfe.medir_versao(self.storage, "v1")
        mfe = resultados[0]["janelas"]["pos_entrada_72h"]["mfe"]
        self.assertIsNotNone(mfe)
        self.assertIsNone(mfe["r"])
        self.assertAlmostEqual(mfe["pct"], 400.0)

    def test_contaminado_e_risco_irrealista_ficam_fora(self) -> None:
        self._sinal_tag("CONTAM", '["contaminado_candle"]')
        self._sinal_tag("RISCOIRR", '["risco_irrealista"]')
        resultados = auditar_mfe.medir_versao(self.storage, "v1")
        self.assertEqual(resultados, [])

    def _sinal_tag(self, pool: str, tags: str) -> None:
        signal_id = self.storage.pr1_insert_signal({
            "chain": "solana", "pool": pool, "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 0,
            "mint": f"MINT_{pool}", "symbol": pool, "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": tags,
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
            "entry_price": 100.0, "stop": 80.0, "reason": "stop", "closed_ts": 3_600.0,
        })
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool=pool, tf="1h", mint=f"MINT_{pool}", symbol=pool,
            t_entrada=0.0, preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0, fonte_candle="gt",
        )
        self.storage.pr_append_bars(pool, "1h", _bars([(100, 110, 95, 105)]))

    def test_divergencia_dexpaprika_aparece_so_para_v1(self) -> None:
        signal_id = self._sinal("DIVERG", entry_price=100.0, stop=80.0, closed_ts=3_600.0)
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="DIVERG", tf="1h", mint="MINT_DIVERG", symbol="DIVERG",
            t_entrada=0.0, preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0, fonte_candle="gt",
        )
        self.storage.pr_append_bars("DIVERG", "1h", _bars([(100, 110, 95, 105)]))
        self.storage.pr1_dexpaprika_divergencia_insert(
            0.0, "solana", "DIVERG", "MINT_DIVERG", "DIVERG", "1h", 0, "high", 110.0, 95.0, 15.8, "abc123")
        resultados = auditar_mfe.medir_versao(self.storage, "v1")
        mfe = resultados[0]["janelas"]["pos_entrada_72h"]["mfe"]
        self.assertIn("high", mfe["divergencia_dexpaprika"])
        self.assertIn("GT=110", mfe["divergencia_dexpaprika"])

    def test_vol_entrada_e_vol_24h_antes_somam_so_os_candles_anteriores_a_entrada(self) -> None:
        # PEDIDO 2026-11-05 (FRENTE B): entrada no 5o candle (ts=4h); os 4 anteriores (10+20+30+40=100)
        # estao dentro das 24h antes -- o candle de entrada (vol=5) NUNCA entra nessa soma.
        signal_id = self._sinal("VOLCHECK", entry_price=100.0, stop=80.0, closed_ts=18_000.0)
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="VOLCHECK", tf="1h", mint="MINT_VOLCHECK",
            symbol="VOLCHECK", t_entrada=14_400.0, preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0,
            fonte_candle="gt",
        )
        rows = [
            (0, 100, 100, 100, 100, 10.0, 0), (3_600, 100, 100, 100, 100, 20.0, 0),
            (7_200, 100, 100, 100, 100, 30.0, 0), (10_800, 100, 100, 100, 100, 40.0, 0),
            (14_400, 100, 110, 95, 105, 5.0, 0), (18_000, 105, 108, 90, 95, 7.0, 0),
        ]
        self.storage.pr_append_bars("VOLCHECK", "1h", rows)
        resultados = auditar_mfe.medir_versao(self.storage, "v1")
        self.assertEqual(len(resultados), 1)
        self.assertAlmostEqual(resultados[0]["vol_entrada"], 5.0)
        self.assertAlmostEqual(resultados[0]["vol_24h_antes"], 100.0)

    def test_candle_volume_zero_nunca_decide_mfe_e_e_contado_como_descartado(self) -> None:
        # PEDIDO 2026-11-05 (correcao FRENTE A, item 1): o candle com o high mais alto (+400%) tem
        # volume=0 (lacuna/sem negociacao) -- NUNCA pode vencer o MFE; o real vencedor e o proximo
        # candle limpo (+10%), e o descartado entra na contagem da janela.
        signal_id = self._sinal("VOLZERO", entry_price=100.0, stop=80.0, closed_ts=10_800.0)
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="VOLZERO", tf="1h", mint="MINT_VOLZERO",
            symbol="VOLZERO", t_entrada=0.0, preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0,
            fonte_candle="gt",
        )
        rows = [
            (0, 100, 105, 95, 100, 100.0, 0),      # entrada, limpo
            (3_600, 100, 500, 100, 100, 0.0, 0),   # pico enorme, MAS volume=0 -- descartado
            (7_200, 100, 110, 95, 105, 100.0, 0),  # real vencedor do MFE (+10%)
        ]
        self.storage.pr_append_bars("VOLZERO", "1h", rows)
        resultados = auditar_mfe.medir_versao(self.storage, "v1")
        self.assertEqual(len(resultados), 1)
        jan = resultados[0]["janelas"]["pos_entrada_72h"]
        self.assertAlmostEqual(jan["mfe"]["pct"], 10.0)
        self.assertEqual(jan["n_candles_corrompidos_descartados"], 1)

    def test_candle_pico_isolado_vs_2_vizinhos_nunca_decide_mfe(self) -> None:
        # high 20x MAIOR que os dois vizinhos (105 e 108) -- mesmo com volume>0, e
        # `candle_corrompido_provavel` (pico isolado, provavel erro de dado).
        signal_id = self._sinal("PICOISOLADO", entry_price=100.0, stop=80.0, closed_ts=10_800.0)
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="PICOISOLADO", tf="1h", mint="MINT_PICOISOLADO",
            symbol="PICOISOLADO", t_entrada=0.0, preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0,
            fonte_candle="gt",
        )
        rows = [
            (0, 100, 105, 95, 100, 100.0, 0),       # entrada, limpo
            (3_600, 100, 2_000, 100, 100, 100.0, 0),  # isolado: 2000 > 10x105 E > 10x108
            (7_200, 100, 108, 95, 105, 100.0, 0),    # vizinho seguinte, limpo
        ]
        self.storage.pr_append_bars("PICOISOLADO", "1h", rows)
        resultados = auditar_mfe.medir_versao(self.storage, "v1")
        jan = resultados[0]["janelas"]["pos_entrada_72h"]
        self.assertLess(jan["mfe"]["pct"], 20.0)   # nunca o +1900% do candle isolado
        self.assertEqual(jan["n_candles_corrompidos_descartados"], 1)


class DeduplicacaoEMetricasNovasTests(unittest.TestCase):
    """PEDIDO 2026-11-05 (correcao FRENTE A, itens 2/3): dedup por (origem, pool, entrada_ts) e as
    4 metricas novas -- dicts sinteticos minimos, mesmo estilo de ResumoTests."""

    @staticmethod
    def _linha(versao: str, origem: str, pool: str, entrada_ts: float, token: str,
              mfe_r: Optional[float], reason: Optional[str] = None,
              pos_saida_mfe_pct: Optional[float] = None) -> dict:
        janelas: dict = {"durante_posicao": {"mfe": {"pct": 1.0, "r": mfe_r} if mfe_r is not None else None,
                                             "mae": None, "n_candles_corrompidos_descartados": 0}}
        if pos_saida_mfe_pct is not None:
            janelas["pos_saida"] = {"mfe": {"pct": pos_saida_mfe_pct, "r": None},
                                    "mae": None, "n_candles_corrompidos_descartados": 0}
        return {"token": token, "pool": pool, "entrada_ts": entrada_ts, "versao": versao, "origem": origem,
               "risco_pct": 20.0, "r_oficial": mfe_r, "reason": reason, "janelas": janelas,
               "vol_entrada": None, "vol_24h_antes": None}

    def test_mesmo_trade_em_v1_e_v2_conta_1x_no_resumo(self) -> None:
        linhas = [
            self._linha("v2", "ao_vivo", "POOL1", 100.0, "CAT", mfe_r=2.0),
            self._linha("v1", "ao_vivo", "POOL1", 100.0, "CAT", mfe_r=2.0),   # MESMO trade real
            self._linha("v1", "ao_vivo", "POOL2", 200.0, "DOG", mfe_r=0.5),  # trade DIFERENTE
        ]
        res = auditar_mfe.resumo(linhas)
        self.assertEqual(res["n_antes_dedup"], 3)
        self.assertEqual(res["n_depois_dedup"], 2)
        self.assertEqual(res["n_fechados"], 2)
        dedup = auditar_mfe._deduplicar_por_entrada(linhas)
        grupo_cat = next(r for r in dedup if r["token"] == "CAT")
        self.assertEqual(grupo_cat["versao"], "v1")   # prioridade v1 < v2
        self.assertEqual(grupo_cat["_versoes_agrupadas"], ["v1", "v2"])

    def test_tokens_distintos_com_mfe_1r_e_2r(self) -> None:
        linhas = [
            self._linha("v1", "ao_vivo", "P1", 1.0, "CAT", mfe_r=2.5),
            self._linha("v1", "ao_vivo", "P2", 2.0, "DOG", mfe_r=1.2),
            self._linha("v1", "ao_vivo", "P3", 3.0, "BIRD", mfe_r=0.3),
        ]
        res = auditar_mfe.resumo(linhas)
        self.assertEqual(res["n_tokens_mfe_1r"], 2)   # CAT e DOG
        self.assertEqual(res["n_tokens_mfe_2r"], 1)   # so CAT

    def test_devolucao_2r_para_stop_so_conta_quem_fechou_em_stop(self) -> None:
        linhas = [
            self._linha("v1", "ao_vivo", "P1", 1.0, "CAT", mfe_r=2.5, reason="stop"),
            self._linha("v1", "ao_vivo", "P2", 2.0, "DOG", mfe_r=3.0, reason="exit_full"),
        ]
        res = auditar_mfe.resumo(linhas)
        self.assertEqual(res["n_devolucao_2r_para_stop"], 1)   # so CAT (DOG fechou em exit_full)

    def test_stop_seguido_de_alta_100pct_72h_conta_token_distinto(self) -> None:
        linhas = [
            self._linha("v1", "ao_vivo", "P1", 1.0, "CAT", mfe_r=0.1, reason="stop", pos_saida_mfe_pct=150.0),
            self._linha("v1", "ao_vivo", "P2", 2.0, "DOG", mfe_r=0.1, reason="stop", pos_saida_mfe_pct=20.0),
            self._linha("v1", "ao_vivo", "P3", 3.0, "BIRD", mfe_r=0.1, reason="tp1", pos_saida_mfe_pct=150.0),
        ]
        res = auditar_mfe.resumo(linhas)
        self.assertEqual(res["n_tokens_stop_seguido_alta_100pct_72h"], 1)   # so CAT

    def test_formatar_separa_origens_e_marca_replay_v3_como_exploratorio(self) -> None:
        # mfe_r=None (nunca formata candle de detalhe aqui -- so testa cabecalho/ordem do resumo).
        linhas = [
            self._linha("v1", "ao_vivo", "P1", 1.0, "CAT", mfe_r=None),
            self._linha("v1", "retro_lote1", "P2", 2.0, "DOG", mfe_r=None),
            self._linha("v3", "replay_v3", "P3", 3.0, "BIRD", mfe_r=None),
        ]
        texto = auditar_mfe.formatar(linhas)
        self.assertIn("ao vivo (V1/V2/V3) -- resumo", texto)
        self.assertIn("coorte retro lote 1", texto)
        self.assertIn("replay V3 sobre pools admitidos hoje (EXPLORATORIO) -- resumo", texto)
        self.assertLess(texto.index("ao vivo"), texto.index("retro lote 1"))
        self.assertLess(texto.index("retro lote 1"), texto.index("replay V3"))


class ExecutarSmokeTests(unittest.TestCase):
    def test_executar_nunca_crasha_com_banco_vazio(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="auditar_mfe_executar_"))
        try:
            db_path = make_paths(tmp).db
            storage = Storage(make_paths(tmp))
            storage.close()
            texto = auditar_mfe.executar(db_path)
            self.assertIn("auditar_mfe", texto)
            self.assertNotIn("Traceback", texto)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ResumoTests(unittest.TestCase):
    def test_conta_lucro_antes_da_saida_mfe_r_mediano_e_r_por_token(self) -> None:
        resultados = [
            {"token": "CAT", "r_oficial": 2.0,
             "janelas": {"durante_posicao": {"mfe": {"pct": 10.0, "r": 2.0}, "mae": None}}},
            {"token": "CAT", "r_oficial": -1.0,
             "janelas": {"durante_posicao": {"mfe": {"pct": -5.0, "r": -1.0}, "mae": None}}},
            {"token": "DOG", "r_oficial": 1.0,
             "janelas": {"durante_posicao": {"mfe": {"pct": 20.0, "r": 4.0}, "mae": None}}},
        ]
        res = auditar_mfe.resumo(resultados)
        self.assertEqual(res["n_fechados"], 3)
        self.assertEqual(res["n_lucraram_antes_da_saida"], 2)   # CAT#1 (+10%) e DOG (+20%)
        self.assertAlmostEqual(res["mfe_r_mediano"], 2.0)   # mediana de (2.0, -1.0, 4.0)
        self.assertEqual(res["n_tokens_distintos"], 2)
        self.assertAlmostEqual(res["r_por_token"]["CAT"]["r_medio"], 0.5)   # media(2.0, -1.0)
        self.assertEqual(res["r_por_token"]["DOG"]["n"], 1)

    def test_sinal_sem_janela_durante_posicao_nunca_entra_no_n_fechados(self) -> None:
        resultados = [{"token": "CAT", "r_oficial": None, "janelas": {"pos_entrada_72h": {"mfe": None, "mae": None}}}]
        res = auditar_mfe.resumo(resultados)
        self.assertEqual(res["n_fechados"], 0)

    def test_vol_24h_antes_zero_conta_como_sem_negociacao_antes_da_entrada(self) -> None:
        resultados = [
            {"token": "CAT", "r_oficial": None, "janelas": {}, "vol_entrada": 5.0, "vol_24h_antes": 0.0},
            {"token": "DOG", "r_oficial": None, "janelas": {}, "vol_entrada": 50.0, "vol_24h_antes": 200.0},
        ]
        res = auditar_mfe.resumo(resultados)
        self.assertEqual(res["n_24h_antes_sem_negociacao"], 1)
        self.assertEqual(res["n_vol_entrada_valido"], 2)
        self.assertAlmostEqual(res["vol_entrada_mediano"], 27.5)
        self.assertAlmostEqual(res["vol_24h_antes_mediano"], 100.0)


class FontesBeCTests(unittest.TestCase):
    """PEDIDO 2026-11-04 (FRENTE A): fontes B (coorte retro lote1 admitida) e C (replay V3) usam o
    MESMO fixture ja validado em test_avaliar_v3_retro.py (gera >=1 ENTRADA de verdade, nunca um
    numero fixo chutado)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="auditar_mfe_bc_"))
        storage = Storage(make_paths(self.tmp))
        self.db_path = storage.paths.db
        storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _popular_pool_admitido(self, con: sqlite3.Connection, pool: str, symbol: str) -> None:
        bars = textbook_v1().bars
        added_ts = max(b.ts for b in bars) + 7_200.0   # depois de TODO o historico -- truncamento inclui tudo
        con.execute(
            "INSERT INTO pr_pools (pool, symbol, status, l_bc, grad_ts, added_ts, info) VALUES (?,?,?,?,?,?,?)",
            (pool, symbol, "ativo", L_BC, GRAD, added_ts, json.dumps({"criado_ts": CREATED})),
        )
        con.executemany(
            f"INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES ('{pool}','1h',?,?,?,?,?,?,?)",
            [(b.ts, b.open, b.high, b.low, b.close, b.volume, int(b.filled)) for b in bars],
        )

    def test_medir_v3_replay_sobre_pool_admitido_real_gera_janelas(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        self._popular_pool_admitido(con, "POOL1", "CAT")
        con.commit()
        con.close()
        storage = Storage(make_paths(self.tmp))
        try:
            linhas = auditar_mfe.medir_v3_replay(storage, self.db_path)
        finally:
            storage.close()
        self.assertGreaterEqual(len(linhas), 1)
        for l in linhas:
            self.assertEqual(l["versao"], "v3")
            self.assertEqual(l["origem"], "replay_v3")
            self.assertIn("pos_entrada_72h", l["janelas"])

    def test_medir_retro_admitido_sobre_lote1_real_gera_janelas(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "CREATE TABLE IF NOT EXISTS pr_retro_candidatos (pool TEXT PRIMARY KEY, mint TEXT, symbol TEXT, "
            "launchpad TEXT, l_bc REAL, grad_ts REAL, criado_ts REAL, mc_found REAL, lista_hash TEXT NOT NULL, "
            "congelado_em REAL NOT NULL)"
        )
        con.execute(
            "INSERT INTO pr_retro_candidatos (pool, mint, symbol, launchpad, grad_ts, criado_ts, lista_hash, "
            "congelado_em) VALUES ('POOL1', 'MINT1', 'CAT', 'pumpfun', ?, ?, 'hash123', 0.0)",
            (GRAD, CREATED),
        )
        self._popular_pool_admitido(con, "POOL1", "CAT")
        con.commit()
        con.close()
        storage = Storage(make_paths(self.tmp))
        try:
            linhas = auditar_mfe.medir_retro_admitido(storage, self.db_path)
        finally:
            storage.close()
        self.assertGreaterEqual(len(linhas), 1)
        for l in linhas:
            self.assertIn(l["versao"], ("v1", "v2"))
            self.assertEqual(l["origem"], "retro_lote1")
            self.assertIn("pos_entrada_72h", l["janelas"])


if __name__ == "__main__":
    unittest.main()
