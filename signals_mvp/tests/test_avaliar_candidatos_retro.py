"""PEDIDO 2026-11-02 PARTE 2: testes de `scripts/avaliar_candidatos_retro.py` -- SOMENTE LEITURA do
detector, zero rede real (nenhum teste aqui chama `executar()` com candidatos nao-vazios, que exigiria
rede; `processar_candidato` e testado isolado com um `ohlcv` falso que nunca toca a rede)."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.candles import Bar
from ..pos_runner.costs import CostModel
from ..pos_runner.params_v1 import load_params_v1
from ..pos_runner.params_v2 import load_params_v2
from ..scripts import avaliar_candidatos_retro as retro
from ..storage import Storage
from .test_pos_runner_v1 import CREATED, GRAD, H, L_BC, params, textbook_v1


class _FakeOhlcv:
    """Duck-type de `OhlcvStore`: so o metodo que `processar_candidato` realmente chama."""

    def __init__(self, bars: list[Bar]):
        self.bars = bars

    def history(self, pool: str, tf: str, start_ts: int) -> list[Bar]:
        return self.bars


class CongelamentoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="retro_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _con(self):
        return retro._conectar_rw(self.storage.paths.db)   # noqa: SLF001

    def test_includes_a_verificado_pool_that_was_discarded_and_never_promoted(self) -> None:
        now = time.time()
        self.storage.pr_upsert_pool("NUNCAATIVO", status="verificado", symbol="NUNCA", mint="M1",
                                    launchpad="pumpfun", l_bc=L_BC, grad_ts=GRAD,
                                    info=json.dumps({"criado_ts": CREATED}))
        self.storage.pr_vaga_descarte_insert(now, "NUNCAATIVO")
        con = self._con()
        try:
            candidatos = retro.congelar_candidatos(con, now)
        finally:
            con.close()
        self.assertEqual([c["pool"] for c in candidatos], ["NUNCAATIVO"])
        self.assertEqual(candidatos[0]["launchpad"], "pumpfun")
        self.assertEqual(candidatos[0]["criado_ts"], CREATED)

    def test_excludes_a_pool_currently_ativo(self) -> None:
        now = time.time()
        self.storage.pr_upsert_pool("ATIVO1", status="ativo", symbol="ATIVO1",
                                    info=json.dumps({"criado_ts": CREATED}))
        self.storage.pr_vaga_descarte_insert(now, "ATIVO1")
        con = self._con()
        try:
            candidatos = retro.congelar_candidatos(con, now)
        finally:
            con.close()
        self.assertEqual(candidatos, [])

    def test_excludes_a_pool_that_was_once_active_and_rotated_to_dormant(self) -> None:
        """`_rotacionar_vagas` (PARTE 1/FASE 2) poe o pool em 'dormente' e `_recheck_dormentes` pode
        readmitir pra 'verificado' -- se faltar vaga de novo, ele volta a `pr_vaga_descartes`, mas
        NUNCA conta como "nunca foi ativo" (tem linha em `pr_dormentes` pra sempre)."""
        now = time.time()
        self.storage.pr_upsert_pool("FOIATIVO", status="verificado", symbol="FOIATIVO",
                                    info=json.dumps({"criado_ts": CREATED}))
        self.storage.pr_dormente_insert("FOIATIVO", "MINT", "FOIATIVO", "rotacao", 50_000.0, now - 3600.0)
        self.storage.pr_vaga_descarte_insert(now, "FOIATIVO")
        con = self._con()
        try:
            candidatos = retro.congelar_candidatos(con, now)
        finally:
            con.close()
        self.assertEqual(candidatos, [])

    def test_excludes_a_pool_with_any_v1_or_v2_signal_ever(self) -> None:
        now = time.time()
        self.storage.pr_upsert_pool("TEVESINAL", status="verificado", symbol="TEVESINAL",
                                    info=json.dumps({"criado_ts": CREATED}))
        self.storage._db.execute(   # noqa: SLF001 -- so pra fixar a precondicao do teste (ver test_pos_runner_evidencia_live.py)
            "INSERT INTO pr1_signals (chain, pool, tf, ts_fechamento, versao_config_v1) VALUES ('solana','TEVESINAL','1h',0,'x')")
        self.storage._db.commit()   # noqa: SLF001
        self.storage.pr_vaga_descarte_insert(now, "TEVESINAL")
        con = self._con()
        try:
            candidatos = retro.congelar_candidatos(con, now)
        finally:
            con.close()
        self.assertEqual(candidatos, [])

    def test_freeze_happens_once_and_never_recomputes_on_a_later_call(self) -> None:
        now = time.time()
        self.storage.pr_upsert_pool("PRIMEIRO", status="verificado", symbol="PRIMEIRO",
                                    info=json.dumps({"criado_ts": CREATED}))
        self.storage.pr_vaga_descarte_insert(now, "PRIMEIRO")
        con = self._con()
        try:
            primeira = retro.congelar_candidatos(con, now)
            hash1 = primeira[0]["lista_hash"]
            self.assertEqual([c["pool"] for c in primeira], ["PRIMEIRO"])
            # candidato novo aparece DEPOIS do congelamento -- nunca deve entrar na amostra congelada
            self.storage.pr_upsert_pool("DEPOIS", status="verificado", symbol="DEPOIS",
                                        info=json.dumps({"criado_ts": CREATED}))
            self.storage.pr_vaga_descarte_insert(now + 10.0, "DEPOIS")
            segunda = retro.congelar_candidatos(con, now + 10.0)
        finally:
            con.close()
        self.assertEqual([c["pool"] for c in segunda], ["PRIMEIRO"])
        self.assertEqual(segunda[0]["lista_hash"], hash1)


class OrcamentoHorarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="retro_orc_"))
        self.path = self.tmp / "orcamento.json"
        self.now = [1_800_000_000.0]

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _orc(self, limite: int) -> retro.OrcamentoHorario:
        return retro.OrcamentoHorario(self.path, limite, clock=lambda: self.now[0])

    def test_blocks_once_the_hourly_limit_is_reached(self) -> None:
        orc = self._orc(2)
        self.assertTrue(orc.pode_chamar())
        orc.registrar()
        self.assertTrue(orc.pode_chamar())
        orc.registrar()
        self.assertFalse(orc.pode_chamar())

    def test_resets_on_a_new_utc_hour_bucket(self) -> None:
        orc = self._orc(1)
        orc.registrar()
        self.assertFalse(orc.pode_chamar())
        self.now[0] += 3600.0   # proxima hora UTC
        self.assertTrue(orc.pode_chamar())

    def test_persists_across_separate_instances_same_hour(self) -> None:
        """Uma execucao de processo por vez -- o orcamento sobrevive entre invocacoes separadas do
        script (arquivo em disco, nao estado em memoria)."""
        self._orc(1).registrar()
        outra_instancia = self._orc(1)
        self.assertFalse(outra_instancia.pode_chamar())


class OrcamentoHttpClientTests(unittest.TestCase):
    def test_raises_budget_error_without_any_network_call_once_exhausted(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="retro_http_"))
        try:
            orc = retro.OrcamentoHorario(tmp / "orc.json", limite=0)   # limite 0 -- nunca pode chamar
            from ..http import RateLimiter
            http = retro.OrcamentoHttpClient("https://example.invalid", RateLimiter(60, 2), 5.0,
                                             name="teste", orcamento=orc)
            with self.assertRaises(Exception) as ctx:
                http.get_json("qualquer/caminho")
            self.assertEqual(getattr(ctx.exception, "kind", None), "budget")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ProcessarCandidatoTests(unittest.TestCase):
    def _row(self, **over) -> dict:
        base = {"pool": "POOL1", "symbol": "POOL1", "launchpad": "pumpfun", "l_bc": L_BC,
               "grad_ts": GRAD, "criado_ts": CREATED}
        base.update(over)
        return base

    def test_reproduces_the_same_entrada_the_production_detector_finds(self) -> None:
        """Amarra `processar_candidato` ao MESMO `DetectorV1`/`simulate_v1` que a suite da V1 ja
        cobre (`test_pos_runner_v1.py`) -- ground truth calculado aqui, independente, nunca um numero
        fixo chutado."""
        from ..pos_runner.detector_v1 import DetectorV1 as _D
        bars = textbook_v1().bars
        p1 = params()   # mesma janela de idade larga do textbook_v1 (so o teste de idade ja e coberto em test_pos_runner_v1.py)
        det_esperado = _D(p1, "1h", L_BC, GRAD, CREATED)
        n_entradas_esperado = 0
        for bar in bars:
            for ev in det_esperado.update(bar):
                if ev.kind == "ENTRADA":
                    n_entradas_esperado += 1
        self.assertGreaterEqual(n_entradas_esperado, 1, "textbook_v1 precisa gerar >=1 ENTRADA (ver test_pos_runner_v1.py)")
        ohlcv = _FakeOhlcv(bars)
        resultado = retro.processar_candidato(self._row(), ohlcv, None, p1, p1, CostModel(), time.time())
        self.assertTrue(resultado.historico_suficiente)
        self.assertTrue(resultado.chegou_runner)
        self.assertEqual(len(resultado.sinais_v1), n_entradas_esperado)
        self.assertEqual(len(resultado.sinais_v2), n_entradas_esperado)
        for sinal in resultado.sinais_v1:
            self.assertTrue(sinal["retroativo"])

    def test_marks_sem_dados_pool_when_l_bc_or_criado_ts_is_missing(self) -> None:
        ohlcv = _FakeOhlcv(textbook_v1().bars)
        resultado = retro.processar_candidato(self._row(l_bc=None), ohlcv, None, params(), params(), CostModel(), time.time())
        self.assertFalse(resultado.historico_suficiente)
        self.assertEqual(resultado.motivo_sem_historico, "sem_dados_pool")

    def test_marks_sem_historico_when_the_source_returns_no_candle(self) -> None:
        ohlcv = _FakeOhlcv([])
        resultado = retro.processar_candidato(self._row(), ohlcv, None, params(), params(), CostModel(), time.time())
        self.assertFalse(resultado.historico_suficiente)
        self.assertEqual(resultado.motivo_sem_historico, "sem_historico_na_fonte")

    def test_propagates_a_budget_error_instead_of_swallowing_it(self) -> None:
        from ..http import ApiError

        class _OhlcvOrcamentoEsgotado:
            def history(self, pool, tf, start_ts):
                raise ApiError("budget", "esgotado")

        with self.assertRaises(ApiError) as ctx:
            retro.processar_candidato(self._row(), _OhlcvOrcamentoEsgotado(), None, params(), params(), CostModel(), time.time())
        self.assertEqual(ctx.exception.kind, "budget")


class RStatsTests(unittest.TestCase):
    def test_excludes_risco_irrealista_signals_from_the_average_and_hit_rate(self) -> None:
        sinais = [
            {"status": "fechado", "r_mult": 2.0},
            {"status": "fechado", "r_mult": -1.0},
            {"status": "fechado", "r_mult": None},   # risco_irrealista -- fora da media
            {"status": "em_aberto", "r_mult": None},
        ]
        stats = retro._r_stats(sinais)   # noqa: SLF001
        self.assertEqual(stats["n_sinais"], 4)
        self.assertEqual(stats["n_fechados"], 3)
        self.assertEqual(stats["n_r_valido"], 2)
        self.assertAlmostEqual(stats["r_medio"], 0.5)
        self.assertAlmostEqual(stats["taxa_acerto_pct"], 50.0)


class PopulacaoAdmitidaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="retro_adm_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_persisted_funil_marco_for_pct_runner(self) -> None:
        now = time.time()
        self.storage.pr_upsert_pool("ADM1", status="ativo", mc_found=200_000.0,
                                    info=json.dumps({"criado_ts": now - 5 * 86400.0}))
        self.storage.pr_upsert_pool("ADM2", status="encerrado", mc_found=300_000.0,
                                    info=json.dumps({"criado_ts": now - 10 * 86400.0}))
        self.storage.pr_funil_marco_insert("ADM1", "v1", "runner", now)
        con = retro._conectar_rw(self.storage.paths.db)   # noqa: SLF001
        try:
            admitida = retro._populacao_admitida(con)   # noqa: SLF001
        finally:
            con.close()
        self.assertEqual(admitida["n"], 2)
        self.assertAlmostEqual(admitida["pct_runner"], 50.0)
        self.assertAlmostEqual(admitida["mc_found_medio"], 250_000.0)


class ExecutarSemCandidatosTests(unittest.TestCase):
    """Fim a fim SEM rede: nenhum candidato congelado -- o laco de download nunca roda, so a
    mecanica de congelamento/relatorio e exercida."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="retro_e2e_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reports_the_exploratory_disclaimer_and_zero_candidates(self) -> None:
        texto = retro.executar(self.storage.paths.db, self.tmp / "cache", max_chamadas_hora=15)
        self.assertIn("replicacao EXPLORATORIA", texto)
        self.assertIn("Nunca soma ao N=30", texto)
        self.assertIn("congelamento: 0 candidatos", texto)
        self.assertIn("lista_hash=", texto)
