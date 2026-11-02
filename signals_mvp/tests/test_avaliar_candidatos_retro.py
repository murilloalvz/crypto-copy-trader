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
    """Duck-type de `OhlcvStore`: so o metodo que `processar_candidato` realmente chama. `self.bars`
    aqui representa PRECO POR TOKEN em USD (o que `currency="usd"` devolve de verdade) -- com
    `supply=1.0` no row de teste, o preco "e" o MC, reaproveitando os fixtures de MC existentes de
    `test_pos_runner_v1.py` sem precisar reescala-los."""

    def __init__(self, bars: list[Bar]):
        self.bars = bars
        self.chamadas_history = 0

    def history(self, pool: str, tf: str, start_ts: int, currency: str = "usd", side: str = "base") -> list[Bar]:
        self.chamadas_history += 1
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
        """PATCH 2026-11-02: `l_bc` NUNCA e passado aqui de proposito -- um pool 'verificado' nunca
        tem `pr_pools.l_bc` de verdade (so `_refresh_core` grava isso, e so pra pool 'ativo'); o
        congelamento guarda `supply` (necessario pro script calcular MC depois), nunca exige `l_bc`."""
        now = time.time()
        self.storage.pr_upsert_pool("NUNCAATIVO", status="verificado", symbol="NUNCA", mint="M1",
                                    launchpad="pumpfun", grad_ts=GRAD, supply=1_000_000_000.0,
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
        self.assertIsNone(candidatos[0]["l_bc"])
        self.assertEqual(candidatos[0]["supply"], 1_000_000_000.0)
        self.assertEqual(candidatos[0]["side"], "base")

    def test_backfills_supply_and_side_for_a_pool_frozen_before_the_patch_without_changing_the_hash(self) -> None:
        """Simula uma lista congelada pela VERSAO ANTERIOR do script (supply/side ainda nao existiam
        como coluna) -- `congelar_candidatos` precisa preencher as colunas novas a partir de
        `pr_pools` SEM re-congelar (hash/ts intactos)."""
        now = time.time()
        self.storage.pr_upsert_pool("ANTIGO", status="verificado", symbol="ANTIGO", supply=42.0,
                                    info=json.dumps({"criado_ts": CREATED, "side": "token"}))
        con = self._con()
        try:
            con.execute("INSERT INTO pr_retro_candidatos (pool, lista_hash, congelado_em) VALUES ('ANTIGO','HASHANTIGO',123.0)")
            con.commit()
            candidatos = retro.congelar_candidatos(con, now)
        finally:
            con.close()
        self.assertEqual(len(candidatos), 1)
        self.assertEqual(candidatos[0]["lista_hash"], "HASHANTIGO")
        self.assertEqual(candidatos[0]["congelado_em"], 123.0)
        self.assertEqual(candidatos[0]["supply"], 42.0)
        self.assertEqual(candidatos[0]["side"], "token")

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
        # supply=1.0: os fixtures de `test_pos_runner_v1.py` (`textbook_v1`) ja estao em escala de MC;
        # `l_bc` NUNCA e passado aqui de proposito -- PATCH 2026-11-02, e sempre CALCULADO, nunca lido.
        base = {"pool": "POOL1", "symbol": "POOL1", "launchpad": "pumpfun", "grad_ts": GRAD,
               "supply": 1.0, "side": "base", "criado_ts": CREATED}
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
        self.assertFalse(resultado.idade_desconhecida)
        self.assertEqual(len(resultado.sinais_v1), n_entradas_esperado)
        self.assertEqual(len(resultado.sinais_v2), n_entradas_esperado)
        for sinal in resultado.sinais_v1:
            self.assertTrue(sinal["retroativo"])

    def test_repro_caso_oa_never_promoted_pool_has_no_stored_l_bc_but_now_succeeds(self) -> None:
        """PATCH 2026-11-02: reproduz o relato (60/60 `sem_dados_pool`, zero chamada de rede). Um
        candidato 'verificado' JAMAIS tem `pr_pools.l_bc` (so `_refresh_core`, que so roda pra pool
        'ativo', grava isso) -- a versao anterior deste script EXIGIA `l_bc` ja pronto e bloqueava
        antes de qualquer `ohlcv.history()`. Agora `l_bc` e calculado a partir do 1o candle (MC) que
        a propria chamada de rede devolve."""
        bars = textbook_v1().bars
        ohlcv = _FakeOhlcv(bars)
        resultado = retro.processar_candidato(self._row(), ohlcv, None, params(), params(), CostModel(), time.time())
        self.assertEqual(ohlcv.chamadas_history, 1, "precisa de exatamente 1 chamada de historico -- nunca bloqueado antes dela")
        self.assertTrue(resultado.historico_suficiente, resultado.motivo_sem_historico)
        self.assertEqual(resultado.categoria, "ok")
        self.assertGreaterEqual(len(resultado.sinais_v1), 1)

    def test_marks_sem_dados_pool_when_grad_ts_or_supply_is_missing(self) -> None:
        ohlcv = _FakeOhlcv(textbook_v1().bars)
        for campo in ("grad_ts", "supply"):
            resultado = retro.processar_candidato(self._row(**{campo: None}), ohlcv, None, params(), params(), CostModel(), time.time())
            self.assertFalse(resultado.historico_suficiente, campo)
            self.assertEqual(resultado.categoria, "sem_dados_pool", campo)
            self.assertEqual(ohlcv.chamadas_history, 0, f"{campo} ausente nunca deve chamar a rede")

    def test_marks_idade_desconhecida_but_still_succeeds_when_criado_ts_is_missing(self) -> None:
        """`criado_ts` ausente so e um atributo do resultado (idade desconhecida) -- nunca bloqueia
        mais (o `DetectorV1` ja aceita `created_ts=None`, ENTRADA cai em FORA_DA_IDADE la dentro)."""
        bars = textbook_v1().bars
        ohlcv = _FakeOhlcv(bars)
        resultado = retro.processar_candidato(self._row(criado_ts=None), ohlcv, None, params(), params(), CostModel(), time.time())
        self.assertTrue(resultado.historico_suficiente)
        self.assertTrue(resultado.idade_desconhecida)

    def test_marks_sem_historico_when_the_source_returns_no_candle(self) -> None:
        ohlcv = _FakeOhlcv([])
        resultado = retro.processar_candidato(self._row(), ohlcv, None, params(), params(), CostModel(), time.time())
        self.assertFalse(resultado.historico_suficiente)
        self.assertEqual(resultado.categoria, "sem_historico")
        self.assertEqual(resultado.motivo_sem_historico, "sem_historico_na_fonte")

    def test_propagates_a_budget_error_instead_of_swallowing_it(self) -> None:
        from ..http import ApiError

        class _OhlcvOrcamentoEsgotado:
            def history(self, pool, tf, start_ts, currency="usd", side="base"):
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


class _FakeDexpaprikaIndisponivel:
    def disponivel(self) -> bool:
        return False


class ExecutarPersistenciaTests(unittest.TestCase):
    """PEDIDO 2026-11-02 (2a rodada): um candidato 'ok' numa execucao nunca pode ser refeito (nem
    pedir rede) numa execucao seguinte, mesmo com o orcamento zerado."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="retro_exec_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _congelar(self, pools: list[str]) -> None:
        now = time.time()
        for p in pools:
            self.storage.pr_upsert_pool(p, status="verificado", symbol=p, grad_ts=GRAD, supply=1.0,
                                        info=json.dumps({"criado_ts": CREATED}))
            self.storage.pr_vaga_descarte_insert(now, p)

    def test_candidates_resolved_on_the_first_run_are_never_refetched_and_still_appear_on_the_second(self) -> None:
        self._congelar(["POOL1", "POOL2", "POOL3"])
        fake1 = _FakeOhlcv(textbook_v1().bars)
        texto1 = retro.executar(self.storage.paths.db, self.tmp / "cache", max_chamadas_hora=15,
                                ohlcv=fake1, dexpaprika=_FakeDexpaprikaIndisponivel())
        self.assertIn("ok=3", texto1)
        self.assertIn("buscados=3", texto1)
        self.assertEqual(fake1.chamadas_history, 3)

        class _OhlcvNuncaDeveSerChamado:
            def history(self, *a, **kw):
                raise AssertionError("candidato ja 'ok' persistido nunca deve pedir historico de novo")

        texto2 = retro.executar(self.storage.paths.db, self.tmp / "cache", max_chamadas_hora=0,
                                ohlcv=_OhlcvNuncaDeveSerChamado(), dexpaprika=_FakeDexpaprikaIndisponivel())
        self.assertIn("ok=3", texto2)
        self.assertIn("buscados=0", texto2)

    def test_reprocessar_forces_a_refetch_even_for_an_already_ok_candidate(self) -> None:
        self._congelar(["POOL1"])
        fake1 = _FakeOhlcv(textbook_v1().bars)
        retro.executar(self.storage.paths.db, self.tmp / "cache", max_chamadas_hora=15,
                      ohlcv=fake1, dexpaprika=_FakeDexpaprikaIndisponivel())
        self.assertEqual(fake1.chamadas_history, 1)
        fake2 = _FakeOhlcv(textbook_v1().bars)
        retro.executar(self.storage.paths.db, self.tmp / "cache", max_chamadas_hora=15, reprocessar=True,
                      ohlcv=fake2, dexpaprika=_FakeDexpaprikaIndisponivel())
        self.assertEqual(fake2.chamadas_history, 1)


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
