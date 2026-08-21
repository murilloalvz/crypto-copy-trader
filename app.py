import pandas as pd
import streamlit as st

from src.analytics import paper_performance, wallet_metrics
from src.database import add_wallet, initialize_database, remove_wallet, rows
from src.services import generate_paper_trades, price_paper_trades, sync_wallet

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

options = {f"{wallet['label']} · {wallet['address'][:6]}…{wallet['address'][-4:]}": wallet for wallet in wallets}
selected_label = st.selectbox("Wallet monitorada", options)
wallet = options[selected_label]
address = wallet["address"]

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
                    f"falhas do RPC: {result['failed']}. Primeira falha: {result['first_error']}",
                )
            else:
                st.session_state["flash"] = (
                    "success",
                    f"Encontradas: {result['found']} · novas importadas: {result['inserted']} · "
                    f"já existentes/ignoradas: {result['skipped']}.",
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
                f"{result['failed']} falhas.",
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Falha ao importar histórico: {exc}")
with paper_col:
    if st.button("Simular novas cópias", use_container_width=True):
        created = generate_paper_trades(address)
        st.session_state["flash"] = ("success", f"{created} operações simuladas criadas.")
        st.rerun()
with remove_col:
    if st.button("Remover da lista", use_container_width=True):
        remove_wallet(address)
        st.rerun()

metrics = wallet_metrics(address)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Wallet Score inicial", f"{metrics['score']}/100")
c2.metric("Transações", metrics["transactions"])
c3.metric("Swaps detectados", metrics["swaps"])
c4.metric("Swaps/dia ativo", f"{metrics['frequency']:.2f}")

txs = rows(
    """SELECT block_time, kind, status, sol_change, fee_sol, token_mint, token_change, signature
    FROM transactions WHERE wallet_address=? ORDER BY block_time DESC""",
    (address,),
)
paper = rows(
    """SELECT source_block_time, side, token_mint, simulated_usd, market_price_usd,
    execution_price_usd, token_quantity, fees_usd, realized_pnl_usd, slippage_bps,
    delay_seconds, status, price_error
    FROM paper_trades WHERE wallet_address=? ORDER BY id DESC""",
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
    if st.button("Buscar preços e calcular performance", type="primary"):
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
                f"{performance['price_failures']} operação(ões) ainda não possuem preço histórico. "
                "Veja a coluna price_error."
            )
    else:
        st.info("Depois da sincronização, clique em “Simular novas cópias”.")
    st.caption("Preços on-chain fornecidos por GeckoTerminal. Powered by CoinGecko.")
with tab3:
    st.write(
        "O score atual mede atividade, diversidade de tokens e regularidade. Ele ainda não prova "
        "rentabilidade. P&L, win rate e drawdown serão adicionados com preços históricos confiáveis."
    )
