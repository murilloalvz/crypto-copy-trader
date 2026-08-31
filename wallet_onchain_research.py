import argparse
import sys

from src.database import add_wallet, initialize_database, rows
from src.onchain_wallet_research import build_onchain_wallet_profile
from src.services import sync_wallet
from src.solana import SolanaRPCError


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "indisponível"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3_600:
        return f"{seconds / 60:.1f}min"
    if seconds < 86_400:
        return f"{seconds / 3_600:.1f}h"
    return f"{seconds / 86_400:.1f}d"


def _local_swaps(address: str) -> list[dict]:
    return rows(
        """SELECT block_time, status, kind, dex, token_mint, token_change
        FROM transactions
        WHERE wallet_address=? AND kind='swap' AND status='success'
        ORDER BY block_time""",
        (address,),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstrói comportamento observável de uma wallet via Solana RPC e SQLite, "
            "sem usar créditos da Solana Tracker Data API."
        )
    )
    parser.add_argument("address", help="endereço público Solana")
    parser.add_argument("--pages", type=int, default=3, help="páginas RPC de assinaturas (padrão: 3)")
    parser.add_argument("--existing-only", action="store_true", help="não sincroniza RPC; usa apenas o SQLite atual")
    parser.add_argument("--label", default="Wallet Onchain Research")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.pages <= 20:
        print("Erro: --pages precisa ficar entre 1 e 20.", file=sys.stderr)
        return 2

    initialize_database()
    add_wallet(args.address, args.label)

    if not args.existing_only:
        for page in range(1, args.pages + 1):
            try:
                result = sync_wallet(args.address, backfill=page > 1)
            except (SolanaRPCError, ValueError) as exc:
                print(f"[rpc] página {page} falhou: {exc}", file=sys.stderr)
                if page == 1:
                    return 1
                break
            print(
                f"[rpc] página {page}/{args.pages}: encontrados {result['found']} | "
                f"novos {result['inserted']} | conhecidos {result['skipped']} | "
                f"falhas {result['failed']} | endpoint {result['rpc_endpoint']}"
            )
            if result["found"] == 0:
                break

    swaps = _local_swaps(args.address)
    profile = build_onchain_wallet_profile(args.address, swaps)

    print()
    print("Crypto Copy Trader — On-chain Wallet Research v1")
    print("Modo: RESEARCH / READ ONLY — sem Solana Tracker Data API e sem ordens.")
    print(f"Wallet: {profile.address}")
    print(f"Amostra: {profile.swap_count} swaps | {profile.token_count} tokens | grau {profile.sample_grade}")
    print(f"Compras/vendas: {profile.buy_count}/{profile.sell_count} | janela observada: {profile.observed_span_days:.2f}d")
    print()
    print("PADRÃO DE EXECUÇÃO OBSERVADO")
    print(f"Ações por token (mediana): {profile.median_actions_per_token:.1f}")
    print(f"Tokens com buy+sell observado: {profile.roundtrip_token_share_pct:.1f}%")
    print(f"Tokens multi-ação: {profile.multi_action_token_share_pct:.1f}%")
    print(f"Scale-in entre roundtrips: {profile.scale_in_token_share_pct:.1f}%")
    print(f"Saída em múltiplas vendas entre roundtrips: {profile.partial_exit_token_share_pct:.1f}%")
    print(f"Reentrada após primeira venda entre roundtrips: {profile.reentry_token_share_pct:.1f}%")
    print(f"Primeira saída após primeira compra (mediana): {_duration(profile.median_first_exit_seconds)}")
    print(f"Span compra→última venda observada (mediana): {_duration(profile.median_roundtrip_span_seconds)}")
    print(f"Gap global entre swaps (mediana): {_duration(profile.median_swap_gap_seconds)}")
    dex = ", ".join(f"{name}: {count}" for name, count in profile.dex_mix.items()) or "nenhum"
    print(f"DEX mix: {dex}")

    if profile.flags:
        print()
        print("ALERTAS")
        for flag in profile.flags:
            print(f"- {flag}")

    print()
    print("LIMITAÇÃO IMPORTANTE")
    print(
        "Este relatório descreve sequência on-chain observada. Sem os dados enriquecidos da Data API, "
        "ele não afirma PnL, ROI, liquidez histórica nem qualidade da entrada."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
