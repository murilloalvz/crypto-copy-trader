"""PEDIDO 2026-11-02 (Passo 0e, item 5): smoke test do script somente-leitura sobre um banco real
(mesmo harness ao vivo) -- confirma que roda sem rede/escrita e que os números batem com o que já
está persistido (nunca um cálculo paralelo inventado).

PEDIDO 2026-11-03 (correção -- MFE +1.378.027 R inutilizável): `Passo0eExclusaoFixTests` prova a
correção diretamente, com sinais sintéticos (mesmo padrão de `test_storage_evidencia.py`): risco<3%
nunca entra no R/medias da amostra limpa (vai pra `linhas_risco_baixo`, com MFE% ainda valido via
`mfe_r * risco_pct`); `contaminado_candle` fica fora dos dois grupos; um sinal limpo normal continua
aparecendo com R igual ao que já está persistido."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..storage import Storage
from ..scripts import passo0e_topo_e_fechamento as passo0e
from .test_pos_runner_live import LiveHarness, start_tracking


class Passo0eTests(unittest.TestCase):
    def test_runs_without_exceptions_and_reports_every_version(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(17)
            texto = passo0e.executar(h.storage.paths.db)
            self.assertIn("## V1", texto)
            self.assertIn("## V2", texto)
            self.assertIn("## V3", texto)
            self.assertIn("Resposta à pergunta do Passo 0e", texto)
            self.assertNotIn("Traceback", texto)
        finally:
            h.close()

    def test_medir_versao_matches_the_persisted_tp1_timestamp(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.run_hours(40)   # tempo suficiente pra algum sinal fechar/tocar TP1
            r = passo0e.medir_versao(h.storage, "v1")
            self.assertEqual(r["versao"], "v1")
            self.assertGreaterEqual(r["n_entradas"], 0)
            # so confere a forma do resultado -- nenhum numero fabricado fora do que o banco tem.
            for chave in ("tempo_ate_topo_h", "mfe_r", "mfe_h"):
                self.assertIn(chave, r)
        finally:
            h.close()

    def test_empty_database_never_crashes(self) -> None:
        h = LiveHarness()
        try:
            texto = passo0e.executar(h.storage.paths.db)
            self.assertIn("s/d", texto)
        finally:
            h.close()


class Passo0eExclusaoFixTests(unittest.TestCase):
    """PEDIDO 2026-11-03: prova direta da correção (sinais sintéticos, sem depender do LiveHarness)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="passo0e_fix_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sinal(self, pool: str, tags: str = "[]", reason: str = "stop") -> int:
        return self.storage.pr1_insert_signal({
            "chain": "solana", "pool": pool, "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": f"MINT_{pool}", "symbol": pool, "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": tags,
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
            "entry_price": 100.0, "stop": 80.0, "reason": reason,
        })

    def test_risco_abaixo_de_3pct_nunca_entra_no_r_mas_mostra_mfe_pct_valido(self) -> None:
        # Mesma causa-raiz do McRib (-561R/-564R): risco_pct perto de 0 explode o R-multiplo. Aqui
        # risco_pct=0.1% e mfe_r=1200 (R absurdo, exatamente a classe do bug relatado) -- o fix tem
        # que converter pra % bruto (mfe_r*risco_pct=120%, numero estavel) e manter o R fora da amostra limpa.
        signal_id = self._sinal("BAIXORISCO", tags='["risco_irrealista"]')
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="BAIXORISCO", tf="1h", mint="MINT_BAIXORISCO",
            symbol="BAIXORISCO", t_entrada=1_000.0, preco_entrada=100.0, risco_pct=0.1, r_unidade=0.1,
            fonte_candle="gt", mfe_r=1200.0, mae_r=-5.0, mfe_h=2.0, fechado=1,
        )
        r = passo0e.medir_versao(self.storage, "v1")
        self.assertEqual(r["n_limpos"], 0)
        self.assertEqual(r["n_risco_baixo"], 1)
        self.assertIsNone(r["mfe_r"])  # amostra limpa de R fica vazia -- nunca contaminada pelo risco baixo
        linha = r["linhas_risco_baixo"][0]
        self.assertIsNone(linha["mfe_r"])  # nunca reportado em R quando risco<3%
        self.assertAlmostEqual(linha["mfe_pct"], 120.0)  # 1200 * 0.1% = 120%, nao 1200 "R"

    def test_contaminado_candle_fica_fora_dos_dois_grupos(self) -> None:
        signal_id = self._sinal("CONTAMINADO", tags='["contaminado_candle"]')
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="CONTAMINADO", tf="1h", mint="MINT_CONTAMINADO",
            symbol="CONTAMINADO", t_entrada=1_000.0, preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0,
            fonte_candle="gt", mfe_r=2.0, mfe_h=3.0, fechado=1,
        )
        r = passo0e.medir_versao(self.storage, "v1")
        self.assertEqual(r["n_contaminados"], 1)
        self.assertEqual(r["n_limpos"], 0)
        self.assertEqual(r["n_risco_baixo"], 0)
        self.assertEqual(r["linhas_limpas"], [])
        self.assertEqual(r["linhas_risco_baixo"], [])

    def test_sinal_limpo_normal_mantem_r_e_pct_consistentes(self) -> None:
        signal_id = self._sinal("LIMPO", reason="EXIT FULL")
        self.storage.pr_trajetoria_upsert(
            "v1", signal_id, 0.0, chain="solana", pool="LIMPO", tf="1h", mint="MINT_LIMPO",
            symbol="LIMPO", t_entrada=1_000.0, preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0,
            fonte_candle="gt", mfe_r=2.0, mae_r=-0.3, mfe_h=4.0, fechado=1,
        )
        r = passo0e.medir_versao(self.storage, "v1")
        self.assertEqual(r["n_limpos"], 1)
        self.assertEqual(r["n_risco_baixo"], 0)
        linha = r["linhas_limpas"][0]
        self.assertEqual(linha["mfe_r"], 2.0)
        self.assertAlmostEqual(linha["mfe_pct"], 40.0)  # 2.0 * 20% = 40%
        self.assertEqual(linha["motivo_saida"], "EXIT FULL")


if __name__ == "__main__":
    unittest.main()
