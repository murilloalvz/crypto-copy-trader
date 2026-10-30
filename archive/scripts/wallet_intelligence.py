import argparse
import json
import sys
from dataclasses import asdict

from src.database import add_wallet, initialize_database, rows
from src.discovery.solana_tracker import (
    SolanaTrackerAuthenticationError,
    SolanaTrackerClient,
    SolanaTrackerConfigurationError,
    SolanaTrackerError,
)
from src.services import sync_wallet
from src.solana import SolanaRPCError
from src.wallet_intelligence import (
    WalletStrategyProfile,
    build_wallet_strategy_profile,
    format_duration,
)


FLAG_LABELS = {
    "position_sample_too_small": "amostra de posições pequena",
    "profit_concentrated_in_top_winner": "lucro bruto concentrado no maior vencedor",
    "positive_pnl_disappears_without_best_position": "PnL positivo desaparece sem a melhor posição",
    "positive_pnl_with_nonpositive_median_roi": "PnL total positivo com ROI mediano não positivo",
    "hold_time_unavailable": "tempo de posição indisponível",
    "holding_time_too_short_for_delayed_copy": "holding típico curto demais para cópia atrasada",
    "liquidity_coverage_low": "cobertura de liquidez insuficiente",
    "liquid_capital_share_low": "pouco capital amostrado em tokens líquidos",
    "onchain_sequence_sample_small": "sequência on-chain local ainda pequena",
}


def _money(value: float) -> str:
    return f"US$ {value:+,.2f}"


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def _local_swaps(address: str) -> list[dict]:
    return rows(
        """SELECT block_time, status, kind, dex, token_mint, token_change
        FROM transactions
        WHERE wallet_address=? AND kind='swap' AND status='success'
        ORDER BY block_time""",
        (address,),
    )


def format_profile(profile: WalletStrategyProfile) -> str:
    pf = "∞" if profile.profit_factor is None and profile.realized_pnl_usd > 0 else (
        "n/a" if profile.profit_factor is None else f"{profile.profit_factor:.2f}"
    )
    dex = (
        ", ".join(f"{name}: {count}" for name, count in profile.dex_mix.items())
        if profile.dex_mix
        else "sem sequência local suficiente"
    )
    lines = [
        "Crypto Copy Trader — Wallet Intelligence v1",
        "",
        f"Wallet: {profile.address}",
        "Modo: RESEARCH / READ ONLY — não altera wave_v3 e não executa ordens.",
        f"Grau da amostra de posições: {profile.sample_grade}",
        "",
        "PERFIL DE ESTRATÉGIA",
        f"Arquétipo temporal: {profile.archetype}",
        f"Estilo de execução observado: {profile.execution_style}",
        f"Posições amostradas: {profile.sampled_positions}",
        (
            f"Holding mediano: {format_duration(profile.median_hold_seconds)} | "
            f"P25/P75: {format_duration(profile.p25_hold_seconds)} / "
            f"{format_duration(profile.p75_hold_seconds)}"
        ),
        (
            f"Ações por token (mediana): {profile.median_actions_per_token:.1f} | "
            f"posições multi-ação: {_pct(profile.multi_action_position_share_pct)}"
        ),
        "",
        "ROBUSTEZ DO RESULTADO",
        (
            f"PnL realizado amostrado: {_money(profile.realized_pnl_usd)} | "
            f"mediana por posição: {_money(profile.median_position_pnl_usd)}"
        ),
        (
            f"Win rate por posições com resultado: {_pct(profile.win_rate_pct)} | "
            f"ROI mediano: {profile.median_roi_pct:+.1f}% | PF: {pf}"
        ),
        (
            f"Melhor/pior posição: {_money(profile.best_position_pnl_usd)} / "
            f"{_money(profile.worst_position_pnl_usd)}"
        ),
        (
            f"Maior vencedor / lucro bruto: {_pct(profile.top_winner_share_pct)} | "
            f"Top 3 / lucro bruto: {_pct(profile.top3_winner_share_pct)}"
        ),
        f"PnL sem o maior vencedor: {_money(profile.pnl_without_top_winner_usd)}",
        "",
        "CONSISTÊNCIA DIÁRIA",
        (
            f"Dias ativos: {profile.active_days} | positivos: {profile.profitable_days} | "
            f"negativos: {profile.losing_days}"
        ),
        (
            f"PnL diário mediano: {_money(profile.median_daily_pnl_usd)} | "
            f"melhor dia / lucro positivo: {_pct(profile.top_positive_day_share_pct)}"
        ),
        f"Drawdown realizado da curva diária: {_money(profile.realized_daily_drawdown_usd)}",
        "",
        "MERCADO / COPYABILITY",
        (
            f"Cobertura de liquidez: {_pct(profile.liquidity_coverage_pct)} | "
            f"tokens líquidos entre conhecidos: {_pct(profile.liquid_position_share_pct)}"
        ),
        (
            f"Capital em tokens líquidos: {_pct(profile.liquid_capital_share_pct)} | "
            f"liquidez atual mediana: US$ {profile.median_current_liquidity_usd:,.0f}"
        ),
        (
            f"Market cap atual mediano: US$ {profile.median_current_market_cap_usd:,.0f} | "
            f"microcaps <US$2M: {_pct(profile.microcap_position_share_pct)} | "
            f"US$2M–20M: {_pct(profile.smallcap_position_share_pct)}"
        ),
        "",
        "SEQUÊNCIA ON-CHAIN LOCAL",
        (
            f"Swaps: {profile.local_swap_count} | tokens: {profile.local_token_count} | "
            f"compras/vendas: {profile.local_buy_count}/{profile.local_sell_count}"
        ),
        (
            f"Tokens com buy+sell: {_pct(profile.local_roundtrip_token_share_pct)} | "
            f"tokens multi-ação: {_pct(profile.local_multi_action_token_share_pct)}"
        ),
        f"Gap mediano entre swaps: {format_duration(profile.median_local_swap_gap_seconds)}",
        f"DEX mix: {dex}",
        "",
        (
            "Pronta para pesquisa explícita de atraso: SIM"
            if profile.delay_research_ready
            else "Pronta para pesquisa explícita de atraso: NÃO — ampliar/qualificar evidência primeiro"
        ),
    ]
    if profile.flags:
        lines.extend(
            [
                "",
                "ALERTAS DE PESQUISA",
                *[f"- {FLAG_LABELS.get(flag, flag)}" for flag in profile.flags],
            ]
        )
    lines.extend(["", "LIMITAÇÕES", *[f"- {item}" for item in profile.limitations]])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Perfila a estratégia observável de uma wallet pública sem executar trades."
    )
    parser.add_argument("address", help="endereço público Solana")
    parser.add_argument("--positions", type=int, default=100)
    parser.add_argument("--history", default="90d", choices=("30d", "90d", "all"))
    parser.add_argument(
        "--sync-onchain",
        action="store_true",
        help="sincroniza uma página recente de transações RPC antes da análise",
    )
    parser.add_argument("--label", default="Wallet Intelligence")
    parser.add_argument("--json", action="store_true", help="imprime JSON em vez do relatório")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 5 <= args.positions <= 200:
        print("Erro: --positions precisa ficar entre 5 e 200.", file=sys.stderr)
        return 2

    initialize_database()
    if args.sync_onchain:
        add_wallet(args.address, args.label)
        try:
            result = sync_wallet(args.address)
        except (SolanaRPCError, ValueError) as exc:
            print(f"Falha ao sincronizar sequência on-chain: {exc}", file=sys.stderr)
            return 1
        print(
            "[on-chain] "
            f"{result['inserted']} novas | {result['skipped']} já conhecidas | "
            f"{result['failed']} falhas"
        )

    client = SolanaTrackerClient()
    try:
        history = client.wallet_history(args.address, args.history)
        positions = client.wallet_positions(
            args.address, period="30d", limit=args.positions
        )
    except (SolanaTrackerConfigurationError, SolanaTrackerAuthenticationError) as exc:
        print(f"Configuração necessária: {exc}", file=sys.stderr)
        return 2
    except (SolanaTrackerError, ValueError) as exc:
        print(f"Falha ao obter dados da wallet: {exc}", file=sys.stderr)
        return 1

    profile = build_wallet_strategy_profile(
        args.address,
        history,
        positions,
        _local_swaps(args.address),
    )
    if args.json:
        print(json.dumps(asdict(profile), ensure_ascii=False, indent=2))
    else:
        print(format_profile(profile))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
