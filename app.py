import pandas as pd
import streamlit as st

from src.analytics import paper_performance, wallet_metrics
from src.database import add_wallet, initialize_database, remove_wallet, rows
from src.demo import (
    DEMO_WALLET_ADDRESS,
    DEMO_WALLET_LABEL,
    DemoPriceProvider,
    DemoSolanaClient,
)
from src.services import (
    generate_paper_trades,
    price_paper_trades,
    reparse_wallet_transactions,
    sync_wallet,
    wallet_protocol_diagnostics,
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
    st.header("Modo de execução")
    demo_mode = st.toggle(
        "Modo demonstração offline",
        help="Usa somente dados e preços sintéticos salvos no app.",
    )
    if demo_mode:
        st.info(
            "Não usa internet, RPC ou blockchain. Os resultados servem apenas "
            "para testar o funcionamento do sistema."
        )
        st.markdown(
            "**Ordem do teste**\n\n"
            "1. Carregar dados offline\n"
            "2. Simular novas cópias\n"
            "3. Aplicar preços na aba Paper trading"
        )
    else:
        st.header("Adicionar wallet")
        label = st.text_input("Nome", placeholder="Ex.: Trader 01")
        new_address = st.text_input("Endereço público Solana")
        if st.button("Adicionar", use_container_width=True, type="primary"):
            if 32 <= len(new_address.strip()) <= 44:
                add_wallet(new_address, label)
                st.session_state["flash"] = ("success", "Wallet adicionada.")
                st.rerun()
            else:
                st.error("O endereço informado não parece ser uma wallet Solana válida.")

if demo_mode:
    add_wallet(DEMO_WALLET_ADDRESS, DEMO_WALLET_LABEL)
    st.warning(
        "MODO DEMONSTRAÇÃO OFFLINE — todas as transações e todos os preços são "
        "sintéticos. Nenhum dado abaixo veio da blockchain."
    )

if demo_mode:
    wallets = rows("SELECT * FROM wallets WHERE address=?", (DEMO_WALLET_ADDRESS,))
else:
    wallets = rows(
        "SELECT * FROM wallets WHERE enabled=1 AND address!=? ORDER BY created_at DESC",
        (DEMO_WALLET_ADDRESS,),
    )
if not wallets:
    st.info("Adicione uma wallet pública na barra lateral para começar.")
    st.stop()

options = {
    f"{wallet['label']} · {wallet['address'][:6]}…{wallet['address'][-4:]}": wallet
    for wallet in wallets
}
selected_label = st.selectbox("Wallet monitorada", options, disabled=demo_mode)
wallet = options[selected_label]
address = wallet["address"]

# Reclassify legacy rows with the latest parser when the app is upgraded. This
# keeps the user's local database and marks old false positives as ignored.
reparse_wallet_transactions(address)

sync_col, history_col, paper_col, remove_col = st.columns(4)
with sync_col:
    sync_label = "Carregar dados offline" if demo_mode else "Sincronizar blockchain"
    if st.button(sync_label, use_container_width=True):
        try:
            spinner = (
                "Carregando transações sintéticas locais..."
                if demo_mode
                else "Buscando transações no RPC Solana..."
            )
            with st.spinner(spinner):
                client = DemoSolanaClient() if demo_mode else None
                result = sync_wallet(address, client=client)
            if demo_mode:
                st.session_state["flash"] = (
                    "success",
                    f"Demonstração carregada: {result['found']} transações sintéticas · "
                    f"{result['inserted']} novas · {result['skipped']} já existentes. "
                    "Nenhuma conexão externa foi usada.",
                )
            elif result["found"] == 0:
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
    history_label = "Histórico já incluso" if demo_mode else "Importar histórico anterior"
    if st.button(history_label, use_container_width=True, disabled=demo_mode):
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
        if demo_mode and not created:
            empty_message = (
                "As operações da demonstração já existem; nenhuma duplicata foi criada."
            )
        else:
            empty_message = "Nenhum swap novo confirmado por uma DEX suportada."
        st.session_state["flash"] = (
            "success" if created else "info",
            (
                f"{created} operações simuladas criadas."
                if created
                else empty_message
            ),
        )
        st.rerun()
with remove_col:
    if st.button("Remover da lista", use_container_width=True, disabled=demo_mode):
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

if metrics["transactions"] and not metrics["swaps"]:
    diagnostics = wallet_protocol_diagnostics(address)
    with st.expander("Por que nenhum swap foi detectado?", expanded=True):
        st.write(
            f"Foram analisadas {diagnostics['analyzed']} transações armazenadas. "
            "O parser só confirma um swap quando encontra uma DEX conhecida e um fluxo "
            "de saldos compatível com compra ou venda."
        )
        if diagnostics["supported"]:
            st.write("**Protocolos suportados encontrados:**")
            st.dataframe(
                pd.DataFrame(diagnostics["supported"]),
                use_container_width=True,
                hide_index=True,
            )
            st.info(
                "A DEX apareceu, mas o fluxo de saldos não parecia um swap simples. "
                "Pode ser liquidez, roteamento complexo ou outra atividade do protocolo."
            )
        else:
            st.warning(
                "Nenhuma DEX suportada apareceu nessas transações. Isso não prova que a "
                "wallet nunca fez swaps; ela pode usar outro protocolo ou um histórico mais antigo."
            )
        if diagnostics["unknown"]:
            st.write("**Programas ainda não reconhecidos mais frequentes:**")
            st.dataframe(
                pd.DataFrame(diagnostics["unknown"]),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "Esses IDs ajudam a identificar qual integração precisa ser adicionada ao parser."
            )

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
    , pt.price_error_code, pt.price_retry_count
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
        action = "Carregar dados offline" if demo_mode else "Sincronizar blockchain"
        st.info(f"Clique em “{action}” para importar o histórico recente.")
with tab2:
    price_button_label = (
        "Aplicar preços sintéticos e calcular"
        if demo_mode
        else "Buscar preços e calcular performance"
    )
    if st.button(
        price_button_label,
        type="primary",
        disabled=not bool(paper),
    ):
        try:
            spinner = (
                "Aplicando preços sintéticos e reconstruindo posições FIFO..."
                if demo_mode
                else "Consultando candles históricos e reconstruindo posições FIFO..."
            )
            with st.spinner(spinner):
                provider = DemoPriceProvider() if demo_mode else None
                result = price_paper_trades(address, provider=provider)
            skipped_market = result["skipped_illiquid"] + result["skipped_low_volume"]
            level = "warning" if result["failed"] or skipped_market else "success"
            st.session_state["flash"] = (
                level,
                f"Preços novos: {result['priced']} · em cache: {result['cached']} · "
                f"falhas temporárias: {result['retryable_failures']} · "
                f"falhas permanentes: {result['permanent_failures']} · "
                f"retentativas esgotadas: {result['exhausted_failures']} · "
                f"sinais sem mercado copiável: {skipped_market} · "
                f"vendas fechadas: {result['closed']}.",
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

    coverage_label = (
        f"{performance['priced_signals']} de {performance['total_signals']} swaps "
        f"precificados ({performance['price_coverage_pct']:.1f}%)"
    )
    st.progress(
        min(performance["price_coverage_pct"] / 100, 1.0),
        text=f"Cobertura da amostra: {coverage_label}",
    )
    st.caption(
        f"Entre os {performance['eligible_signals']} sinais não bloqueados pelo mercado, "
        f"a cobertura de preço é {performance['eligible_price_coverage_pct']:.1f}%. "
        "P&L, retorno, win rate e drawdown representam apenas operações elegíveis que "
        "formaram compras e vendas precificadas; não representam todos os swaps da wallet."
    )

    if performance["filtered_trades"]:
        st.info(
            f"{performance['filtered_trades']} operação(ões) antigas foram ignoradas porque "
            "não eram swaps confirmados por Jupiter, Raydium ou Pump.fun."
        )

    if performance["liquidity_skips"]:
        st.warning(
            f"{performance['liquidity_skips']} sinal(is) foram registrados, mas ignorados "
            "do paper trading por liquidez ou volume atuais insuficientes. Veja a coluna "
            "price_error."
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
        if performance["temporary_price_failures"]:
            st.warning(
                f"{performance['temporary_price_failures']} operação(ões) tiveram falha "
                "temporária e poderão ser tentadas novamente automaticamente."
            )
        if performance["permanent_price_failures"]:
            details = " · ".join(
                f"{code}: {count}"
                for code, count in sorted(performance["price_error_breakdown"].items())
            )
            st.info(
                f"{performance['permanent_price_failures']} operação(ões) possuem falha "
                f"permanente e não serão consultadas novamente. {details}"
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
            action = "Carregar dados offline" if demo_mode else "Sincronizar blockchain"
            st.info(
                f"Clique em “{action}” para buscar as transações da wallet."
            )
    if demo_mode:
        st.caption(
            "Preços sintéticos locais — somente demonstração; não são cotações de mercado."
        )
    else:
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
