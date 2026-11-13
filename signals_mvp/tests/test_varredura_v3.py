"""PEDIDO 2026-11-05 (autorizado, Parte B): testes de `scripts/varredura_v3.py` -- toque causal
(+1R/+2R/+3R antes de -1R, prioridade do stop no mesmo candle, candle corrompido nunca decide),
dedup por token, check de RAM, e smoke end-to-end (banco vazio, pool admitido real, --csv,
RAM insuficiente). EXPLORATORIO -- nunca testa "edge" (isso e H1)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.candles import Bar
from ..pos_runner.detector_v1 import EventV1
from ..pos_runner.costs import CostModel
from ..pos_runner.params_v3 import load_params_v3
from ..storage import Storage
from ..scripts import varredura_v3 as vv3
from .test_pos_runner_v1 import CREATED, GRAD, L_BC, textbook_v1


def _bar(ts: float, o: float, h: float, l: float, c: float, v: float = 10.0) -> Bar:
    return Bar(ts=int(ts), open=o, high=h, low=l, close=c, volume=v)


def _sinal(bars: list[Bar], ev_idx: int = 0, stop: float = 90.0, topo: float = 1000.0,
          s_val: float = 50.0, token: str = "CAT", mint: str | None = None, pool: str = "P1", tf: str = "1h",
          t_entrada: float | None = None, entry_price: float = 100.0,
          created_ts: float | None = None, origem: str = "universo_admitido") -> vv3.SinalVarredura:
    ev = EventV1(kind="ENTRADA", idx=ev_idx, ts=bars[ev_idx].ts, decision_ts=bars[ev_idx].ts,
                data={"stop": stop, "TOPO": topo, "S": s_val})
    risk_frac = (entry_price - stop) / entry_price
    t = t_entrada if t_entrada is not None else float(bars[ev_idx + 1].ts)
    return vv3.SinalVarredura(
        token=token, mint=mint if mint is not None else token, pool=pool, tf=tf, origem=origem, bars=bars,
        ev=ev, dex="pumpswap", l_bc=L_BC, created_ts=created_ts, supply=None, t_entrada=t,
        entry_price=entry_price, entrada_corrigida=False, stop=stop, topo=topo, s_val=s_val, risk_frac=risk_frac,
        volume_gatilho=None, volume_entrada=None, volume_medio_24h=None, n_pavios=3,
    )


def _bars_mc_elegiveis(n_flat: int = 25, n_rampa: int = 9) -> list[Bar]:
    """Serie em escala de MC (USD, MESMA convencao de `pr_bars` -- `quotes.to_mc_bars`): idx0 fixa um
    pico de 1.000.000; `n_flat` candles em ~150k (queda ~85% do pico, MC>=100k -- elegiveis pra
    `candidatos_elegiveis`); depois `n_rampa` candles em disparada (garante que TODO controle/
    entrada aleatoria sorteado na faixa plana, ao varrer causalmente pra frente, toca +NR antes do
    stop -- nunca 'indefinido' por falta de candle). Usado so pra exercitar o pareamento por toque e
    o comparador aleatorio (rodada 9, itens 1/3); SEM pretensao de realismo de mercado."""
    bars = [_bar(0, 1_000_000, 1_000_000, 1_000_000, 1_000_000)]
    for i in range(1, 1 + n_flat):
        bars.append(_bar(i * 3600, 150_000, 155_000, 140_000, 150_000))
    for j in range(n_rampa):
        h = 200_000 + j * 300_000
        bars.append(_bar((1 + n_flat + j) * 3600, h * 0.9, h, h * 0.85, h * 0.95))
    return bars


class RamTests(unittest.TestCase):
    def test_ram_disponivel_mb_devolve_float_ou_none(self) -> None:
        v = vv3.ram_disponivel_mb()
        self.assertTrue(v is None or isinstance(v, float))

    def test_checar_ram_ou_abortar_nunca_dispara_com_minimo_zero(self) -> None:
        vv3.checar_ram_ou_abortar(0.0)   # nao deve lancar

    def test_checar_ram_ou_abortar_dispara_com_minimo_absurdo(self) -> None:
        disponivel = vv3.ram_disponivel_mb()
        if disponivel is None:
            self.skipTest("ram_disponivel_mb indisponivel neste ambiente (nao-Linux)")
        with self.assertRaises(vv3.RamInsuficienteError):
            vv3.checar_ram_ou_abortar(10 ** 9)


class DeduplicarPorTokenTests(unittest.TestCase):
    def test_agrupa_por_token_e_remove_evento_repetido(self) -> None:
        bars = [_bar(i * 3600, 100, 105, 95, 100) for i in range(5)]
        s1 = _sinal(bars, token="CAT", pool="P1", t_entrada=3600.0)
        s2 = _sinal(bars, token="CAT", pool="P1", t_entrada=3600.0)   # mesmo (pool,tf,t_entrada) -- dup
        s3 = _sinal(bars, token="CAT", pool="P2", t_entrada=3600.0)   # pool diferente -- conta
        s4 = _sinal(bars, token="DOG", pool="P3", t_entrada=3600.0)
        por_token = vv3.deduplicar_por_token([s1, s2, s3, s4])
        self.assertEqual(set(por_token), {"CAT", "DOG"})
        self.assertEqual(len(por_token["CAT"]), 2)   # s1 e s3 (s2 e dup de s1)
        self.assertEqual(len(por_token["DOG"]), 1)

    def test_agrupa_por_mint_nunca_por_symbol_clones_de_mesmo_ticker_ficam_separados(self) -> None:
        # RODADA 17 (achado A2 da auditoria 2026-11-10): 2 tokens DISTINTOS (mints diferentes) com o
        # MESMO ticker "CAT" -- antes da correcao, `deduplicar_por_token` agrupava por symbol e os
        # fundia num so grupo; agora precisam ficar SEPARADOS, cada um sua propria chave (mint).
        bars = [_bar(i * 3600, 100, 105, 95, 100) for i in range(5)]
        s_clone_a = _sinal(bars, token="CAT", mint="MINT_A", pool="P1", t_entrada=3600.0)
        s_clone_b = _sinal(bars, token="CAT", mint="MINT_B", pool="P2", t_entrada=3600.0)
        por_token = vv3.deduplicar_por_token([s_clone_a, s_clone_b])
        self.assertEqual(set(por_token), {"MINT_A", "MINT_B"})
        self.assertEqual(len(por_token["MINT_A"]), 1)
        self.assertEqual(len(por_token["MINT_B"]), 1)

    def test_agrupa_por_mint_mesma_entidade_2_pools_mesmo_mint_ainda_soma(self) -> None:
        # Mesmo token real (MESMO mint), 2 pools distintos (ex. migracao/relancamento) -- precisa
        # continuar somando no MESMO grupo, exatamente como antes da correcao.
        bars = [_bar(i * 3600, 100, 105, 95, 100) for i in range(5)]
        s1 = _sinal(bars, token="CAT", mint="MINTCAT", pool="P1", t_entrada=3600.0)
        s2 = _sinal(bars, token="CAT", mint="MINTCAT", pool="P2", t_entrada=3600.0)
        por_token = vv3.deduplicar_por_token([s1, s2])
        self.assertEqual(set(por_token), {"MINTCAT"})
        self.assertEqual(len(por_token["MINTCAT"]), 2)


class PrimeiroToqueTests(unittest.TestCase):
    def test_toque_no_alvo_antes_do_stop(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 105, 95, 100),     # entrada, sem toque
            _bar(7200, 100, 111, 96, 105),     # toca +1R (110) antes do stop (90)
        ]
        s = _sinal(bars, ev_idx=0, stop=90.0, entry_price=100.0)
        self.assertEqual(vv3._primeiro_toque(s, 1.0), "alvo")

    def test_toque_no_stop_tem_prioridade_no_mesmo_candle(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 111, 89, 105),     # mesmo candle toca os dois -- stop ganha
        ]
        s = _sinal(bars, ev_idx=0, stop=90.0, entry_price=100.0)
        self.assertEqual(vv3._primeiro_toque(s, 1.0), "stop")

    def test_indefinido_quando_a_serie_acaba_sem_decidir(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 102, 98, 100),
        ]
        s = _sinal(bars, ev_idx=0, stop=90.0, entry_price=100.0)
        self.assertIsNone(vv3._primeiro_toque(s, 1.0))

    def test_candle_corrompido_nunca_decide(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 101, 99, 100),          # entrada limpa, sem toque
            _bar(7200, 100, 50, 10, 10, v=0.0),      # corrompido (volume 0); low<=stop, mas ignorado
            _bar(10800, 100, 111, 96, 105),          # toca o alvo de verdade
        ]
        s = _sinal(bars, ev_idx=0, stop=90.0, entry_price=100.0)
        self.assertEqual(vv3._primeiro_toque(s, 1.0), "alvo")


class VetoAmploOptInTests(unittest.TestCase):
    """RODADA 18 item 2: `veto='amplo'` (opt-in, default continua 'simples' em TODA funcao de
    biblioteca) usa o MESMO veto do caminho ao vivo -- candle isolado cujo salto e >10x o CLOSE do
    vizinho anterior mas NUNCA >10x o HIGH de ambos os vizinhos (o simples exige os 2)."""

    def test_toque_causal_simples_bate_o_stop_amplo_nunca_decide_nele(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 150, 96, 101),      # idx1 -- entry=100
            _bar(7200, 101, 1050, 70, 90),      # idx2 -- spike isolado: low=70<=stop(80)
            _bar(10800, 100, 103, 98, 101),     # idx3 -- nao confirma o nivel do spike
        ]
        self.assertEqual(vv3._toque_causal(bars, 1, 100.0, 80.0, 5.0), "stop")
        self.assertIsNone(vv3._toque_causal(bars, 1, 100.0, 80.0, 5.0, veto="amplo", peak=10_000.0))

    def test_montar_sinal_simples_nunca_corrige_amplo_corrige_e_volta_mais(self) -> None:
        bars = [
            _bar(0, 100, 150, 96, 100),         # idx0 -- high alto o bastante p/ nunca bater o simples
            _bar(3600, 101, 1050, 70, 90),      # idx1 (j0) -- spike isolado
            _bar(7200, 100, 103, 98, 101),      # idx2 -- nao confirma
        ]
        ev = EventV1(kind="ENTRADA", idx=0, ts=bars[0].ts, decision_ts=bars[0].ts,
                    data={"stop": 80.0, "TOPO": 10_000.0, "S": 0.0})
        s_simples = vv3._montar_sinal(bars, ev, "desconhecido", None, "ao_vivo", "CAT", "MINT1",
                                      "POOL1", "1h", None, None)
        s_amplo = vv3._montar_sinal(bars, ev, "desconhecido", None, "ao_vivo", "CAT", "MINT1",
                                    "POOL1", "1h", None, None, veto="amplo")
        self.assertIsNotNone(s_simples)
        self.assertIsNotNone(s_amplo)
        self.assertFalse(s_simples.entrada_corrigida)
        self.assertEqual(s_simples.entry_price, bars[1].open)
        self.assertTrue(s_amplo.entrada_corrigida)
        self.assertEqual(s_amplo.entry_price, bars[0].close)

    def test_tokens_excluidos_diagnostico_inclui_high(self) -> None:
        self.assertIn("HIGH", vv3.TOKENS_EXCLUIDOS_DIAGNOSTICO)
        self.assertIn("PEAK", vv3.TOKENS_EXCLUIDOS_DIAGNOSTICO)


class ResumoToquesTests(unittest.TestCase):
    def test_compara_contra_equilibrio_e_conta_indefinidos(self) -> None:
        bars_alvo = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 105, 95, 100),
            _bar(7200, 100, 111, 96, 105),
        ]
        bars_indef = [
            _bar(0, 100, 101, 99, 100),
            _bar(3600, 100, 102, 98, 100),
        ]
        s_alvo = _sinal(bars_alvo, ev_idx=0, stop=90.0, entry_price=100.0, pool="P1")
        s_indef = _sinal(bars_indef, ev_idx=0, stop=90.0, entry_price=100.0, pool="P2")
        out = vv3.resumo_toques([s_alvo, s_indef])
        d = out[1.0]
        self.assertEqual(d["n_decididos"], 1)
        self.assertEqual(d["n_indefinido"], 1)
        self.assertEqual(d["n_alvo"], 1)
        self.assertAlmostEqual(d["p_observado_pct"], 100.0)
        self.assertAlmostEqual(d["equilibrio_pct"], 50.0)   # 100/(1+1)
        self.assertAlmostEqual(d["delta_pct"], 50.0)


class ResumirPareamentoTests(unittest.TestCase):
    def test_media_mediana_sem_top3_ic90_e_n_corretos(self) -> None:
        valores_por_token = {"A": [1.0, 2.0], "B": [3.0], "C": [10.0]}   # 10.0 e o maior, saida no sem_top3
        p = vv3._resumir_pareamento(valores_por_token)
        self.assertEqual(p.n, 4)
        self.assertAlmostEqual(p.media, (1.0 + 2.0 + 3.0 + 10.0) / 4.0)
        self.assertAlmostEqual(p.mediana, 2.5)
        self.assertAlmostEqual(p.sem_top3, 1.0)   # remove os 3 maiores (10,3,2), so sobra o 1.0

    def test_sem_top3_remove_os_3_maiores(self) -> None:
        p = vv3._resumir_pareamento({"A": [1.0, 2.0, 3.0, 4.0, 100.0, 200.0, 300.0]})
        self.assertEqual(p.n, 7)
        self.assertAlmostEqual(p.sem_top3, (1.0 + 2.0 + 3.0 + 4.0) / 4.0)

    def test_vazio_devolve_tudo_none(self) -> None:
        p = vv3._resumir_pareamento({})
        self.assertEqual(p.n, 0)
        self.assertIsNone(p.media)
        self.assertIsNone(p.ic90_bootstrap)


class PareamentoRodada9Tests(unittest.TestCase):
    """Rodada 2026-11-05 (9), itens 1 e 3: pareamento por TOQUE (MESMOS 10 controles do pareamento em
    R@72h) e comparador de entrada ALEATORIA (K=20, semente propria). Bars sinteticos em escala de MC
    (`_bars_mc_elegiveis`) so pra exercitar a mecanica -- sem pretensao de realismo de mercado."""

    def setUp(self) -> None:
        self.bars = _bars_mc_elegiveis()
        self.sinal = _sinal(self.bars, ev_idx=1, created_ts=0.0, pool="POOL1", token="CAT")
        self.params = load_params_v3()

    def test_controles_e_aleatorios_usam_sementes_independentes(self) -> None:
        controles = vv3._controles_indices(self.sinal, self.params)
        aleatorios = vv3._aleatorios_indices(self.sinal, self.params)
        self.assertEqual(len(controles), 10)   # N_CONTROLES_PADRAO, populacao >= 10
        self.assertGreater(len(aleatorios), 10)   # K=20, populacao >= 20
        self.assertLessEqual(len(aleatorios), 20)
        self.assertNotEqual(set(controles), set(aleatorios))   # sorteio independente, nunca o mesmo

    def test_r72h_e_toque_de_indices_resolvem_pros_mesmos_controles(self) -> None:
        costs = CostModel()
        indices = vv3._controles_indices(self.sinal, self.params)
        valores_r = vv3._r72h_de_indices(self.sinal, indices, self.params, costs, now=1e12)
        valores_toque = vv3._toques_de_indices(self.sinal, indices, vv3.ALVO_PAREAMENTO_TOQUE)
        self.assertTrue(valores_r)
        self.assertTrue(valores_toque)
        self.assertTrue(all(v in (0.0, 1.0) for v in valores_toque))
        # rampa no fim da serie: todo controle na faixa plana toca o alvo antes do stop (nunca stop).
        self.assertTrue(all(v == 1.0 for v in valores_toque))

    def test_calcular_equilibrio_empirico_agrega_por_token_e_alvo(self) -> None:
        out = vv3.calcular_equilibrio_empirico([self.sinal], self.params)
        self.assertEqual(set(out), set(vv3.ALVOS_R))
        for alvo in vv3.ALVOS_R:
            d = out[alvo]
            self.assertGreater(d["n_draws"], 0)
            self.assertEqual(d["n_tokens"], 1)
            self.assertAlmostEqual(d["p_empirico_pct"], 100.0)   # rampa garante alvo em todo sorteio

    def test_sem_created_ts_nunca_sorteia_nada(self) -> None:
        sinal_sem_idade = _sinal(self.bars, ev_idx=1, created_ts=None, pool="POOL1")
        self.assertEqual(vv3._controles_indices(sinal_sem_idade, self.params), [])
        self.assertEqual(vv3._aleatorios_indices(sinal_sem_idade, self.params), [])


class TokenSignalSeqTests(unittest.TestCase):
    """Rodada 10, item 2: ordem do sinal DENTRO do token, calculada offline (replay/retro)."""

    def test_ordena_por_t_entrada_crescente_dentro_do_token(self) -> None:
        bars = _bars_mc_elegiveis()
        s_2a = _sinal(bars, ev_idx=1, token="CAT", t_entrada=300.0)
        s_1a = _sinal(bars, ev_idx=1, token="CAT", t_entrada=100.0)
        s_outro_token = _sinal(bars, ev_idx=1, token="DOG", t_entrada=50.0)
        seq = vv3.calcular_token_signal_seq([s_2a, s_1a, s_outro_token])
        self.assertEqual(seq[1], 1)   # s_1a (indice 1, t=100) e a 1a tentativa de CAT
        self.assertEqual(seq[0], 2)   # s_2a (indice 0, t=300) e a 2a tentativa de CAT
        self.assertEqual(seq[2], 1)   # DOG so tem 1 sinal -- sempre seq=1

    def test_3a_tentativa_tambem_conta(self) -> None:
        bars = _bars_mc_elegiveis()
        sinais = [_sinal(bars, ev_idx=1, token="CAT", t_entrada=t) for t in (100.0, 200.0, 300.0)]
        seq = vv3.calcular_token_signal_seq(sinais)
        self.assertEqual([seq[i] for i in range(3)], [1, 2, 3])

    def test_clones_de_mesmo_ticker_mints_diferentes_contam_1a_tentativa_cada(self) -> None:
        # RODADA 17 (achado A2): 2 tokens distintos com o MESMO ticker "CAT" nunca podem ser
        # tratados como "a 2a tentativa do mesmo token" -- cada um e seq=1 (1a e UNICA tentativa dele).
        bars = _bars_mc_elegiveis()
        s_clone_a = _sinal(bars, ev_idx=1, token="CAT", mint="MINT_A", t_entrada=100.0)
        s_clone_b = _sinal(bars, ev_idx=1, token="CAT", mint="MINT_B", t_entrada=200.0)
        seq = vv3.calcular_token_signal_seq([s_clone_a, s_clone_b])
        self.assertEqual(seq[0], 1)
        self.assertEqual(seq[1], 1)


def _sinal_mc(bars: list[Bar], token: str, t_entrada: float, mint: str | None = None) -> vv3.SinalVarredura:
    """`_sinal` escalado pra bars em MC (`_bars_mc_elegiveis`) -- stop/topo/entry_price precisam
    estar na MESMA escala dos bars (senao `simulate_v1` cancela a entrada por invalida)."""
    return _sinal(bars, ev_idx=1, token=token, mint=mint, t_entrada=t_entrada, stop=100_000.0,
                 topo=5_000_000.0, entry_price=150_000.0)


class ResumoR72hPorOrdemSinalTests(unittest.TestCase):
    """Rodada 10, item 2: reconciliacao R carteira x varredura -- R@72h MTM separado por 1a
    tentativa (seq==1) vs reentradas (seq>=2), e variante sem MOGZ/PEAK."""

    def test_separa_1a_tentativa_de_reentrada_por_token(self) -> None:
        bars = _bars_mc_elegiveis()
        primeira = _sinal_mc(bars, "CAT", float(bars[2].ts))
        reentrada = _sinal_mc(bars, "CAT", float(bars[10].ts))
        resumo = vv3.resumo_r72h_por_ordem_sinal([primeira, reentrada], now=1e12)
        self.assertEqual(resumo.primeira_tentativa.n, 1)
        self.assertEqual(resumo.reentradas.n, 1)

    def test_tokens_excluidos_saem_so_da_variante_sem_outliers(self) -> None:
        bars = _bars_mc_elegiveis()
        normal = _sinal_mc(bars, "CAT", float(bars[2].ts))
        outlier = _sinal_mc(bars, "MOGZ", float(bars[2].ts))
        resumo = vv3.resumo_r72h_por_ordem_sinal([normal, outlier], now=1e12)
        self.assertEqual(resumo.primeira_tentativa.n, 2)            # inclui MOGZ
        self.assertEqual(resumo.primeira_tentativa_sem_outliers.n, 1)   # exclui MOGZ

    def test_segunda_tentativa_do_mesmo_token_sem_outlier_nunca_afeta_a_1a(self) -> None:
        bars = _bars_mc_elegiveis()
        primeira = _sinal_mc(bars, "PEAK", float(bars[2].ts))
        reentrada = _sinal_mc(bars, "PEAK", float(bars[10].ts))
        resumo = vv3.resumo_r72h_por_ordem_sinal([primeira, reentrada], now=1e12)
        self.assertEqual(resumo.primeira_tentativa.n, 1)
        self.assertEqual(resumo.reentradas.n, 1)
        self.assertEqual(resumo.primeira_tentativa_sem_outliers.n, 0)   # PEAK excluido
        self.assertEqual(resumo.reentradas_sem_outliers.n, 0)

    def test_clones_de_mesmo_ticker_nunca_contam_como_1a_tentativa_e_reentrada(self) -> None:
        # RODADA 17 (achado A2): 2 sinais com o MESMO ticker "CAT" mas MINTS diferentes (clones) --
        # antes da correcao, o 2o entraria como "reentrada" do 1o; agora, cada um e sua propria
        # "1a tentativa" (seq=1 nos 2), entao os 2 caem em `primeira_tentativa`, nenhum em `reentradas`.
        bars = _bars_mc_elegiveis()
        clone_a = _sinal_mc(bars, "CAT", float(bars[2].ts), mint="MINT_A")
        clone_b = _sinal_mc(bars, "CAT", float(bars[10].ts), mint="MINT_B")
        resumo = vv3.resumo_r72h_por_ordem_sinal([clone_a, clone_b], now=1e12)
        self.assertEqual(resumo.primeira_tentativa.n, 2)
        self.assertEqual(resumo.reentradas.n, 0)


class CreatedTsAdmitidoTests(unittest.TestCase):
    """Regressao do BUG corrigido na rodada 9, item 2: `carregar_universo_admitido` fixava
    `created_ts=None` sempre, zerando SEMPRE o pareamento com controles desta origem (`
    candidatos_elegiveis` nunca elege nada sem `created_ts`)."""

    def test_sinais_do_universo_admitido_carregam_created_ts_real(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="varredura_v3_createdts_"))
        try:
            storage = Storage(make_paths(tmp))
            db_path = storage.paths.db
            storage.close()
            con = sqlite3.connect(str(db_path))
            con.execute(
                "INSERT INTO pr_pools (pool, symbol, status, l_bc, grad_ts, info) VALUES (?,?,?,?,?,?)",
                ("POOL1", "CAT", "ativo", L_BC, GRAD, json.dumps({"criado_ts": CREATED})),
            )
            bars = textbook_v1().bars
            con.executemany(
                "INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES ('POOL1','1h',?,?,?,?,?,?,?)",
                [(b.ts, b.open, b.high, b.low, b.close, b.volume, int(b.filled)) for b in bars],
            )
            con.commit()
            con.close()
            sinais = vv3.carregar_universo_admitido(db_path)
            self.assertTrue(sinais, "fixture deveria gerar >=1 ENTRADA sob ParamsV3")
            self.assertTrue(all(s.created_ts == CREATED for s in sinais))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ExecutarSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="varredura_v3_"))
        storage = Storage(make_paths(self.tmp))
        self.db_path = storage.paths.db
        storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha(self) -> None:
        texto = vv3.executar(self.db_path, progresso=False)
        self.assertIn(vv3.AVISO, texto)
        self.assertNotIn("Traceback", texto)

    def test_pool_admitido_real_gera_sinais_no_relatorio(self) -> None:
        # Mesmo fixture ja usado por test_avaliar_v3_retro.py -- gera >=1 ENTRADA sob ParamsV3
        # (sem lookahead, zero historico sintetico pensado pra este teste).
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "INSERT INTO pr_pools (pool, symbol, status, l_bc, grad_ts, info) VALUES (?,?,?,?,?,?)",
            ("POOL1", "CAT", "ativo", L_BC, GRAD, json.dumps({"criado_ts": CREATED})),
        )
        bars = textbook_v1().bars
        con.executemany(
            "INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES ('POOL1','1h',?,?,?,?,?,?,?)",
            [(b.ts, b.open, b.high, b.low, b.close, b.volume, int(b.filled)) for b in bars],
        )
        con.commit()
        con.close()
        texto = vv3.executar(self.db_path, progresso=False)
        self.assertIn("## universo_admitido", texto)
        self.assertNotIn("Traceback", texto)

    def test_csv_path_grava_arquivo_quando_ha_resultado(self) -> None:
        csv_path = self.tmp / "out.csv"
        texto = vv3.executar(self.db_path, csv_path=csv_path, progresso=False)
        self.assertTrue(csv_path.exists())
        self.assertIn(str(csv_path), texto)

    def test_ram_insuficiente_levanta_e_nunca_roda(self) -> None:
        disponivel = vv3.ram_disponivel_mb()
        if disponivel is None:
            self.skipTest("ram_disponivel_mb indisponivel neste ambiente (nao-Linux)")
        with self.assertRaises(vv3.RamInsuficienteError):
            vv3.executar(self.db_path, min_ram_mb=10 ** 9)


if __name__ == "__main__":
    unittest.main()
