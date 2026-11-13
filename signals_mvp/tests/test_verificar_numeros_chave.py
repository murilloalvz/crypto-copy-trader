"""PEDIDO 2026-11-10 (autorizado, Rodada 17, item 0): testes de
`scripts/verificar_numeros_chave.py` -- PASS/FAIL com tolerancia 0 pro unico baseline numerico
citado por extenso no pedido (sinais/tokens por origem), e o smoke end-to-end sobre um banco vazio
(zero crash, zero PASS fabricado). EXPLORATORIO -- so confere a mecanica/wiring."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..scripts import varredura_v3 as vv3
from ..scripts import verificar_numeros_chave as vnc
from ..storage import Storage
from .test_pos_runner_v1 import L_BC
from .test_retrospectivo_saida_fiel import _bar


class LinhaPassFailTests(unittest.TestCase):
    def test_esperado_igual_obtido_e_pass_sem_diff(self) -> None:
        linha = vnc._linha_pass_fail("n sinais", 15, 15)
        self.assertIn("[PASS]", linha)
        self.assertIn("diff=0", linha)

    def test_esperado_diferente_de_obtido_e_fail_com_diff_assinado(self) -> None:
        self.assertIn("diff=-5", vnc._linha_pass_fail("n sinais", 15, 10))
        self.assertIn("[FAIL]", vnc._linha_pass_fail("n sinais", 15, 10))
        self.assertIn("diff=+3", vnc._linha_pass_fail("n sinais", 15, 18))
        self.assertIn("[FAIL]", vnc._linha_pass_fail("n sinais", 15, 18))


class VerificarOrigemTests(unittest.TestCase):
    def _sinal(self, mint: str, pool: str) -> vv3.SinalVarredura:
        from ..pos_runner.detector_v1 import EventV1
        bars = [
            _bar(0, 100, 101, 99, 100), _bar(3_600, 100, 102, 96, 101),
            _bar(7_200, 101, 102, 97, 100), _bar(10_800, 100, 103, 98, 102),
        ]
        ev = EventV1(kind="ENTRADA", idx=0, ts=bars[0].ts, decision_ts=bars[0].ts,
                    data={"stop": 80.0, "TOPO": 200.0, "S": 0.0})
        s = vv3._montar_sinal(bars, ev, "desconhecido", None, "ao_vivo", "CAT", mint, pool, "1h",
                              None, None)
        self.assertIsNotNone(s)
        return s

    def test_baseline_exato_da_pass_nos_2_contadores(self) -> None:
        sinais = [self._sinal("MINT_A", "POOL_A"), self._sinal("MINT_B", "POOL_B")]
        vnc.BASELINE_SINAIS_TOKENS["ao_vivo"] = (2, 2)
        try:
            out = vnc.verificar_origem("ao_vivo", sinais, now=sinais[0].t_entrada + 73 * 3600)
        finally:
            vnc.BASELINE_SINAIS_TOKENS["ao_vivo"] = (15, 6)
        texto = "\n".join(out)
        self.assertIn("[PASS] n sinais: esperado=2 obtido=2", texto)
        self.assertIn("[PASS] n tokens distintos", texto)
        self.assertIn("R@72h (saida oficial A", texto)
        self.assertIn("distancia media ao topo anterior", texto)

    def test_contagem_de_tokens_usa_mint_nunca_symbol_mesmo_ticker_clone(self) -> None:
        # 2 sinais com o MESMO ticker (CAT) mas mint diferente -- precisam contar como 2 tokens
        # distintos (RODADA 17 item 2), nunca 1 so por coincidencia de symbol.
        sinais = [self._sinal("MINT_X", "POOL_A"), self._sinal("MINT_Y", "POOL_B")]
        vnc.BASELINE_SINAIS_TOKENS["ao_vivo"] = (2, 2)
        try:
            out = vnc.verificar_origem("ao_vivo", sinais, now=sinais[0].t_entrada + 73 * 3600)
        finally:
            vnc.BASELINE_SINAIS_TOKENS["ao_vivo"] = (15, 6)
        self.assertIn("[PASS] n tokens distintos", "\n".join(out))

    def test_sem_sinais_nao_crasha_e_nunca_inventa_metrica(self) -> None:
        out = vnc.verificar_origem("ao_vivo", [], now=0.0)
        texto = "\n".join(out)
        self.assertIn("[FAIL] n sinais: esperado=15 obtido=0", texto)
        self.assertIn("sem sinais nesta origem", texto)
        self.assertNotIn("R@72h", texto)


class VerificarAbertoPerdidoOfflineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vnc_aberto_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_conta_aberto_e_perdido_offline_separados(self) -> None:
        import json
        base = {
            "chain": "solana", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 0,
            "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap", "versao_config_v3": "abc123",
            "gatilho": json.dumps([]), "tags": "[]", "janela_ouro": "janela_ouro", "hora_brt": "09:00",
            "entry_price": 100.0, "stop": 90.0, "topo": 200.0, "s_suporte": 80.0, "r_resistencia": 95.0,
            "n_pavios": 2, "caixa_candles": 5, "caixa_horas": 5.0, "idade_dias": 3.0,
        }
        self.storage.pr3_insert_signal({**base, "pool": "P1", "mint": "M1", "status": "aberto"})
        self.storage.pr3_insert_signal({**base, "pool": "P2", "mint": "M2", "status": "aberto"})
        self.storage.pr3_insert_signal({**base, "pool": "P3", "mint": "M3", "status": "perdido_offline"})
        self.storage.pr3_insert_signal({**base, "pool": "P4", "mint": "M4", "status": "fechado"})
        db_path = self.storage.paths.db
        self.storage.close()
        out = vnc.verificar_aberto_perdido_offline(db_path)
        self.storage = Storage(make_paths(self.tmp))   # reabre pro tearDown fechar sem erro
        texto = "\n".join(out)
        self.assertIn("aberto: 2", texto)
        self.assertIn("perdido_offline: 1", texto)


class ExecutarSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vnc_smoke_"))
        self.storage = Storage(make_paths(self.tmp))
        self.db_path = self.storage.paths.db
        self.storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha_e_reporta_fail_honesto(self) -> None:
        texto = vnc.executar(self.db_path, progresso=False)
        self.assertIn(vnc.AVISO, texto)
        self.assertIn("[FAIL] n sinais: esperado=15 obtido=0", texto)
        self.assertIn("[FAIL] n sinais: esperado=38 obtido=0", texto)
        self.assertIn("[FAIL] n sinais: esperado=88 obtido=0", texto)
        self.assertIn("aberto: 0 | perdido_offline: 0", texto)
        self.assertNotIn("Traceback", texto)
        self.assertNotIn("[PASS]", texto)   # banco vazio nunca pode fabricar um PASS


if __name__ == "__main__":
    unittest.main()
