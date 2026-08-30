import argparse
import sys

from src.discovery.copyability import COPYABILITY_REJECTION_LABELS
from src.discovery.ranking import REJECTION_LABELS
from src.discovery.solana_tracker import (
    SolanaTrackerAuthenticationError,
    SolanaTrackerConfigurationError,
    SolanaTrackerError,
)
from src.discovery.tracker_service import SolanaTrackerDiscoveryService
from src.wallet_intelligence import build_wallet_strategy_profile, format_duration


def _short(address: str) -> str:
    return f"{address[:6]}...{address[-6:]}"


def _print_reason_counts(title: str, counts: dict[str, int], labels: dict[str, str]) -> None:
    if not counts:
        return
    print()
    print(title)
    for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"- {labels.get(key, key)}: {count}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Descobre big wallets e cria shortlist para pesquisa de estratégia."
    )
    parser.add_argument("--wallets", type=int, default=250)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--copyability-limit", type=int, default=25)
    parser.add_argument("--liquid-seeds", type=int, default=25)
    parser.add_argument("--positions", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.wallets <= 10_000:
        print("Erro: --wallets precisa ficar entre 1 e 10000.", file=sys.stderr)
        return 2
    if not 1 <= args.top <= 25:
        print("Erro: --top precisa ficar entre 1 e 25.", file=sys.stderr)
        return 2
    if not args.top <= args.copyability_limit <= 100:
        print(
            "Erro: --copyability-limit precisa ser >= --top e <= 100.",
            file=sys.stderr,
        )
        return 2
    if not 0 <= args.liquid_seeds <= min(args.wallets, 200):
        print("Erro: --liquid-seeds inválido para o universo solicitado.", file=sys.stderr)
        return 2
    if not 5 <= args.positions <= 200:
        print("Erro: --positions precisa ficar entre 5 e 200.", file=sys.stderr)
        return 2

    service = SolanaTrackerDiscoveryService()
    try:
        discovery = service.discover(
            args.wallets,
            copyability_limit=args.copyability_limit,
            liquid_seed_limit=args.liquid_seeds,
        )
    except (SolanaTrackerConfigurationError, SolanaTrackerAuthenticationError) as exc:
        print(f"Configuração necessária: {exc}", file=sys.stderr)
        return 2
    except SolanaTrackerError as exc:
        print(f"Falha no discovery: {exc}", file=sys.stderr)
        return 1

    shortlist = list(discovery.copyability_results[: args.top])
    print("Crypto Copy Trader — Big Wallet Strategy Research")
    print("Modo: RESEARCH / READ ONLY — wave_v3 permanece congelada.")
    print(
        f"Discovery: {discovery.source_count} fontes | "
        f"{discovery.passed_count} Candidate Score | "
        f"{discovery.copyability_evaluated_count} avaliadas por copyability"
    )
    _print_reason_counts(
        "PRINCIPAIS ELIMINAÇÕES DO DISCOVERY",
        discovery.rejected_by_reason,
        REJECTION_LABELS,
    )
    _print_reason_counts(
        "PRINCIPAIS BARREIRAS DE COPYABILITY",
        discovery.copyability_rejected_by_reason,
        COPYABILITY_REJECTION_LABELS,
    )
    if discovery.data_errors:
        print()
        print(f"Falhas de dados no funil: {len(discovery.data_errors)}")
    if not shortlist:
        print("Nenhuma wallet com dados suficientes nesta rodada.")
        return 0

    profiles = []
    for index, copyability in enumerate(shortlist, start=1):
        address = copyability.candidate.address
        print(f"[strategy] {index}/{len(shortlist)} {_short(address)}", file=sys.stderr)
        try:
            history = service.client.wallet_history(address, "90d")
            positions = service.client.wallet_positions(
                address, period="30d", limit=args.positions
            )
        except SolanaTrackerError as exc:
            print(f"[strategy] falha em {_short(address)}: {exc}", file=sys.stderr)
            continue
        profile = build_wallet_strategy_profile(address, history, positions)
        profiles.append((copyability, profile))

    print()
    print("SHORTLIST DE PESQUISA")
    for index, (copyability, profile) in enumerate(profiles, start=1):
        candidate = copyability.candidate
        flags = ", ".join(profile.flags[:3]) if profile.flags else "sem alerta estrutural principal"
        print()
        print(f"{index}. {candidate.address}")
        print(
            f"Candidate {candidate.candidate_score:.1f} | "
            f"Copyability {copyability.copyability_score:.1f} | "
            f"arquétipo {profile.archetype}"
        )
        print(
            f"Posições {profile.sampled_positions} | "
            f"PnL US$ {profile.realized_pnl_usd:+,.2f} | "
            f"ROI mediano {profile.median_roi_pct:+.1f}% | "
            f"hold {format_duration(profile.median_hold_seconds)}"
        )
        print(
            f"Top winner {profile.top_winner_share_pct:.1f}% do lucro bruto | "
            f"PnL sem melhor US$ {profile.pnl_without_top_winner_usd:+,.2f} | "
            f"capital líquido {profile.liquid_capital_share_pct:.1f}%"
        )
        print(
            "Status atraso: "
            + ("PRONTA PARA DEEP DIVE" if profile.delay_research_ready else "AMPLIAR EVIDÊNCIA")
        )
        print(f"Alertas: {flags}")

    ready = [
        (copyability, profile)
        for copyability, profile in profiles
        if profile.delay_research_ready
        and profile.realized_pnl_usd > 0
        and profile.pnl_without_top_winner_usd > 0
    ]
    print()
    print("PRÓXIMO PASSO")
    if ready:
        print(
            "Priorizar sincronização on-chain das primeiras wallets abaixo; "
            "isso ainda não autoriza cópia:"
        )
        for copyability, profile in ready[:5]:
            print(
                f"- {profile.address} | hold {format_duration(profile.median_hold_seconds)} | "
                f"top winner {profile.top_winner_share_pct:.1f}%"
            )
        print(
            "Depois: reconstruir sequência buy/sell e testar atraso com dados de execução "
            "mais finos que candle de 1 minuto."
        )
    else:
        print(
            "Nenhuma wallet passou simultaneamente pelos gates mínimos de deep dive nesta rodada. "
            "Não afrouxar critérios só para produzir candidatas."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
