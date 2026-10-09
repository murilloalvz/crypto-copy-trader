import argparse
import sys

from src.discovery.solana_tracker import (
    SolanaTrackerAuthenticationError,
    SolanaTrackerClient,
    SolanaTrackerConfigurationError,
    SolanaTrackerError,
)
from src.wallet_research_universe import (
    FREQUENCY_LABELS,
    RESEARCH_REJECTION_LABELS,
    select_research_universe,
)


SOURCE_VIEWS = (
    ("realized", "desc"),
    ("roi", "desc"),
    ("win_percentage", "desc"),
    ("days", "desc"),
    ("trades", "desc"),
)


def _collect_source(client: SolanaTrackerClient, per_view: int) -> list:
    selected = []
    seen = set()
    for current, (sort_by, direction) in enumerate(SOURCE_VIEWS, start=1):
        print(f"[source] {current}/{len(SOURCE_VIEWS)} {sort_by}:{direction}", file=sys.stderr)
        rows = client.top_traders(
            per_view,
            sort_by=sort_by,
            direction=direction,
            days=30,
            min_trades=20,
            min_win_rate=40,
            min_roi=0,
            min_closed_tokens=5,
            max_single_token_pct=40,
            min_invested_usd=500,
            min_trading_days=3,
        )
        for snapshot in rows:
            if snapshot.address in seen:
                continue
            seen.add(snapshot.address)
            selected.append(snapshot)
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Forma um universo diversificado de wallets para pesquisa de estratégia "
            "com poucas chamadas à API. Não aplica gates de copyability."
        )
    )
    parser.add_argument(
        "--per-view",
        type=int,
        default=100,
        help="wallets pedidas por cada uma das 5 visões do leaderboard (padrão: 100)",
    )
    parser.add_argument(
        "--shortlist",
        type=int,
        default=12,
        help="quantidade final para pesquisa posterior (padrão: 12)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 20 <= args.per_view <= 500:
        print("Erro: --per-view precisa ficar entre 20 e 500.", file=sys.stderr)
        return 2
    if not 1 <= args.shortlist <= 100:
        print("Erro: --shortlist precisa ficar entre 1 e 100.", file=sys.stderr)
        return 2

    client = SolanaTrackerClient()
    try:
        snapshots = _collect_source(client, args.per_view)
    except (SolanaTrackerConfigurationError, SolanaTrackerAuthenticationError) as exc:
        print(f"Configuração/créditos: {exc}", file=sys.stderr)
        return 2
    except SolanaTrackerError as exc:
        print(f"Falha na fonte: {exc}", file=sys.stderr)
        return 1

    report = select_research_universe(snapshots, shortlist_limit=args.shortlist)

    print("Crypto Copy Trader — Wallet Research Universe v1")
    print("Modo: RESEARCH / READ ONLY — wave_v3 e gates de copyability permanecem congelados.")
    print(
        f"Fonte deduplicada: {report.source_count} wallets | "
        f"elegíveis para pesquisa: {report.eligible_count}"
    )
    print(
        "Este scanner NÃO chama history/positions por wallet; ele existe para economizar "
        "créditos antes do deep dive."
    )

    if report.rejected_by_reason:
        print()
        print("ELIMINAÇÕES DE QUALIDADE DO UNIVERSO")
        for reason, count in sorted(
            report.rejected_by_reason.items(), key=lambda item: (-item[1], item[0])
        ):
            print(f"- {RESEARCH_REJECTION_LABELS.get(reason, reason)}: {count}")

    print()
    print("DISTRIBUIÇÃO POR FREQUÊNCIA — NÃO É GATE DE COPYABILITY")
    for bucket, count in report.frequency_counts.items():
        print(f"- {FREQUENCY_LABELS[bucket]}: {count}")

    print()
    print("SHORTLIST DIVERSIFICADA PARA ESTRATÉGIA")
    if not report.shortlist:
        print("Nenhuma wallet passou pelos gates amplos de qualidade.")
        return 0

    for index, entry in enumerate(report.shortlist, start=1):
        item = entry.snapshot
        flags = ", ".join(entry.flags) if entry.flags else "sem alerta do estágio barato"
        age = (
            "indisponível"
            if entry.last_trade_age_days is None
            else f"{entry.last_trade_age_days:.1f}d"
        )
        print()
        print(f"{index}. {item.address}")
        print(
            f"Faixa: {FREQUENCY_LABELS[entry.frequency_bucket]} | "
            f"trades {item.trades} | tokens {item.tokens_traded} | dias ativos {item.trading_days}"
        )
        print(
            f"PnL 30d US$ {item.realized_pnl_usd:+,.2f} | ROI {item.roi_pct:+.1f}% | "
            f"win rate {item.win_rate_pct:.1f}% | investido US$ {item.invested_usd:,.0f}"
        )
        print(f"Último trade: {age} | Alertas: {flags}")

    print()
    print("PRÓXIMO PASSO")
    print(
        "Quando houver créditos, aprofundar poucas wallets desta lista com "
        "wallet_intelligence.py. High-frequency permanece útil para estudar a estratégia, "
        "mas não é promovida automaticamente para copy trading."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
