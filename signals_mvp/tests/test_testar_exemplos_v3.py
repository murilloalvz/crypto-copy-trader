"""PEDIDO 2026-11-05 (autorizado, rodada 11, Parte B9): testes de `scripts/testar_exemplos_v3.py` --
leitura do CSV (colunas obrigatorias, timestamps ISO8601/epoch), resolucao de pool (symbol/endereco/
mint), deteccao de ENTRADA dentro da janela esperada, e smoke end-to-end com fixture real.
EXPLORATORIO -- nunca inventa um caso."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..storage import Storage
from ..scripts import testar_exemplos_v3 as tev
from ..scripts.avaliar_v3_retro import _conectar_ro
from ..pos_runner.params_v3 import load_params_v3
from .test_pos_runner_v1 import CREATED, GRAD, L_BC, textbook_v1


class CarregarExemplosTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tev_csv_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_le_linhas_validas_e_ignora_linha_vazia(self) -> None:
        csv_path = self.tmp / "exemplos.csv"
        csv_path.write_text(
            "token_ou_pool,inicio,fim,esperado,nota\n"
            "CAT,2026-01-01T00:00:00Z,2026-01-02T00:00:00Z,sinal,teste1\n"
            ",2026-01-01T00:00:00Z,2026-01-02T00:00:00Z,sinal,linha vazia ignorada\n"
            "DOG,1000,2000,descartar,epoch direto\n",
            encoding="utf-8",
        )
        casos = tev.carregar_exemplos(csv_path)
        self.assertEqual(len(casos), 2)
        self.assertEqual(casos[0].token_ou_pool, "CAT")
        self.assertEqual(casos[0].esperado, "sinal")
        self.assertEqual(casos[1].inicio, 1000.0)
        self.assertEqual(casos[1].fim, 2000.0)

    def test_coluna_obrigatoria_ausente_levanta_erro_explicito(self) -> None:
        csv_path = self.tmp / "exemplos.csv"
        csv_path.write_text("token_ou_pool,inicio,fim\nCAT,1000,2000\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            tev.carregar_exemplos(csv_path)

    def test_modelo_do_repo_tem_as_colunas_obrigatorias(self) -> None:
        modelo = Path(__file__).resolve().parents[1] / "scripts" / "exemplos_v3_modelo.csv"
        self.assertTrue(modelo.exists(), "modelo do CSV precisa existir em signals_mvp/dados/")
        casos = tev.carregar_exemplos(modelo)
        self.assertEqual(len(casos), 1)
        self.assertIn("PLACEHOLDER", casos[0].token_ou_pool)


class TestarCasoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tev_db_"))
        storage = Storage(make_paths(self.tmp))
        self.db_path = storage.paths.db
        storage.close()
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "INSERT INTO pr_pools (pool, symbol, mint, status, l_bc, grad_ts, info) VALUES (?,?,?,?,?,?,?)",
            ("POOL1", "CAT", "MINT1", "ativo", L_BC, GRAD, json.dumps({"criado_ts": CREATED})),
        )
        bars = textbook_v1().bars
        con.executemany(
            "INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES ('POOL1','1h',?,?,?,?,?,?,?)",
            [(b.ts, b.open, b.high, b.low, b.close, b.volume, int(b.filled)) for b in bars],
        )
        con.commit()
        con.close()
        self.params = load_params_v3()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _con(self):
        return _conectar_ro(self.db_path)

    def test_resolve_por_symbol_e_acerta_quando_esperado_bate(self) -> None:
        con = self._con()
        try:
            caso = tev.CasoExemplo(token_ou_pool="CAT", inicio=0.0, fim=1e12, esperado="sinal", nota="")
            r = tev.testar_caso(con, self.params, caso)
        finally:
            con.close()
        self.assertEqual(r.pools_candidatos, ["POOL1"])
        self.assertTrue(r.sinal_gerado)   # textbook_v1 e o MESMO fixture que ja comprova >=1 ENTRADA
        self.assertTrue(r.bateu_esperado)

    def test_resolve_por_endereco_do_pool_tambem_funciona(self) -> None:
        con = self._con()
        try:
            caso = tev.CasoExemplo(token_ou_pool="POOL1", inicio=0.0, fim=1e12, esperado="sinal", nota="")
            r = tev.testar_caso(con, self.params, caso)
        finally:
            con.close()
        self.assertEqual(r.pools_candidatos, ["POOL1"])
        self.assertTrue(r.sinal_gerado)

    def test_janela_que_nunca_cobre_o_sinal_real_diverge(self) -> None:
        con = self._con()
        try:
            # janela MUITO antes de qualquer candle real -- nunca pode achar o sinal verdadeiro.
            caso = tev.CasoExemplo(token_ou_pool="CAT", inicio=-1000.0, fim=-500.0, esperado="sinal", nota="")
            r = tev.testar_caso(con, self.params, caso)
        finally:
            con.close()
        self.assertFalse(r.sinal_gerado)
        self.assertFalse(r.bateu_esperado)

    def test_pool_nao_encontrado_nunca_inventa_match(self) -> None:
        con = self._con()
        try:
            caso = tev.CasoExemplo(token_ou_pool="NUNCA_EXISTIU", inicio=0.0, fim=1e12, esperado="sinal", nota="")
            r = tev.testar_caso(con, self.params, caso)
        finally:
            con.close()
        self.assertEqual(r.pools_candidatos, [])
        self.assertIsNone(r.bateu_esperado)

    def test_indefinido_e_fora_do_setup_nunca_contam_acerto_ou_erro(self) -> None:
        con = self._con()
        try:
            caso_indef = tev.CasoExemplo(token_ou_pool="CAT", inicio=0.0, fim=1e12, esperado="indefinido", nota="")
            caso_fora = tev.CasoExemplo(token_ou_pool="CAT", inicio=0.0, fim=1e12, esperado="fora_do_setup", nota="")
            r_indef = tev.testar_caso(con, self.params, caso_indef)
            r_fora = tev.testar_caso(con, self.params, caso_fora)
        finally:
            con.close()
        self.assertIsNone(r_indef.bateu_esperado)
        self.assertIsNone(r_fora.bateu_esperado)


class FormatarSecaoSeparadaTests(unittest.TestCase):
    def test_informativos_ficam_em_secao_propria_nunca_contados(self) -> None:
        avaliado = tev.ResultadoCaso(
            tev.CasoExemplo("CAT", 0.0, 1.0, "sinal", ""), ["POOL1"], True, [0.5], True)
        informativo = tev.ResultadoCaso(
            tev.CasoExemplo("DOG", 0.0, 1.0, "indefinido", "ver com o operador"), ["POOL2"], False, [], None)
        texto = tev.formatar([avaliado, informativo])
        self.assertIn("casos avaliados (esperado='sinal'/'descartar'): bateu 1/1", texto)
        self.assertIn("Casos informativos", texto)
        self.assertIn("DOG", texto)
        self.assertIn("ver com o operador", texto)

    def test_esperado_nao_reconhecido_nunca_e_silenciosamente_descartado(self) -> None:
        caso_estranho = tev.ResultadoCaso(
            tev.CasoExemplo("ZZZ", 0.0, 1.0, "talvez", ""), ["POOL3"], False, [], None)
        texto = tev.formatar([caso_estranho])
        self.assertIn("NAO RECONHECIDO", texto)
        self.assertIn("ZZZ", texto)


class ExecutarSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tev_smoke_"))
        storage = Storage(make_paths(self.tmp))
        self.db_path = storage.paths.db
        storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_pool_nao_encontrado_nunca_crasha(self) -> None:
        csv_path = self.tmp / "exemplos.csv"
        csv_path.write_text("token_ou_pool,inicio,fim,esperado,nota\nXYZ,0,1e12,sinal,\n", encoding="utf-8")
        texto = tev.executar(self.db_path, csv_path)
        self.assertIn(tev.AVISO, texto)
        self.assertIn("POOL NAO ENCONTRADO", texto)
        self.assertNotIn("Traceback", texto)


if __name__ == "__main__":
    unittest.main()
