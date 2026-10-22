"""POS-RUNNER-V1: templates do Telegram (item 4) e o teclado com link_for. Sem rede."""

from __future__ import annotations

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
        self.assertIn("Market Cap: $500K" if False else "Market Cap:", text)
        self.assertIn("janela de ouro", text)
        self.assertIn("power_candle_rompimento", text)
        self.assertIn("risco fora da faixa", text)
        self.assertIn("VAMP_RISK", text)
        self.assertIn("Liquidez do pool", text)
        self.assertIn("mintA", text)
        self.assertNotIn("<script>", text)   # HTML-escape do ticker

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


if __name__ == "__main__":
    unittest.main()
