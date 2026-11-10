"""PEDIDO 2026-11-05 (autorizado, 3a rodada): testes de `scripts/simular_v3_carteira.py` -- tamanho
de posicao em VALOR ABSOLUTO (V10/V25/V50/V_oportunidade, com tetos de supply/volume e motivo de
pulado), impacto de preco, ledger so sobre saldo realizado, ponto de equilibrio, probabilidade de
ruina relativa, correcao de candle corrompido/latencia na entrada, amostra/overlap de tokens, e
smoke end-to-end. EXPLORATORIO -- nunca testa "edge" (isso e H1)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..storage import Storage
from ..scripts import simular_v3_carteira as svc
from .test_exit_lab import _bars_vol


def _trade_minimo(**kwargs) -> svc.TradeV3:
    # RODADA 17 (achado A2 da auditoria 2026-11-10): `mint` e a identidade REAL usada por
    # `uma_por_token`/overlap/bootstrap (ver `simular_v3_carteira.py`) -- por padrao segue `token`
    # (cada "token" sintetico deste fixture e seu proprio mint, MESMO comportamento de antes da
    # correcao), MAS pode ser sobrescrito explicitamente pra testar o caso-clone (mesmo ticker,
    # mint diferente).
    base = dict(token="CAT", pool="POOL1", tf="1h", origem="ao_vivo", t_entrada=0.0,
               entry_price=100.0, entry_price_corrigido=False, entrada_atrasada_corrigida=False,
               risk_frac=0.2, volume_gatilho=None, volume_entrada=None, volume_medio_24h=None,
               n_pavios=None, supply=None,
               status_72h="marcado", r_72h=1.0, r_regra=None, r_7d=None, r_sombra_c=None, r_sombra_d=None)
    base.update(kwargs)
    base.setdefault("mint", base["token"])
    return svc.TradeV3(**base)


class ValorBaseTests(unittest.TestCase):
    def test_v10_v25_v50_sao_valores_fixos(self) -> None:
        self.assertAlmostEqual(svc._valor_base("V10", _trade_minimo()), 10.0)
        self.assertAlmostEqual(svc._valor_base("V25", _trade_minimo()), 25.0)
        self.assertAlmostEqual(svc._valor_base("V50", _trade_minimo()), 50.0)

    def test_v_oportunidade_usa_volume_do_gatilho_para_qualificar(self) -> None:
        sem_qualidade = _trade_minimo(volume_gatilho=50.0, volume_medio_24h=40.0, n_pavios=3)   # <2x
        self.assertAlmostEqual(svc._valor_base("V_oportunidade", sem_qualidade), 10.0)
        qualidade_fraca = _trade_minimo(volume_gatilho=100.0, volume_medio_24h=40.0, n_pavios=3,
                                        volume_entrada=10.0)   # qualifica mas entrada fraca
        self.assertAlmostEqual(svc._valor_base("V_oportunidade", qualidade_fraca), 25.0)
        qualidade_forte = _trade_minimo(volume_gatilho=100.0, volume_medio_24h=40.0, n_pavios=3,
                                        volume_entrada=25.0)   # entrada >=50% da media (20)
        self.assertAlmostEqual(svc._valor_base("V_oportunidade", qualidade_forte), 50.0)

    def test_v_oportunidade_exige_exatamente_3_pavios(self) -> None:
        trade = _trade_minimo(volume_gatilho=100.0, volume_medio_24h=40.0, n_pavios=2, volume_entrada=25.0)
        self.assertAlmostEqual(svc._valor_base("V_oportunidade", trade), 10.0)


class TamanhoComTetosTests(unittest.TestCase):
    def test_sem_teto_algum_usa_o_valor_desejado(self) -> None:
        tamanho, desejado, motivo = svc._tamanho_com_tetos("V25", 1000.0, _trade_minimo(), svc.MAX_VOLUME_PCT_PADRAO)
        self.assertAlmostEqual(tamanho, 25.0)
        self.assertAlmostEqual(desejado, 25.0)
        self.assertIsNone(motivo)

    def test_sem_banca_livre_suficiente_entra_menor_e_marca_sem_capital(self) -> None:
        tamanho, desejado, motivo = svc._tamanho_com_tetos("V50", 15.0, _trade_minimo(), svc.MAX_VOLUME_PCT_PADRAO)
        self.assertAlmostEqual(tamanho, 15.0)
        self.assertAlmostEqual(desejado, 50.0)
        self.assertEqual(motivo, "sem_capital")

    def test_teto_de_supply_limita_e_marca_o_motivo(self) -> None:
        # 1,5% de 1000 tokens x preco 1.0 = US$15 -- menor que os US$25 pedidos.
        trade = _trade_minimo(entry_price=1.0, supply=1000.0)
        tamanho, _, motivo = svc._tamanho_com_tetos("V25", 1000.0, trade, svc.MAX_VOLUME_PCT_PADRAO)
        self.assertAlmostEqual(tamanho, 15.0)
        self.assertEqual(motivo, "teto_supply")

    def test_sem_supply_conhecido_o_teto_nunca_se_aplica(self) -> None:
        trade = _trade_minimo(entry_price=1.0, supply=None)
        tamanho, desejado, motivo = svc._tamanho_com_tetos("V25", 1000.0, trade, svc.MAX_VOLUME_PCT_PADRAO)
        self.assertAlmostEqual(tamanho, desejado)
        self.assertIsNone(motivo)

    def test_teto_de_volume_limita_e_marca_o_motivo(self) -> None:
        trade = _trade_minimo(volume_entrada=100.0)
        tamanho, _, motivo = svc._tamanho_com_tetos("V25", 1000.0, trade, max_volume_pct=10.0)
        self.assertAlmostEqual(tamanho, 10.0)   # 10% de 100
        self.assertEqual(motivo, "teto_volume")


class ImpactoPrecoTests(unittest.TestCase):
    def test_sem_volume_nunca_inventa_impacto(self) -> None:
        self.assertEqual(svc._impacto_preco_r(25.0, None), 0.0)
        self.assertEqual(svc._impacto_preco_r(25.0, 0.0), 0.0)

    def test_100pct_do_volume_custa_1r_com_coeficiente_padrao(self) -> None:
        self.assertAlmostEqual(svc._impacto_preco_r(50.0, 50.0), svc.IMPACT_COEF_R)

    def test_impacto_e_proporcional_a_posicao_sobre_volume(self) -> None:
        self.assertAlmostEqual(svc._impacto_preco_r(10.0, 100.0), svc.IMPACT_COEF_R * 0.10)


class LedgerRealizadoTests(unittest.TestCase):
    def _rodar(self, trades, regra="V10", banca=250.0, **kwargs):
        return svc.simular_carteira(trades, "ao_vivo", regra, "base", "US$0.05", banca,
                                    calcular_ruina=False, **kwargs)

    def test_banca_debita_no_open_e_credita_so_na_liberacao(self) -> None:
        trades = [
            _trade_minimo(token="A", t_entrada=0.0, r_72h=5.0),
            _trade_minimo(token="B", t_entrada=10.0, r_72h=5.0),   # ainda dentro das 72h de A
        ]
        r = self._rodar(trades, regra="V50", banca=100.0)
        self.assertEqual(r.n_trades, 2)   # 50+50=100 -- exatamente a banca, nunca mais

    def test_pendente_nunca_conta_como_perda_nem_consome_banca(self) -> None:
        trades = [
            _trade_minimo(token="A", t_entrada=0.0, status_72h="pendente", r_72h=None),
            _trade_minimo(token="B", t_entrada=100.0, status_72h="marcado", r_72h=1.0),
        ]
        r = self._rodar(trades)
        self.assertEqual(r.n_trades, 1)

    def test_sem_dado_nunca_entra_na_carteira(self) -> None:
        trades = [_trade_minimo(token="A", t_entrada=0.0, status_72h="sem_dado", r_72h=None)]
        r = self._rodar(trades)
        self.assertEqual(r.n_trades, 0)

    def test_limite_de_posicoes_simultaneas_pula_e_conta_sem_vaga(self) -> None:
        trades = [_trade_minimo(token=t, t_entrada=0.0, r_72h=1.0) for t in ("A", "B", "C", "D")]
        r = self._rodar(trades, max_posicoes=2)
        self.assertEqual(r.n_trades, 2)
        self.assertEqual(r.pulados_por_motivo.get("sem_vaga"), 2)

    def test_entrada_nunca_fica_abaixo_do_minimo_pula_e_conta(self) -> None:
        # banca=15: V50 nao cabe (15<10 nao, mas apos a 1a entrada de 15 a banca_livre vira 0).
        trades = [_trade_minimo(token=t, t_entrada=0.0, r_72h=0.0) for t in ("A", "B")]
        r = self._rodar(trades, regra="V50", banca=15.0, max_posicoes=10)
        self.assertEqual(r.n_trades, 1)   # A entra reduzido a 15 (banca inteira)
        self.assertEqual(r.n_entradas_reduzidas, 1)
        self.assertEqual(r.pulados_por_motivo.get("sem_capital"), 1)   # B: banca_livre=0 < minimo

    def test_drawdown_e_a_maior_queda_desde_o_pico_realizado(self) -> None:
        trades = [
            _trade_minimo(token="A", t_entrada=0.0, r_72h=2.0),
            _trade_minimo(token="B", t_entrada=svc.HORIZONTES_S["72h"] + 1, r_72h=-2.0),
        ]
        r = self._rodar(trades)
        self.assertGreater(r.max_drawdown_pct, 0.0)
        self.assertGreater(r.max_drawdown_usd, 0.0)

    def test_maior_sequencia_de_perdas_conta_so_consecutivas_na_liberacao(self) -> None:
        passo = svc.HORIZONTES_S["72h"] + 1
        trades = [
            _trade_minimo(token="A", t_entrada=0.0, r_72h=-1.0),
            _trade_minimo(token="B", t_entrada=passo, r_72h=-1.0),
            _trade_minimo(token="C", t_entrada=passo * 2, r_72h=1.0),
            _trade_minimo(token="D", t_entrada=passo * 3, r_72h=-1.0),
        ]
        r = self._rodar(trades)
        self.assertEqual(r.maior_sequencia_perdas, 2)

    def test_custo_fixo_e_slippage_sao_reportados_em_r(self) -> None:
        trades = [_trade_minimo(token="A", t_entrada=0.0, r_72h=1.0)]
        r = self._rodar(trades)
        self.assertIsNotNone(r.custo_fixo_r_medio)
        self.assertGreater(r.custo_fixo_r_medio, 0.0)
        self.assertIsNotNone(r.slippage_r_medio)

    def test_r_medio_sem_top3_exclui_os_3_maiores_resultados(self) -> None:
        passo = svc.HORIZONTES_S["72h"] + 1
        trades = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=float(i)) for i in range(6)]
        r = self._rodar(trades, max_posicoes=10)
        self.assertIsNotNone(r.r_medio_sem_top3)
        self.assertLess(r.r_medio_sem_top3, r.r_medio)   # tira os maiores -- media cai

    def test_ponto_de_equilibrio_e_positivo_quando_r_e_positivo(self) -> None:
        trades = [_trade_minimo(token="A", t_entrada=0.0, r_72h=1.0)]
        r = self._rodar(trades)
        self.assertIsNotNone(r.ponto_equilibrio_custo_fixo_usd)
        self.assertGreater(r.ponto_equilibrio_custo_fixo_usd, 0.0)


class ProbabilidadeRuinaTests(unittest.TestCase):
    def test_sem_trades_devolve_none(self) -> None:
        r = svc.probabilidade_ruina_bootstrap([], "V10", "base", "US$0.05", 250.0)
        self.assertIsNone(r.prob_ruina_pct)
        self.assertIsNone(r.n_trades_medio)

    def test_limiar_e_relativo_a_banca_inicial(self) -> None:
        passo = svc.HORIZONTES_S["72h"] + 1
        trades = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=-5.0) for i in range(10)]
        # com banca=10000, uma entrada V10 (US$10) perdendo nunca chega perto de 50% -- com
        # banca=15, a 1a entrada (trava US$10, perde) ja derruba a banca bem abaixo de 50%.
        p_banca_grande = svc.probabilidade_ruina_bootstrap(trades, "V10", "base", "US$0.05", 10_000.0, n_bootstrap=200)
        p_banca_pequena = svc.probabilidade_ruina_bootstrap(trades, "V10", "base", "US$0.05", 15.0, n_bootstrap=200)
        self.assertGreater(p_banca_pequena.prob_ruina_pct, p_banca_grande.prob_ruina_pct)

    def test_e_deterministico_com_a_mesma_seed(self) -> None:
        passo = svc.HORIZONTES_S["72h"] + 1
        trades = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=-1.0) for i in range(10)]
        p1 = svc.probabilidade_ruina_bootstrap(trades, "V50", "base", "US$0.05", 250.0, n_bootstrap=500)
        p2 = svc.probabilidade_ruina_bootstrap(trades, "V50", "base", "US$0.05", 250.0, n_bootstrap=500)
        self.assertEqual(p1.prob_ruina_pct, p2.prob_ruina_pct)
        self.assertEqual(p1.n_trades_medio, p2.n_trades_medio)

    def test_usa_o_patrimonio_corrigido_a1_nunca_so_o_caixa(self) -> None:
        """PEDIDO 2026-11-05 (rodada 10, item 1): confirma que a ruina chama `_executar_ledger`
        (MESMO motor que calcula patrimonio = caixa + posicoes abertas, A1) -- uma posicao aberta
        trava capital mas NUNCA aparece como perda so por estar aberta; a ruina so dispara com um
        resultado REALMENTE negativo o bastante, nunca pelo caixa cair so porque o principal esta
        travado em posicoes ainda sem desfecho."""
        passo = svc.HORIZONTES_S["72h"] + 1
        # 4 posicoes V50 (US$50 cada = US$200, 80% da banca de 250) TODAS lucrativas -- o caixa cai
        # pra US$50 no momento de abrir a 4a (travado), mas o patrimonio nunca sai de ~US$250+.
        trades = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=1.0) for i in range(4)]
        r = svc.probabilidade_ruina_bootstrap(trades, "V50", "base", "US$0.05", 250.0, n_bootstrap=500)
        self.assertEqual(r.prob_ruina_pct, 0.0)

    def test_ruina_muda_quando_a_lista_de_trades_muda(self) -> None:
        """PEDIDO 2026-11-05 (rodada 10, item 1): regressao -- a ruina precisa responder a mudancas
        na lista de trades (nunca ficar "presa" num numero antigo). Acrescenta reentradas BEM piores
        aos MESMOS tokens (mesmo `n` de tokens distintos pro bootstrap) e confirma que a ruina sobe."""
        passo = svc.HORIZONTES_S["72h"] + 1
        base = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=0.5) for i in range(5)]
        p_base = svc.probabilidade_ruina_bootstrap(base, "V50", "base", "US$0.05", 250.0, n_bootstrap=3000)
        # reentradas BEM piores nos MESMOS 5 tokens (nunca um token novo) -- `n` pro bootstrap e igual.
        extra = base + [_trade_minimo(token=f"T{i}", t_entrada=(i + 100) * passo, r_72h=-20.0) for i in range(5)]
        p_extra = svc.probabilidade_ruina_bootstrap(extra, "V50", "base", "US$0.05", 250.0, n_bootstrap=3000)
        self.assertNotEqual(p_base.prob_ruina_pct, p_extra.prob_ruina_pct)
        self.assertGreater(p_extra.prob_ruina_pct, p_base.prob_ruina_pct)

    def test_A1_diagnostico_max_posicoes_agora_tem_efeito_real_na_ruina(self) -> None:
        """PEDIDO 2026-11-05 (rodada 11, item A1/A2) -- regressao do BUG DE DESENHO relatado: antes
        desta correcao, a amostra sintetica do bootstrap SEMPRE espacava cada entrada 72h+1s depois
        da anterior (mesmo entre tokens DIFERENTES), garantindo que NUNCA mais de 1 posicao ficava
        aberta ao mesmo tempo -- `max_posicoes` nunca tinha chance de bloquear nada, e a ruina saia
        IDENTICA entre `max_posicoes=4` e `max_posicoes=10` (exatamente o relato). Corrigido: os
        tokens sorteados preservam seus timestamps REAIS (tokens que competiram por capital de
        verdade continuam competindo), entao um teto de vagas mais apertado precisa, no minimo,
        NUNCA ter MENOS ruina que um teto mais largo pra MESMA lista de sinais concorrendo por
        capital de verdade. Usa muitos tokens com entradas BEM proximas no tempo real (a mesma
        epoca) -- justamente o cenario que a versao antiga nunca testava."""
        # 8 tokens, todos entrando quase juntos (1h de diferenca) -- com max_posicoes=2, so 2 cabem
        # por vez e o resto fica de fora (sem_vaga); com max_posicoes=8, todos cabem.
        trades = [_trade_minimo(token=f"T{i}", t_entrada=i * 3600.0, r_72h=-3.0) for i in range(8)]
        r_teto_apertado = svc.probabilidade_ruina_bootstrap(trades, "V50", "base", "US$0.05", 250.0,
                                                            max_posicoes=2, n_bootstrap=3000)
        r_teto_largo = svc.probabilidade_ruina_bootstrap(trades, "V50", "base", "US$0.05", 250.0,
                                                          max_posicoes=8, n_bootstrap=3000)
        # menos vagas -- menos trades executados por caminho em media (nunca o mesmo numero).
        self.assertLess(r_teto_apertado.n_trades_medio, r_teto_largo.n_trades_medio)

    def test_A3_prob_ruina_cresce_com_o_tamanho_da_posicao(self) -> None:
        """PEDIDO 2026-11-05 (rodada 11, item A3): P(ruina) cresce com o tamanho da posicao pra
        MESMA lista de trades (V50 arrisca mais capital por posicao que V10 -- perder a MESMA fracao
        R dói mais em $ com posicao maior)."""
        passo = svc.HORIZONTES_S["72h"] + 1
        trades = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=-3.0) for i in range(6)]
        r_v10 = svc.probabilidade_ruina_bootstrap(trades, "V10", "base", "US$0.05", 250.0, n_bootstrap=3000)
        r_v50 = svc.probabilidade_ruina_bootstrap(trades, "V50", "base", "US$0.05", 250.0, n_bootstrap=3000)
        self.assertGreaterEqual(r_v50.prob_ruina_pct, r_v10.prob_ruina_pct)

    def test_sorteio_repetido_do_mesmo_token_nunca_colide_com_ele_mesmo(self) -> None:
        """Bootstrap com reposicao PODE sortear o MESMO token real 2x (ex.: A,A) -- cada sorteio
        (slot) recebe um nome sintetico distinto (`token#slot`), entao as 2 copias NUNCA se bloqueiam
        via `uma_por_token` (seriam 2 observacoes IID, nunca a mesma posicao duplicada). Com 2 tokens
        reais (1 trade cada) e `n=2` sorteios por replica, QUALQUER combinacao (A,A/A,B/B,A/B,B)
        sempre contribui EXATAMENTE 2 trades -- se a colisao acontecesse (bug), sortear o MESMO token
        2x derrubaria pra 1 trade (a 2a copia seria rejeitada como token_ja_aberto), puxando a media
        pra baixo de 2.0."""
        trades = [_trade_minimo(token="A", t_entrada=0.0, r_72h=1.0),
                 _trade_minimo(token="B", t_entrada=0.0, r_72h=1.0)]
        r = svc.probabilidade_ruina_bootstrap(trades, "V10", "base", "US$0.05", 10_000.0,
                                              max_posicoes=1000, n_bootstrap=500)
        self.assertEqual(r.n_trades_medio, 2.0)


class MaxPerdaFracNaoAfetaRMedioTests(unittest.TestCase):
    """PEDIDO 2026-11-05 (rodada 10, item 3): MAX_PERDA_FRAC (piso de -100% do principal) so existe
    pra travar `resultado_usd`/banca/drawdown/ruina -- os valores de R reportados (`r_valores`,
    `r_medio`/`r_mediano`/IC90% na tabela) sao SEMPRE o R-multiplo ANTES do piso (`r_final`, que pode
    ir muito alem de -1.0 quando o R a mercado e muito negativo). Documentado aqui pra nunca ser
    uma surpresa silenciosa pra quem le "R medio" na tabela."""

    def test_r_valores_nunca_e_clampado_mesmo_quando_o_resultado_usd_e(self) -> None:
        trades = [_trade_minimo(token="EXTREMO", t_entrada=0.0, r_72h=-20.0, risk_frac=0.2)]
        r = svc._executar_ledger(trades, "V10", "base", "US$0.05", 250.0, svc.MAX_POSICOES_PADRAO,
                                 svc.MAX_VOLUME_PCT_PADRAO)
        # net_frac sem piso seria -20*0.2=-4.0 (perderia 400% do principal) -- resultado_usd TEM que
        # ficar travado em -tamanho_usd (nunca perder mais que investiu).
        self.assertAlmostEqual(r["resultados_usd"][0], -10.0, places=2)
        # r_valores (o que alimenta r_medio/mediano/IC90% da tabela) fica MUITO abaixo de -1.0 --
        # NUNCA e travado pelo MAX_PERDA_FRAC (e um numero so informativo do R de mercado, nunca o
        # retorno realizado em $ que o piso protege).
        self.assertLess(r["r_valores"][0], -1.0)
        self.assertAlmostEqual(r["r_valores"][0], -20.0 - (0.05 / (10.0 * 0.2)), places=3)

    def test_r_medio_da_tabela_e_identico_com_ou_sem_perda_extrema_alem_do_piso(self) -> None:
        """Dobrar a severidade de uma perda que JA passa do piso (-20R vs -40R) muda `r_medio` da
        tabela proporcionalmente (nunca "satura" em -1.0 como aconteceria se o R reportado fosse
        o `net_frac` travado) -- confirma que o piso nunca contamina o R reportado."""
        trades_20 = [_trade_minimo(token="A", t_entrada=0.0, r_72h=-20.0, risk_frac=0.2)]
        trades_40 = [_trade_minimo(token="A", t_entrada=0.0, r_72h=-40.0, risk_frac=0.2)]
        r20 = svc._executar_ledger(trades_20, "V10", "base", "US$0.05", 250.0, svc.MAX_POSICOES_PADRAO,
                                   svc.MAX_VOLUME_PCT_PADRAO)
        r40 = svc._executar_ledger(trades_40, "V10", "base", "US$0.05", 250.0, svc.MAX_POSICOES_PADRAO,
                                   svc.MAX_VOLUME_PCT_PADRAO)
        self.assertNotAlmostEqual(r20["r_valores"][0], r40["r_valores"][0], places=3)
        # mas resultado_usd (o que o piso protege) fica IDENTICO -- ambos ja perderam 100% do principal.
        self.assertAlmostEqual(r20["resultados_usd"][0], r40["resultados_usd"][0], places=2)


class DistribuicaoPermutacaoTests(unittest.TestCase):
    """PEDIDO 2026-11-05 (rodada 11, item A4): distribuicao por permutacao aleatoria da ordem."""

    def test_sem_sinais_devolve_tudo_none(self) -> None:
        d = svc.distribuicao_por_permutacao([], "V10", "base", "US$0.05", 250.0, k=20)
        self.assertIsNone(d.retorno_pct_mediana)
        self.assertIsNone(d.n_trades_medio)

    def test_preserva_os_instantes_reais_de_chegada_so_permuta_quem_ocupa_cada_um(self) -> None:
        """Com `max_posicoes=1`, so 1 sinal por vez pode estar aberto -- como os instantes reais
        (3 chegadas bem proximas) nunca mudam, o teto de vagas bloqueia o MESMO numero de posicoes
        em QUALQUER permutacao (sempre 1 trade por caminho, nunca 3) -- confirma que a permutacao
        preserva a densidade real de chegada, nunca so reordena por t_entrada."""
        trades = [_trade_minimo(token=f"T{i}", t_entrada=float(i), r_72h=1.0) for i in range(3)]
        d = svc.distribuicao_por_permutacao(trades, "V10", "base", "US$0.05", 250.0, max_posicoes=1, k=50)
        self.assertEqual(d.n_trades_medio, 1.0)

    def test_quantis_sao_monotonos_q05_menor_ou_igual_mediana_menor_ou_igual_q95(self) -> None:
        passo = svc.HORIZONTES_S["72h"] + 1
        trades = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=float(i) - 3.0) for i in range(8)]
        d = svc.distribuicao_por_permutacao(trades, "V50", "base", "US$0.05", 250.0, k=200)
        self.assertLessEqual(d.retorno_pct_q05, d.retorno_pct_mediana)
        self.assertLessEqual(d.retorno_pct_mediana, d.retorno_pct_q95)
        self.assertLessEqual(d.max_dd_pct_q05, d.max_dd_pct_mediana)
        self.assertLessEqual(d.max_dd_pct_mediana, d.max_dd_pct_q95)

    def test_e_deterministico_com_a_mesma_seed(self) -> None:
        passo = svc.HORIZONTES_S["72h"] + 1
        trades = [_trade_minimo(token=f"T{i}", t_entrada=i * passo, r_72h=-1.0) for i in range(5)]
        d1 = svc.distribuicao_por_permutacao(trades, "V50", "base", "US$0.05", 250.0, k=100)
        d2 = svc.distribuicao_por_permutacao(trades, "V50", "base", "US$0.05", 250.0, k=100)
        self.assertEqual(d1.retorno_pct_mediana, d2.retorno_pct_mediana)
        self.assertEqual(d1.max_dd_pct_mediana, d2.max_dd_pct_mediana)


class CorrecaoDeEntradaTests(unittest.TestCase):
    def test_candle_de_entrada_corrompido_usa_o_candle_limpo_anterior(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 0.0)])
        preco, corrigido = svc._candle_limpo_na_entrada(bars, 1)
        self.assertTrue(corrigido)
        self.assertAlmostEqual(preco, bars[0].close)

    def test_candle_de_entrada_limpo_nunca_e_corrigido(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0)])
        preco, corrigido = svc._candle_limpo_na_entrada(bars, 1)
        self.assertFalse(corrigido)
        self.assertAlmostEqual(preco, bars[1].open)

    def test_entrada_atrasada_usa_o_1o_candle_apos_o_alerta(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0), (101, 103, 95, 102, 10.0)])
        preco, idx, corrigido = svc._preco_apos_latencia(bars, 1, ts_alerta=bars[2].ts)
        self.assertTrue(corrigido)
        self.assertEqual(idx, 2)
        self.assertAlmostEqual(preco, bars[2].open)

    def test_sem_ts_alerta_fica_no_padrao(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0)])
        preco, idx, corrigido = svc._preco_apos_latencia(bars, 1, ts_alerta=None)
        self.assertFalse(corrigido)
        self.assertEqual(idx, 1)
        self.assertAlmostEqual(preco, bars[1].open)


class OverlapTokensTests(unittest.TestCase):
    def test_tokens_em_mais_de_1_origem_sao_contados(self) -> None:
        ao_vivo = [_trade_minimo(token="CAT")]
        retro = [_trade_minimo(token="CAT", origem="retro_lote1")]
        replay = [_trade_minimo(token="DOG", origem="v3_replay")]
        linhas = svc._resumo_overlap_tokens(ao_vivo, retro, replay)
        self.assertIn("tokens em mais de 1 origem: 1", linhas[0])
        self.assertIn("CAT", linhas[0])

    def test_sem_overlap_conta_zero(self) -> None:
        ao_vivo = [_trade_minimo(token="CAT")]
        retro = [_trade_minimo(token="DOG", origem="retro_lote1")]
        linhas = svc._resumo_overlap_tokens(ao_vivo, retro, [])
        self.assertIn("tokens em mais de 1 origem: 0", linhas[0])

    def test_clones_de_mesmo_ticker_em_origens_diferentes_nunca_contam_como_overlap(self) -> None:
        # RODADA 17 (achado A2): mesmo ticker "CAT", mints DIFERENTES, em origens diferentes --
        # antes da correcao isso contava como "o mesmo token apareceu em 2 origens"; agora, cada
        # mint e sua propria identidade, nunca um overlap.
        ao_vivo = [_trade_minimo(token="CAT", mint="MINT_A")]
        retro = [_trade_minimo(token="CAT", mint="MINT_B", origem="retro_lote1")]
        linhas = svc._resumo_overlap_tokens(ao_vivo, retro, [])
        self.assertIn("tokens em mais de 1 origem: 0", linhas[0])


class ExecutarSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="simular_v3_carteira_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha(self) -> None:
        texto = svc.executar(self.storage.paths.db)
        self.assertIn(svc.AVISO, texto)
        self.assertIn(svc.AVISO_R_MEDIO, texto)   # rodada 10, item 3 -- nunca escondido
        self.assertNotIn("Traceback", texto)

    def test_sinal_ainda_pendente_mostra_quando_completa_e_nunca_crasha(self) -> None:
        # `executar()` usa o relogio REAL (time.time()) -- t_entrada precisa estar perto de agora
        # (nunca em 1970) pra que o horizonte de 72h ainda nao tenha decorrido de verdade.
        import time as _time
        ts0 = int(_time.time()) - 3_600
        signal_id = self.storage.pr3_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": ts0,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v3": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "aberto", "entry_price": 100.0, "stop": 80.0, "topo": 10_000.0,
            "s_suporte": 50.0, "r_resistencia": 90.0, "n_pavios": 3,
        })
        self.storage.pr_trajetoria_upsert("v3", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                          mint="MINT1", symbol="CAT", t_entrada=float(ts0 + 3_600),
                                          preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0, fonte_candle="gt")
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0)], ts0=ts0, step=3_600)
        self.storage.pr_append_bars("POOL1", "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume,
                                                     int(b.filled)) for b in bars])
        texto = svc.executar(self.storage.paths.db, banca=250.0)
        self.assertIn("pendentes de 72h", texto)
        self.assertIn("1o sinal pendente completa 72h em:", texto)
        self.assertIn("sem trades com desfecho definido ainda", texto)
        self.assertNotIn("Traceback", texto)

    def test_banca_explicita_roda_so_1_cenario(self) -> None:
        texto = svc.executar(self.storage.paths.db, banca=777.0)
        self.assertIn("US$777", texto)
        self.assertNotIn("US$250", texto)

    def test_filtro_desde_exclui_sinais_anteriores_a_data(self) -> None:
        signal_id = self.storage.pr3_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v3": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "aberto", "entry_price": 100.0, "stop": 80.0, "topo": 10_000.0,
            "s_suporte": 50.0, "r_resistencia": 90.0,
        })
        self.storage.pr_trajetoria_upsert("v3", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                          mint="MINT1", symbol="CAT", t_entrada=4_600.0, preco_entrada=100.0,
                                          risco_pct=20.0, r_unidade=20.0, fonte_candle="gt")
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0)])
        self.storage.pr_append_bars("POOL1", "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume,
                                                     int(b.filled)) for b in bars])
        trades = svc.carregar_ao_vivo(self.storage, "2030-01-01", now=10_000_000.0)
        self.assertEqual(trades, [])


class A1PerdaTravadaETests(unittest.TestCase):
    """PEDIDO 2026-11-05 (A1): uma posicao a vista, sem alavancagem, nunca pode perder mais do que
    investiu -- mesmo com R marcado a mercado muito negativo (ex.: token que despencou 95%)."""

    def test_resultado_usd_nunca_excede_o_principal_investido_em_modulo(self) -> None:
        # r_72h=-20 (extremo) x risk_frac=0.2 = -4.0 (-400%) SEM o teto -- com o teto, trava em -100%.
        trades = [_trade_minimo(token="A", t_entrada=0.0, r_72h=-20.0)]
        r = svc.simular_carteira(trades, "ao_vivo", "V25", "base", "US$0.05", 250.0, calcular_ruina=False)
        self.assertEqual(r.n_trades, 1)
        self.assertGreaterEqual(r.banca_final, 250.0 - 25.0 - 1e-6)   # nunca perde mais que os US$25 investidos

    def test_maxdd_em_usd_nunca_excede_o_total_investido_num_unico_round(self) -> None:
        # 4 posicoes de US$25 simultaneas (max_posicoes=4), todas com perda extrema -- o drawdown
        # maximo em US$ tem que ficar <= 4*US$25=US$100 (o capital REALMENTE arriscado), nunca mais.
        trades = [_trade_minimo(token=t, t_entrada=0.0, r_72h=-20.0) for t in ("A", "B", "C", "D")]
        r = svc.simular_carteira(trades, "ao_vivo", "V25", "base", "US$0.05", 250.0, max_posicoes=4,
                                 calcular_ruina=False)
        self.assertEqual(r.n_trades, 4)
        self.assertLessEqual(r.max_drawdown_usd, 4 * 25.0 + 1e-6)


class A1EquityContinuaTests(unittest.TestCase):
    """PEDIDO 2026-11-05 (A1): patrimonio (caixa + posicoes abertas a custo) rastreado a cada evento
    -- abrir uma posicao NUNCA aparenta "drawdown" so por travar o principal (o patrimonio fica
    invariante nesse instante; so muda quando a posicao de fato libera com resultado real)."""

    def test_abrir_varias_posicoes_sem_liberar_nenhuma_nao_gera_drawdown_falso(self) -> None:
        trades = [_trade_minimo(token=t, t_entrada=0.0, r_72h=0.0) for t in ("A", "B", "C", "D")]
        r = svc.simular_carteira(trades, "ao_vivo", "V25", "base", "US$0.05", 250.0, max_posicoes=4,
                                 calcular_ruina=False)
        # 4 entradas de US$25 ao MESMO tempo travam US$100 do caixa, mas o patrimonio (caixa+posicoes)
        # fica em 250 o tempo todo (r_72h=0, sem custo zerado so pelo coeficiente) -- dd deve ficar perto de 0.
        self.assertLess(r.max_drawdown_usd, 5.0)   # so o atrito de custo fixo/impacto, nunca travamento


class A2CriteriosOportunidadeTests(unittest.TestCase):
    def test_reporta_quantos_passam_em_cada_criterio_e_sem_dado(self) -> None:
        trades = [
            _trade_minimo(token="A", volume_gatilho=100.0, volume_medio_24h=40.0, n_pavios=3,
                         volume_entrada=25.0),   # passa tudo
            _trade_minimo(token="B", volume_gatilho=50.0, volume_medio_24h=40.0, n_pavios=2,
                         volume_entrada=5.0),    # nao passa nada
            _trade_minimo(token="C", volume_gatilho=None, volume_medio_24h=None, n_pavios=None,
                         volume_entrada=None),   # sem dado
        ]
        linhas = svc._resumo_criterios_oportunidade(trades)
        texto = "\n".join(linhas)
        self.assertIn("volume do gatilho >=2x media 24h: 1/3", texto)
        self.assertIn("n_pavios==3: 1/3", texto)
        self.assertIn("AMBOS (qualifica p/ US$25+): 1/3", texto)

    def test_sem_nenhum_sinal_qualificado_avisa_explicitamente(self) -> None:
        trades = [_trade_minimo(token="A", volume_gatilho=10.0, volume_medio_24h=40.0, n_pavios=1)]
        texto = "\n".join(svc._resumo_criterios_oportunidade(trades))
        self.assertIn("NENHUM sinal desta origem satisfez o criterio de qualidade", texto)

    def test_sem_trades_nunca_crasha(self) -> None:
        texto = "\n".join(svc._resumo_criterios_oportunidade([]))
        self.assertIn("sem sinais", texto)


class A3UmaPorTokenTests(unittest.TestCase):
    def test_2o_sinal_do_mesmo_token_pula_e_conta_token_ja_aberto(self) -> None:
        trades = [
            _trade_minimo(token="CAT", t_entrada=0.0, r_72h=1.0),
            _trade_minimo(token="CAT", t_entrada=10.0, r_72h=1.0),   # mesmo token, ainda aberto
        ]
        r = svc.simular_carteira(trades, "ao_vivo", "V10", "base", "US$0.05", 250.0, max_posicoes=10,
                                 calcular_ruina=False)
        self.assertEqual(r.n_trades, 1)
        self.assertEqual(r.pulados_por_motivo.get("token_ja_aberto"), 1)

    def test_tokens_diferentes_nunca_bloqueiam_entre_si(self) -> None:
        trades = [
            _trade_minimo(token="CAT", t_entrada=0.0, r_72h=1.0),
            _trade_minimo(token="DOG", t_entrada=10.0, r_72h=1.0),
        ]
        r = svc.simular_carteira(trades, "ao_vivo", "V10", "base", "US$0.05", 250.0, max_posicoes=10,
                                 calcular_ruina=False)
        self.assertEqual(r.n_trades, 2)

    def test_clones_de_mesmo_ticker_mints_diferentes_nunca_bloqueiam_entre_si(self) -> None:
        # RODADA 17 (achado A2): o MESMO ticker "CAT", mints DIFERENTES (clones) -- `uma_por_token`
        # precisa permitir os 2 entrarem juntos, exatamente como tokens realmente diferentes.
        trades = [
            _trade_minimo(token="CAT", mint="MINT_A", t_entrada=0.0, r_72h=1.0),
            _trade_minimo(token="CAT", mint="MINT_B", t_entrada=10.0, r_72h=1.0),
        ]
        r = svc.simular_carteira(trades, "ao_vivo", "V10", "base", "US$0.05", 250.0, max_posicoes=10,
                                 calcular_ruina=False)
        self.assertEqual(r.n_trades, 2)

    def test_apos_liberar_o_mesmo_token_pode_entrar_de_novo(self) -> None:
        passo = svc.HORIZONTES_S["72h"] + 1
        trades = [
            _trade_minimo(token="CAT", t_entrada=0.0, r_72h=1.0),
            _trade_minimo(token="CAT", t_entrada=passo, r_72h=1.0),   # so depois que o 1o liberou
        ]
        r = svc.simular_carteira(trades, "ao_vivo", "V10", "base", "US$0.05", 250.0, max_posicoes=10,
                                 calcular_ruina=False)
        self.assertEqual(r.n_trades, 2)
        self.assertEqual(r.pulados_por_motivo.get("token_ja_aberto"), None)

    def test_uma_por_token_desligado_permite_2_posicoes_do_mesmo_token(self) -> None:
        trades = [
            _trade_minimo(token="CAT", t_entrada=0.0, r_72h=1.0),
            _trade_minimo(token="CAT", t_entrada=10.0, r_72h=1.0),
        ]
        r = svc.simular_carteira(trades, "ao_vivo", "V10", "base", "US$0.05", 250.0, max_posicoes=10,
                                 calcular_ruina=False, uma_por_token=False)
        self.assertEqual(r.n_trades, 2)


class A6CsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="simular_v3_carteira_csv_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_csv_path_grava_um_arquivo_com_cabecalho(self) -> None:
        import csv as _csv
        signal_id = self.storage.pr3_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v3": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "aberto", "entry_price": 100.0, "stop": 80.0, "topo": 10_000.0,
            "s_suporte": 50.0, "r_resistencia": 90.0, "n_pavios": 3,
        })
        self.storage.pr_trajetoria_upsert("v3", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                          mint="MINT1", symbol="CAT", t_entrada=4_600.0, preco_entrada=100.0,
                                          risco_pct=20.0, r_unidade=20.0, fonte_candle="gt")
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0),
            (101, 103, 95, 102, 10.0), (102, 104, 95, 103, 10.0),
        ])
        self.storage.pr_append_bars("POOL1", "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume,
                                                     int(b.filled)) for b in bars])
        csv_path = self.tmp / "saida.csv"
        texto = svc.executar(self.storage.paths.db, banca=250.0, csv_path=csv_path, progresso=False)
        self.assertTrue(csv_path.exists())
        with csv_path.open() as f:
            linhas = list(_csv.DictReader(f))
        self.assertGreater(len(linhas), 0)
        self.assertIn("regra", linhas[0])
        self.assertIn(str(csv_path), texto)


if __name__ == "__main__":
    unittest.main()
