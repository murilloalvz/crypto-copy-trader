import pandas as pd
import streamlit as st

from src.analytics import paper_performance, wallet_metrics
from src.database import add_wallet, initialize_database, remove_wallet, rows
from src.services import (
    generate_paper_trades,
    price_paper_trades,
    reparse_wallet_transactions,
    sync_wallet,
)

st.set_page_config(page_title="Solana CopyTrader", page_icon="◎", layout="wide")
initialize_database()

st.title("Solana CopyTrader")
st.caption("Monitoramento on-chain e paper trading — nenhuma ordem real é enviada.")

flash = st.session_state.pop("flash", None)
if flash:
    level, message = flash
    getattr(st, level)(message)

with st.sidebar:
    st.header("Adicionar wallet")
    label = st.text_input("Nome", placeholder="Ex.: Trader 01")
    address = st.text_input("Endereço público Solana")
    if st.button("Adicionar", use_container_width=True, type="primary"):
        if 32 <= len(address.strip()) <= 44:
            add_wallet(address, label)
            st.session_state["flash"] = ("success", "Wallet adicionada.")
            st.rerun()
        else:
            st.error("O endereço informado não parece ser uma wallet Solana válida.")

wallets = rows("SELECT * FROM wallets WHERE enabled=1 ORDER BY created_at DESC")
if not wallets:
    st.info("Adicione uma wallet pública na barra lateral para começar.")
    st.stop()

options = {
    f"{wallet['label']} · {wallet['address'][:6]}…{wallet['address'][-4:]}": wallet
    for wallet in wallets
}
selected_label = st.selectbox("Wallet monitorada", options)
wallet = options[selected_label]
address = wallet["address"]

# Reclassify legacy rows with the latest parser when the app is upgraded. This
# keeps the user's local database and marks old false positives as ignored.
reparse_wallet_transactions(address)

sync_col, history_col, paper_col, remove_col = st.columns(4)
with sync_col:
    if st.button("Sincronizar blockchain", use_container_width=True):
        try:
            with st.spinner("Buscando transações no RPC Solana..."):
                result = sync_wallet(address)
            if result["found"] == 0:
                st.session_state["flash"] = (
                    "warning",
                    "O RPC respondeu, mas não encontrou transações para este endereço. "
                    "Confira se a wallet selecionada é a correta.",
                )
            elif result["failed"]:
                st.session_state["flash"] = (
                    "warning",
                    f"Encontradas: {result['found']} · importadas: {result['inserted']} · "
                    f"falhas do RPC: {result['failed']} · RPC: {result['rpc_endpoint']}. "
                    f"Primeira falha: {result['first_error']}",
                )
            else:
                st.session_state["flash"] = (
                    "success",
                    f"Encontradas: {result['found']} · novas importadas: {result['inserted']} · "
                    f"já existentes/ignoradas: {result['skipped']} · "
                    f"RPC: {result['rpc_endpoint']}.",
                )
            st.rerun()
        except Exception as exc:
            st.error(f"Falha na sincronização: {exc}")
with history_col:
    if st.button("Importar histórico anterior", use_container_width=True):
        try:
            with st.spinner("Buscando o lote anterior de transações..."):
                result = sync_wallet(address, backfill=True)
            st.session_state["flash"] = (
                "success" if result["inserted"] else "info",
                f"Histórico: {result['found']} encontradas · {result['inserted']} novas · "
                f"{result['failed']} falhas · RPC: {result['rpc_endpoint']}.",
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Falha ao importar histórico: {exc}")
with paper_col:
    if st.button("Simular novas cópias", use_container_width=True):
        created = generate_paper_trades(address)
        st.session_state["flash"] = (
            "success" if created else "info",
            (
                f"{created} operações simuladas criadas."
                if created
                else "Nenhum swap novo confirmado por uma DEX suportada."
            ),
        )
        st.rerun()
with remove_col:
    if st.button("Remover da lista", use_container_width=True):
        remove_wallet(address)
        st.rerun()

metrics = wallet_metrics(address)
c1, c2, c3, c4 = st.columns(4)
score_display = (
    f"{metrics['score']}/100" if metrics["score"] is not None else "Dados insuficientes"
)
c1.metric("Wallet Score", score_display)
c1.caption(metrics["score_reason"])
c2.metric("Transações", metrics["transactions"])
c3.metric("Swaps confirmados", metrics["swaps"])
c4.metric("Swaps/dia ativo", f"{metrics['frequency']:.2f}")

txs = rows(
    """SELECT block_time, kind, dex, status, sol_change, fee_sol, token_mint,
    token_change, signature
    FROM transactions WHERE wallet_address=? ORDER BY block_time DESC""",
    (address,),
)
paper = rows(
    """SELECT pt.source_block_time, tx.dex, pt.side, pt.token_mint, pt.simulated_usd,
    pt.market_price_usd, pt.execution_price_usd, pt.token_quantity, pt.fees_usd,
    pt.realized_pnl_usd, pt.slippage_bps, pt.delay_seconds, pt.status, pt.price_error
    FROM paper_trades pt JOIN transactions tx ON tx.signature=pt.source_signature
    WHERE pt.wallet_address=? AND pt.status!='filtered_non_swap' ORDER BY pt.id DESC""",
    (address,),
)

tab1, tab2, tab3 = st.tabs(["Transações", "Paper trading", "Sobre o score"])
with tab1:
    if txs:
        frame = pd.DataFrame(txs)
        frame["data"] = pd.to_datetime(frame.pop("block_time"), unit="s", utc=True)
        frame["mint"] = frame.pop("token_mint").fillna("-").str.slice(0, 8) + "…"
        frame["assinatura"] = frame.pop("signature").str.slice(0, 12) + "…"
        st.dataframe(frame, use_container_width=True, hide_index=True)
    else:
        st.info("Clique em “Sincronizar blockchain” para importar o histórico recente.")
with tab2:
    if st.button(
        "Buscar preços e calcular performance",
        type="primary",
        disabled=not bool(paper),
    ):
        try:
            with st.spinner("Consultando candles históricos e reconstruindo posições FIFO..."):
                result = price_paper_trades(address)
            level = "warning" if result["failed"] else "success"
            st.session_state["flash"] = (
                level,
                f"Preços novos: {result['priced']} · em cache: {result['cached']} · "
                f"sem preço: {result['failed']} · vendas fechadas: {result['closed']}.",
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Falha ao calcular performance: {exc}")

    performance = paper_performance(address)
    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("P&L realizado", f"US$ {performance['realized_pnl_usd']:.2f}")
    p2.metric("Retorno", f"{performance['return_pct']:.2f}%")
    p3.metric("Win rate", f"{performance['win_rate_pct']:.1f}%")
    p4.metric("Drawdown realizado", f"{performance['max_drawdown_pct']:.2f}%")
    p5.metric("Trades fechados", performance["closed_trades"])

    if performance["filtered_trades"]:
        st.info(
            f"{performance['filtered_trades']} operação(ões) antigas foram ignoradas porque "
            "não eram swaps confirmados por Jupiter, Raydium ou Pump.fun."
        )

    if performance["curve"]:
        curve = pd.DataFrame(performance["curve"])
        curve["data"] = pd.to_datetime(curve.pop("timestamp"), unit="s", utc=True)
        st.line_chart(curve.set_index("data")["equity_usd"])

    if paper:
        paper_frame = pd.DataFrame(paper)
        paper_frame["data"] = pd.to_datetime(
            paper_frame.pop("source_block_time"), unit="s", utc=True, errors="coerce"
        )
        st.dataframe(paper_frame, use_container_width=True, hide_index=True)
        if performance["price_failures"]:
            st.warning(
                f"{performance['price_failures']} operação(ões) ainda não possuem "
                "preço histórico. "
                "Veja a coluna price_error."
            )
    else:
        if metrics["swaps"]:
            st.info(
                "Existem swaps confirmados nesta wallet. Clique em “Simular novas cópias” "
                "para criar as operações de paper trading."
            )
        elif txs:
            st.info(
                "Esta wallet possui transações, mas nenhum swap confirmado por uma DEX "
                "suportada. Não há operações para simular; teste uma wallet de trader."
            )
        else:
            st.info(
                "Clique em “Sincronizar blockchain” para buscar as transações da wallet."
            )
    st.caption("Preços on-chain fornecidos por GeckoTerminal. Powered by CoinGecko.")
with tab3:
    st.write(
        "O Wallet Score só é liberado após pelo menos 5 trades completos de compra e venda. "
        "Antes disso, o dashboard mostra “Dados insuficientes” para não transformar atividade "
        "em uma falsa indicação de rentabilidade."
    )
    st.write(
        "Quando liberado, o score considera retorno realizado, win rate, drawdown, tamanho da "
        "amostra, atividade e frequência. Ele é um filtro de pesquisa, não uma promessa "
        "de lucro."
    )
    if metrics["score_components"]:
        components = pd.DataFrame(
            metrics["score_components"].items(), columns=["componente", "pontos"]
        )
        st.dataframe(components, use_container_width=True, hide_index=True)
