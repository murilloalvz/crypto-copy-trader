"""RODADA 22 (2026-11-17), condição 2 do operador: `simular_pareamento_placebo_v22.py` -- lógica
testada com dados SINTÉTICOS (esta sessão não tem acesso ao banco real/21 sinais citados pelo
operador). Reusa `textbook_v1` (MESMA série de candles já usada em todo o resto da suíte V1) para
nunca precisar reinventar uma sequência de fase -- os 3 pools usam a MESMA série de bars (fase
idêntica em qualquer ts_corte), só idade/volume mudam, isolando o teste na lógica NOVA (idade/
volume), que é o que esta rodada adiciona."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..scripts import simular_pareamento_placebo_v22 as sim
from ..storage import Storage
from .test_pos_runner_v1 import GRAD, L_BC, Series, textbook_v1


def _grava_bars(con: sqlite3.Connection, pool: str, tf: str, bars) -> None:
    for b in bars:
        con.execute(
            "INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES (?,?,?,?,?,?,?,?,1)",
            (pool, tf, b.ts, b.open, b.high, b.low, b.close, b.volume),
        )


def _grava_pool(con: sqlite3.Connection, pool: str, grad_ts, vol_h24) -> None:
    info = json.dumps({"vol_h24_usd": vol_h24}) if vol_h24 is not None else "{}"
    con.execute(
        "INSERT INTO pr_pools (pool, symbol, status, l_bc, grad_ts, info) VALUES (?,?,?,?,?,?)",
        (pool, pool, "ativo", L_BC, grad_ts, info),
    )


class CandidatosParaSinalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="simular_pareamento_"))
        storage = Storage(make_paths(self.tmp))
        self.db_path = storage.paths.db
        storage.close()
        self.con = sqlite3.connect(str(self.db_path))
        self.con.row_factory = sqlite3.Row
        self.bars = textbook_v1().bars
        self.ts_corte = self.bars[17].ts   # ponto estavel na lateral -- MESMA fase pro gatilho e candidatos

    def tearDown(self) -> None:
        self.con.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ro(self):
        self.con.commit()
        return sim._conectar_ro(self.db_path)

    def test_candidato_na_mesma_faixa_de_idade_e_volume_passa_nas_2_regras(self) -> None:
        _grava_pool(self.con, "POOLG", GRAD, 10_000.0)
        _grava_bars(self.con, "POOLG", "1h", self.bars)
        _grava_pool(self.con, "POOLA", GRAD, 10_000.0)   # MESMA idade, MESMO volume
        _grava_bars(self.con, "POOLA", "1h", self.bars)
        ro = self._ro()
        try:
            antiga = sim.candidatos_para_sinal(ro, "POOLG", "1h", self.ts_corte, 3, usar_idade_volume=False)
            nova = sim.candidatos_para_sinal(ro, "POOLG", "1h", self.ts_corte, 3, usar_idade_volume=True)
            self.assertEqual(antiga, ["POOLA"])
            self.assertEqual(nova, ["POOLA"])
        finally:
            ro.close()

    def test_candidato_fora_da_faixa_de_idade_passa_na_antiga_nunca_na_nova(self) -> None:
        _grava_pool(self.con, "POOLG", GRAD, 10_000.0)
        _grava_bars(self.con, "POOLG", "1h", self.bars)
        _grava_pool(self.con, "POOLB", GRAD - 1_000_000.0, 10_000.0)   # muito mais velho
        _grava_bars(self.con, "POOLB", "1h", self.bars)
        ro = self._ro()
        try:
            antiga = sim.candidatos_para_sinal(ro, "POOLG", "1h", self.ts_corte, 3, usar_idade_volume=False)
            nova = sim.candidatos_para_sinal(ro, "POOLG", "1h", self.ts_corte, 3, usar_idade_volume=True)
            self.assertEqual(antiga, ["POOLB"])
            self.assertEqual(nova, [])
        finally:
            ro.close()

    def test_candidato_fora_da_faixa_de_volume_passa_na_antiga_nunca_na_nova(self) -> None:
        _grava_pool(self.con, "POOLG", GRAD, 10_000.0)
        _grava_bars(self.con, "POOLG", "1h", self.bars)
        _grava_pool(self.con, "POOLC", GRAD, 999_999.0)   # muito mais volume
        _grava_bars(self.con, "POOLC", "1h", self.bars)
        ro = self._ro()
        try:
            antiga = sim.candidatos_para_sinal(ro, "POOLG", "1h", self.ts_corte, 3, usar_idade_volume=False)
            nova = sim.candidatos_para_sinal(ro, "POOLG", "1h", self.ts_corte, 3, usar_idade_volume=True)
            self.assertEqual(antiga, ["POOLC"])
            self.assertEqual(nova, [])
        finally:
            ro.close()

    def test_candidato_com_fase_diferente_nunca_entra_em_nenhuma_regra(self) -> None:
        _grava_pool(self.con, "POOLG", GRAD, 10_000.0)
        _grava_bars(self.con, "POOLG", "1h", self.bars)
        bars_planos = Series(start=GRAD).flat(100.0, 25).bars   # nunca sai de PHASE_NONE -- sem_fase
        _grava_pool(self.con, "POOLD", GRAD, 10_000.0)
        _grava_bars(self.con, "POOLD", "1h", bars_planos)
        ro = self._ro()
        try:
            antiga = sim.candidatos_para_sinal(ro, "POOLG", "1h", self.ts_corte, 3, usar_idade_volume=False)
            nova = sim.candidatos_para_sinal(ro, "POOLG", "1h", self.ts_corte, 3, usar_idade_volume=True)
            self.assertEqual(antiga, [])
            self.assertEqual(nova, [])
        finally:
            ro.close()

    def test_posicao_aberta_hoje_exclui_o_candidato(self) -> None:
        _grava_pool(self.con, "POOLG", GRAD, 10_000.0)
        _grava_bars(self.con, "POOLG", "1h", self.bars)
        _grava_pool(self.con, "POOLA", GRAD, 10_000.0)
        _grava_bars(self.con, "POOLA", "1h", self.bars)
        self.con.execute(
            "INSERT INTO pr1_signals (chain, pool, tf, evento, ts_fechamento, mint, symbol, launchpad, dex, "
            "versao_config_v1, gatilho, tags, janela_ouro, hora_brt, status, entry_price, stop, topo) VALUES "
            "('solana','POOLA','1h','ENTRADA',0,'MINTA','AAA','pumpfun','pumpswap','v1','[]','[]','jo','09:00',"
            "'aberto',1.0,0.8,2.0)"
        )
        ro = self._ro()
        try:
            antiga = sim.candidatos_para_sinal(ro, "POOLG", "1h", self.ts_corte, 3, usar_idade_volume=False)
            self.assertEqual(antiga, [])
        finally:
            ro.close()


class RelatorioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="simular_pareamento_rel_"))
        storage = Storage(make_paths(self.tmp))
        self.db_path = storage.paths.db
        storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha(self) -> None:
        texto = sim.executar(self.db_path)
        self.assertIn("Sinais V3 (ENTRADA) encontrados: 0", texto)
        self.assertNotIn("Traceback", texto)

    def test_relatorio_mostra_antiga_e_nova_lado_a_lado_e_sugestao_se_abaixo_de_60_pct(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        try:
            bars = textbook_v1().bars
            ts_corte = bars[17].ts
            _grava_pool(con, "POOLG", GRAD, 10_000.0)
            _grava_bars(con, "POOLG", "1h", bars)
            _grava_pool(con, "POOLB", GRAD - 1_000_000.0, 10_000.0)   # so passa na regra antiga
            _grava_bars(con, "POOLB", "1h", bars)
            con.execute(
                "INSERT INTO pr3_signals (chain, pool, tf, evento, ts_fechamento, mint, symbol, launchpad, dex, "
                "versao_config_v3, gatilho, tags, janela_ouro, hora_brt, status, entry_price, stop, topo, "
                "s_suporte) VALUES ('solana','POOLG','1h','ENTRADA',?,'MINTG','GGG','pumpfun','pumpswap','v3',"
                "'[]','[]','jo','09:00','aberto',1.0,0.8,2.0,0.0)", (ts_corte,),
            )
            con.commit()
        finally:
            con.close()
        texto = sim.executar(self.db_path)
        self.assertIn("Sinais V3 (ENTRADA) encontrados: 1", texto)
        self.assertIn("Regra ANTIGA (só fase+tf): >=1 placebo em 1/1 (100%)", texto)
        self.assertIn("Regra NOVA (fase+tf+idade±50%+volume 0,1x-10x): >=1 placebo em 0/1 (0%)", texto)
        self.assertIn("<60% dos sinais teriam >=1 placebo sob a regra nova", texto)


if __name__ == "__main__":
    unittest.main()
