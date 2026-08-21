import pandas as pd
import streamlit as st

from src.analytics import wallet_metrics
from src.database import add_wallet, initialize_database, remove_wallet, rows
from src.services import generate_paper_trades, sync_wallet

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

sync_col, paper_col, remove_col = st.columns([1, 1, 1])
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
    """SELECT side, token_mint, simulated_usd, slippage_bps, delay_seconds, status, created_at
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
    if paper:
        st.dataframe(pd.DataFrame(paper), use_container_width=True, hide_index=True)
        st.warning("Nesta fase, a simulação registra sinais e custos. P&L confiável entra após integrar preços históricos por timestamp.")
    else:
        st.info("Depois da sincronização, clique em “Simular novas cópias”.")
with tab3:
    st.write(
        "O score atual mede atividade, diversidade de tokens e regularidade. Ele ainda não prova "
        "rentabilidade. P&L, win rate e drawdown serão adicionados com preços históricos confiáveis."
    )
