"""POS-RUNNER-V1: templates do Telegram (item 4) e o teclado com link_for. Sem rede."""

from __future__ import annotations

import json
import unittest

from ..pos_runner.chain_adapter import SolanaAdapter
from ..pos_runner import telegram_v1 as tv1
from ..models import ChainCtx

LINKS = {"axiom": "https://axiom.trade/t/{pool}", "gmgn": "https://gmgn.ai/sol/token/{token}",
        "dexscreener": "https://dexscreener.com/solana/{pool}"}
CTX = ChainCtx(name="solana", platform="solana", gt_network="solana", reference=frozenset())


class TemplateTests(unittest.TestCase):
    def test_entrada_text_has_the_required_sections(self):
        text = tv1.entrada_text(
            chain_name="Solana", symbol="AAA<script>", mc_usd=500_000.0, idade_h=72.0, janela_ouro="janela_ouro",
            gatilho=["power_candle_rompimento"], tags=["risco_fora_da_faixa", "VAMP_RISK"], entry_price=100.0,
            stop=90.0, tp1_price=200.0, tamanho_usd=10.0, mint="mintA", liquidez_usd=50_000.0,
        )
        self.assertIn("SINAL DE ENTRADA DETECTADO", text)
        self.assertIn("Pico (MC):", text)
        self.assertIn("MC na entrada: 100", text)
        self.assertIn("Mão sugerida por risco", text)
        self.assertIn("janela de ouro", text)
        self.assertIn("power_candle_rompimento", text)
        self.assertIn("risco fora da faixa", text)
        self.assertIn("VAMP_RISK", text)
        self.assertIn("Liquidez do pool", text)
        self.assertIn("mintA", text)
        self.assertNotIn("<script>", text)   # HTML-escape do ticker

    def test_entrada_text_mao_sugerida_por_risco_e_capada_em_10_dolares(self):
        # risco baixo (5%) faria US$2/0,05=US$40 -- a linha tem que mostrar o teto de US$10, nunca mais.
        text = tv1.entrada_text("Solana", "AAA", 500_000.0, 72.0, "janela_ouro", [], [], entry_price=100.0,
                                stop=95.0, tp1_price=200.0, tamanho_usd=10.0, mint="mintA")
        self.assertIn(
            "Mão sugerida por risco (informativo, não é o tamanho usado no paper): 10 "
            "(mín(US$10, US$2÷risco%); risco 5.0%)", text)

    def test_entrada_text_mao_sugerida_por_risco_sem_cap_quando_risco_alto(self):
        # risco alto (50%) da US$2/0,50=US$4 -- abaixo do teto de US$10, mostra o valor sem capar.
        text = tv1.entrada_text("Solana", "AAA", 500_000.0, 72.0, "janela_ouro", [], [], entry_price=100.0,
                                stop=50.0, tp1_price=200.0, tamanho_usd=10.0, mint="mintA")
        self.assertIn(
            "Mão sugerida por risco (informativo, não é o tamanho usado no paper): 4 "
            "(mín(US$10, US$2÷risco%); risco 50.0%)", text)

    def test_entrada_text_mao_sugerida_por_risco_e_s_d_sem_entry_price(self):
        text = tv1.entrada_text("Solana", "AAA", 500_000.0, 72.0, "janela_ouro", [], [], entry_price=0.0,
                                stop=0.0, tp1_price=200.0, tamanho_usd=10.0, mint="mintA")
        self.assertIn("Mão sugerida por risco (informativo, não é o tamanho usado no paper): s/d", text)

    def test_entrada_text_omits_liquidity_line_when_unknown(self):
        text = tv1.entrada_text("Solana", "AAA", 500_000.0, 72.0, "fora_da_janela", [], [], 100.0, 90.0, 200.0,
                                10.0, "mintA", liquidez_usd=None)
        self.assertNotIn("Liquidez do pool", text)
        self.assertIn("fora da janela de ouro", text)

    def test_tp1_and_exit_full_texts(self):
        self.assertIn("TP1", tv1.tp1_text("Solana", "AAA", 150.0, 100.0))
        self.assertIn("EXIT FULL", tv1.exit_full_text("Solana", "AAA", 80.0, 100.0, "stop"))
        self.assertIn("suporte", tv1.exit_full_text("Solana", "AAA", 80.0, 100.0, "exit_full"))

    def test_watchlist_and_invalidado_texts(self):
        self.assertIn("WATCHLIST", tv1.watchlist_text("Solana", "AAA", 90.0, 150.0, 1))
        self.assertIn("INVALIDADO", tv1.invalidado_text("Solana", "AAA", "candle absurdo"))

    def test_resumo_diario_text(self):
        text = tv1.resumo_diario_text(3, 1, 2, 5, 4, pnl_pct=-1.5, uptime_h=23.5)
        self.assertIn("RESUMO DIÁRIO", text)
        self.assertIn("dado_invalido: 2", text)
        self.assertIn("filtrado_mc_baixo: 5", text)
        self.assertIn("-1.5%", text)
        self.assertIn("23.5h", text)

    def test_keyboard_uses_link_for_and_asserts_https(self):
        adapter = SolanaAdapter(None, CTX, None, None, LINKS, terminal="axiom")
        kb = tv1.keyboard(adapter, "mintA", "poolA", "", "")
        urls = [b["url"] for b in kb["inline_keyboard"][0]]
        self.assertTrue(all(u.startswith("https://") for u in urls))
        self.assertEqual(urls[0], "https://axiom.trade/t/poolA")


class RelatorioSemanalTextTests(unittest.TestCase):
    """Itens 2 e 4 do pedido de ajustes de alerta/medicao: agrupamento por token (dos votos) e, a partir
    de `sinais_semana` (universo maior, independente de feedback), a quebra de risco_fora_da_faixa por
    gatilho e o histograma do % de stop."""

    def _sinal(self, gatilho, tags, entry_price, stop):
        return {"gatilho": json.dumps(gatilho), "tags": json.dumps(tags),
               "entry_price": entry_price, "stop": stop}

    def test_por_token_agrupa_os_votos_pelo_symbol(self):
        rows = [
            {"voto": "bom", "sig_gatilho": "[]", "sig_tags": "[]", "sig_janela_ouro": "janela_ouro",
             "sig_mint_authority": None, "sig_freeze_authority": None, "symbol": "AAA"},
            {"voto": "ruim", "sig_gatilho": "[]", "sig_tags": "[]", "sig_janela_ouro": "janela_ouro",
             "sig_mint_authority": None, "sig_freeze_authority": None, "symbol": "AAA"},
            {"voto": "bom", "sig_gatilho": "[]", "sig_tags": "[]", "sig_janela_ouro": "janela_ouro",
             "sig_mint_authority": None, "sig_freeze_authority": None, "symbol": "BBB"},
        ]
        text = tv1.relatorio_semanal_text(rows, None, "versaoX")
        self.assertIn("Por token:", text)
        self.assertIn("AAA: 👍1 👎1", text)
        self.assertIn("BBB: 👍1 👎0", text)

    def test_risco_fora_da_faixa_por_gatilho_e_histograma_de_stop(self):
        sinais = [
            self._sinal(["reacao_suporte"], ["risco_fora_da_faixa"], 100.0, 95.0),    # risco 5% -> 0-10%
            self._sinal(["power_candle_rompimento"], ["risco_fora_da_faixa"], 100.0, 95.0),
            self._sinal(["reacao_suporte"], [], 100.0, 82.0),                         # sem a tag: nao conta
            self._sinal([], [], 100.0, 50.0),                                         # risco 50% -> 50-60% (sem tag)
            self._sinal([], [], 0.0, 0.0),                                            # sem entry_price -> s/d
        ]
        text = tv1.relatorio_semanal_text([], None, "versaoX", sinais)
        self.assertIn("Risco fora da faixa por gatilho:", text)
        self.assertIn("reacao_suporte: 1", text)
        self.assertIn("power_candle_rompimento: 1", text)
        self.assertIn("Histograma do % de stop:", text)
        self.assertIn("0-10%: 2", text)
        self.assertIn("10-20%: 1", text)
        self.assertIn("50-60%: 1", text)
        self.assertIn("s/d: 1", text)

    def test_sem_sinais_semana_mostra_sem_dados(self):
        text = tv1.relatorio_semanal_text([], None, "versaoX")
        self.assertIn("Risco fora da faixa por gatilho: sem dados", text)
        self.assertIn("Histograma do % de stop: sem dados", text)


if __name__ == "__main__":
    unittest.main()
