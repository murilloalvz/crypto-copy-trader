"""PEDIDO 2026-11-05 (autorizado): testes de `pos_runner/horizonte_fixo.py` -- causalidade (zero
lookahead: a serie e truncada no corte ANTES de simular), os 4 desfechos (pendente/resolvido_regra/
marcado/sem_dado) e o congelamento do texto da emenda por hash."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import EventV1
from ..pos_runner.horizonte_fixo import (
    EmendaAlteradaError,
    calcular_r_horizonte,
    garantir_emenda_registrada,
    hash_da_emenda,
)
from ..pos_runner.params_v1 import load_params_v1
from ..pos_runner.simulate_v1 import simulate_v1
from ..scripts import horizonte_fixo as hf_script
from ..storage import Storage
from .test_exit_lab import _bars_vol

STEP = 3_600
PARAMS = load_params_v1()
COSTS = CostModel()


def _evento(idx: int, ts: int, stop: float, topo: float, s: float) -> EventV1:
    return EventV1(kind="ENTRADA", idx=idx, ts=ts, decision_ts=ts, data={"stop": stop, "TOPO": topo, "S": s})


class HorizontePendenteTests(unittest.TestCase):
    def test_pendente_quando_o_horizonte_ainda_nao_decorreu(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0)])
        ev = _evento(0, bars[0].ts, stop=80.0, topo=10_000.0, s=50.0)
        r = calcular_r_horizonte(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                 horizonte_s=2 * STEP, now=bars[1].ts + STEP)
        self.assertEqual(r.status, "pendente")
        self.assertIsNone(r.r_mult)


class HorizonteResolvidoPelaRegraTests(unittest.TestCase):
    def test_stop_batido_antes_do_corte_usa_o_r_realizado_da_regra(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0),   # idx0 -- candle anterior
            (100, 102, 96, 101, 10.0),   # idx1 -- entry=100
            (101, 102, 70, 75, 10.0),    # idx2 -- low=70 <= stop(80) -- fecha AQUI, antes do corte
            (75, 80, 74, 78, 10.0),      # idx3 -- so existe pra provar que o corte nem precisa dele
        ])
        ev = _evento(0, bars[0].ts, stop=80.0, topo=10_000.0, s=50.0)
        t_entrada = bars[1].ts
        r = calcular_r_horizonte(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=t_entrada,
                                 horizonte_s=2 * STEP, now=t_entrada + 5 * STEP)
        self.assertEqual(r.status, "resolvido_regra")
        self.assertIsNotNone(r.r_mult)
        self.assertLess(r.r_mult, 0.0)   # fechou no stop -- R negativo


class HorizonteMarcadoSemLookaheadTests(unittest.TestCase):
    def test_marca_no_ultimo_candle_limpo_ate_o_corte_nunca_olhando_o_stop_batido_depois(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0),    # idx0 ts=1000  -- candle anterior
            (100, 102, 96, 101, 10.0),    # idx1 ts=4600  -- entry=100
            (101, 103, 95, 102, 10.0),    # idx2 ts=8200
            (102, 104, 95, 103, 10.0),    # idx3 ts=11800 -- ULTIMO ate o corte (t_entrada+2*STEP=11800)
            (103, 104, 70, 72, 10.0),     # idx4 ts=15400 -- DEPOIS do corte: bateria o stop(80) aqui,
                                          # mas isso nunca pode influenciar o resultado no corte.
        ])
        t_entrada = bars[1].ts
        ev = _evento(0, bars[0].ts, stop=80.0, topo=10_000.0, s=50.0)
        r = calcular_r_horizonte(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=t_entrada,
                                 horizonte_s=2 * STEP, now=t_entrada + 10 * STEP)
        self.assertEqual(r.status, "marcado")
        self.assertEqual(r.candle_marca_ts, bars[3].ts)   # marcado no idx3 -- NUNCA no idx4 (fora do corte)
        self.assertIsNotNone(r.r_mult)
        # a serie completa (com idx4) bateria o stop(80) -- R bem mais negativo que o marcado no corte,
        # que nunca pode "ver" esse candle futuro.
        ev_full = _evento(0, bars[0].ts, stop=80.0, topo=10_000.0, s=50.0)
        r_full = calcular_r_horizonte(bars, ev_full, PARAMS, COSTS, "desconhecido", None,
                                      t_entrada=t_entrada, horizonte_s=4 * STEP, now=t_entrada + 10 * STEP)
        self.assertEqual(r_full.status, "resolvido_regra")
        self.assertLess(r_full.r_mult, r.r_mult)

    def test_sem_nenhum_candle_limpo_ate_o_corte_fica_pendente(self) -> None:
        bars_sujos = [b for b in _bars_vol([
            (100, 101, 99, 100, 0.0), (100, 102, 96, 101, 0.0), (101, 103, 95, 102, 0.0),
        ])]   # volume=0.0 -- TODO candle e `candle_corrompido_provavel`
        t_entrada = bars_sujos[1].ts
        ev = _evento(0, bars_sujos[0].ts, stop=80.0, topo=10_000.0, s=50.0)
        r = calcular_r_horizonte(bars_sujos, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=t_entrada,
                                 horizonte_s=STEP, now=t_entrada + 5 * STEP)
        self.assertEqual(r.status, "pendente")


class VetoDeCandleCorrompidoTests(unittest.TestCase):
    """RODADA 17 (achado P1 da Parte B da auditoria 2026-11-10): `calcular_r_horizonte` agora passa
    o MESMO veto de candle corrompido que o caminho ao vivo ja aplica (`qualidade_candle.
    candle_confiavel_cb`) -- um candle isolado/suspeito nunca pode decidir o stop, mesma classe de
    falha do incidente real do McRib -561R."""

    def _bars_com_spike_isolado(self) -> list:
        return _bars_vol([
            (100, 101, 99, 100, 10.0),    # idx0 ts=1000  -- candle anterior
            (100, 102, 96, 101, 10.0),    # idx1 ts=4600  -- entry=100
            (101, 5_000, 70, 90, 10.0),   # idx2 ts=8200  -- SPIKE isolado: high=5000 (>>10x o vizinho),
                                          # low=70 <= stop(80) -- bateria o stop SE decidisse aqui.
            (103, 104, 102, 103, 10.0),   # idx3 ts=11800 -- NAO confirma o nivel do spike (volta ao
                                          # normal) -- idx2 fica "candle_isolado_vs_vizinhos", vetado.
                                          # low=102 > stop(80): este candle, por si so, NUNCA bate o stop.
        ])

    def test_spike_isolado_nunca_decide_o_stop_fica_marcado_no_candle_limpo_seguinte(self) -> None:
        bars = self._bars_com_spike_isolado()
        t_entrada = bars[1].ts
        ev = _evento(0, bars[0].ts, stop=80.0, topo=10_000.0, s=50.0)
        r = calcular_r_horizonte(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=t_entrada,
                                 horizonte_s=2 * STEP, now=t_entrada + 10 * STEP)
        # com o veto: idx2 (spike) nunca resolve o trade -- idx3 (limpo, nao bate o stop) e o fim da
        # serie truncada -- marcado a mercado no close de idx3 (103), NUNCA resolvido pela regra no
        # stop batido do spike.
        self.assertEqual(r.status, "marcado")
        self.assertEqual(r.candle_marca_ts, bars[3].ts)
        self.assertIsNotNone(r.r_mult)
        # custos conservadores (dex "desconhecido") deixam o R marcado levemente negativo mesmo com
        # close(103) > entry(100) -- mas MUITO menos negativo que o stop batido no spike (ver teste
        # seguinte, que prova quanto pior seria SEM o veto: ~-1.27R vs ~-0.20R aqui).
        self.assertGreater(r.r_mult, -0.5)

    def test_sem_o_veto_o_mesmo_spike_bateria_o_stop_um_resultado_bem_mais_negativo(self) -> None:
        # Mesma serie truncada, mesmo evento, chamando `simulate_v1` DIRETO sem `candle_confiavel`
        # (comportamento ANTES da correcao desta rodada) -- confirma que o spike isolado teria, sim,
        # decidido o stop se o veto nao existisse, com um R bem mais negativo (~-1,27R) que o marcado
        # com o veto (~-0,20R) -- prova que a correcao muda o resultado de verdade, nunca um teste
        # vazio que passaria de qualquer jeito.
        bars = self._bars_com_spike_isolado()
        ev = _evento(0, bars[0].ts, stop=80.0, topo=10_000.0, s=50.0)
        bars_truncados = [b for b in bars if b.ts <= bars[3].ts]
        res_sem_veto = simulate_v1(bars_truncados, ev, PARAMS, COSTS, "desconhecido", None, lambda _t: None)
        self.assertEqual(res_sem_veto.status, "fechado")
        self.assertEqual(res_sem_veto.reason, "stop")
        r_mult_sem_veto = res_sem_veto.net_ret / res_sem_veto.risk_frac
        self.assertLess(r_mult_sem_veto, -1.0, "sem o veto, bate o stop no spike -- R bem mais negativo")

        t_entrada = bars[1].ts
        r_com_veto = calcular_r_horizonte(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=t_entrada,
                                          horizonte_s=2 * STEP, now=t_entrada + 10 * STEP)
        self.assertGreater(r_com_veto.r_mult, r_mult_sem_veto,
                           "com o veto, o resultado precisa ser bem melhor que o stop batido no spike")

    def test_veto_simples_explicito_bate_o_stop_onde_o_amplo_vetaria(self) -> None:
        """RODADA 18 item 2: candle isolado cujo salto e >10x o CLOSE do vizinho anterior mas NUNCA
        >10x o HIGH de ambos os vizinhos (o veto simples exige os 2) -- o amplo veta, o simples (opt-
        in via `veto='simples'`) NAO veta e bate o stop nele, prova que o parametro de fato alterna
        entre os 2 vetos (nunca uma 3a implementacao divergente)."""
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0),    # idx0
            (100, 150, 96, 101, 10.0),    # idx1 -- entry=100
            (101, 1050, 70, 90, 10.0),    # idx2 -- spike isolado: low=70<=stop(80)
            (100, 103, 98, 101, 10.0),    # idx3 -- nao confirma o nivel do spike
        ])
        ev = _evento(0, bars[0].ts, stop=80.0, topo=10_000.0, s=50.0)
        t_entrada = bars[1].ts
        r_amplo = calcular_r_horizonte(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=t_entrada,
                                       horizonte_s=2 * STEP, now=t_entrada + 10 * STEP, veto="amplo")
        r_simples = calcular_r_horizonte(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=t_entrada,
                                         horizonte_s=2 * STEP, now=t_entrada + 10 * STEP, veto="simples")
        self.assertEqual(r_amplo.status, "marcado", "amplo veta idx2 -- marca no idx3 limpo")
        self.assertEqual(r_simples.status, "resolvido_regra", "simples nunca veta idx2 -- bate o stop nele")
        self.assertLess(r_simples.r_mult, -1.0)
        self.assertGreater(r_amplo.r_mult, r_simples.r_mult)


class HorizonteSemDadoTests(unittest.TestCase):
    def test_entrada_cancelada_fora_do_stop_topo_fica_sem_dado(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (70, 101, 69, 100, 10.0)])   # open(70) <= stop(80)
        ev = _evento(0, bars[0].ts, stop=80.0, topo=10_000.0, s=50.0)
        r = calcular_r_horizonte(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                 horizonte_s=STEP, now=bars[1].ts + 5 * STEP)
        self.assertEqual(r.status, "sem_dado")


class EmendaHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="horizonte_fixo_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_1a_chamada_registra_e_as_seguintes_sao_idempotentes(self) -> None:
        h1 = garantir_emenda_registrada(self.storage)
        h2 = garantir_emenda_registrada(self.storage)
        self.assertEqual(h1, h2)
        self.assertEqual(h1, hash_da_emenda())

    def test_texto_alterado_depois_do_registro_recusa(self) -> None:
        garantir_emenda_registrada(self.storage)
        self.storage.set_meta("emenda_horizonte_fixo_hash", "0" * 12)
        with self.assertRaises(EmendaAlteradaError):
            garantir_emenda_registrada(self.storage)


class ScriptAoVivoTests(unittest.TestCase):
    """PEDIDO 2026-11-05 (autorizado): `scripts/horizonte_fixo.py` -- calcula/persiste pra sinais AO
    VIVO de V1 (sinal + controle pareado via `pr_baseline`), nunca escreve fora de
    `pr_horizonte_fixo`."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="horizonte_fixo_script_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _preparar_sinal_aberto(self) -> int:
        signal_id = self.storage.pr1_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "aberto", "entry_price": 100.0, "stop": 80.0, "topo": 10_000.0,
            "s_suporte": 50.0,
        })
        self.storage.pr_trajetoria_upsert("v1", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                          mint="MINT1", symbol="CAT", t_entrada=4_600.0, preco_entrada=100.0,
                                          risco_pct=20.0, r_unidade=20.0, fonte_candle="gt")
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0),
            (101, 103, 95, 102, 10.0), (102, 104, 95, 103, 10.0),
        ])
        self.storage.pr_append_bars("POOL1", "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume,
                                                     int(b.filled)) for b in bars])
        self.storage.pr_baseline_upsert("v1", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                        mint="MINT1", symbol="CAT", n_controles=0, controles_json="[]")
        return signal_id

    def test_persiste_uma_linha_marcada_por_horizonte_para_sinal_em_aberto(self) -> None:
        signal_id = self._preparar_sinal_aberto()
        hf_script.calcular_e_persistir_ao_vivo(self.storage, "v1", now=10_000_000.0)
        row = self.storage.pr_horizonte_fixo_get("v1", "ao_vivo", str(signal_id), "72h")
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "marcado")
        self.assertEqual(row["mint"], "MINT1")

    def test_relatorio_mostra_abertos_fechados_e_contagem_por_horizonte(self) -> None:
        self._preparar_sinal_aberto()
        hf_script.calcular_e_persistir_ao_vivo(self.storage, "v1", now=10_000_000.0)
        texto = hf_script.relatorio(self.storage, now=10_000_000.0)
        self.assertIn("V1: abertos=1 | fechados=0", texto)
        self.assertIn("horizonte 72h: marcado=1", texto)

    def test_controle_pareado_entra_no_dif_pareada_quando_definido(self) -> None:
        signal_id = self._preparar_sinal_aberto()
        # controle no idx0 (candle anterior a entrada) -- idx+1 existe (idx1), MESMA mecanica de
        # `evidencia.evento_controle`.
        self.storage.pr_baseline_upsert("v1", signal_id, 0.0, controles_json='[{"idx": 0, "status": '
                                        '"pendente", "r_controle": null}]')
        hf_script.calcular_e_persistir_ao_vivo(self.storage, "v1", now=10_000_000.0)
        row = self.storage.pr_horizonte_fixo_get("v1", "ao_vivo", str(signal_id), "72h")
        self.assertIsNotNone(row["r_controle_medio"])
        self.assertAlmostEqual(row["dif_pareada"], row["r_mult"] - row["r_controle_medio"])

    def test_executar_registra_a_emenda_e_devolve_o_relatorio(self) -> None:
        self._preparar_sinal_aberto()
        texto = hf_script.executar(self.storage.paths.db)
        self.assertIn("Horizonte fixo (72h/7d)", texto)
        self.assertIsNotNone(self.storage.get_meta("emenda_horizonte_fixo_hash"))


if __name__ == "__main__":
    unittest.main()
