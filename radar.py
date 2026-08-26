import argparse
import sys
from datetime import datetime, timezone

from src.discovery.solana_tracker import (
    SolanaTrackerAuthenticationError,
    SolanaTrackerConfigurationError,
    SolanaTrackerError,
    SolanaTrackerClient,
)
from src.wave_radar import (
    RADAR_BARRIER_LABELS,
    WaveRadarPolicy,
    build_wave_radar_report,
)


def _short_address(address: str) -> str:
    return f"{address[:5]}...{address[-5:]}"


def _money(value: float) -> str:
    return f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _age(created_at_ms: int | None, now_ms: int) -> str:
    if created_at_ms is None:
        return "indisponível"
    seconds = max(0, (now_ms - created_at_ms) / 1_000)
    if seconds < 3_600:
        return f"{seconds / 60:.0f}min"
    if seconds < 86_400:
        return f"{seconds / 3_600:.1f}h"
    return f"{seconds / 86_400:.1f}d"


def format_report(report, *, top_n: int = 10, now_ms: int | None = None) -> str:
    now_ms = now_ms or int(datetime.now(timezone.utc).timestamp() * 1_000)
    lines = [
        "Crypto Copy Trader — Wave Radar",
        "",
        "Fonte: Solana Tracker Token Search | Janela de atividade: 5 minutos",
        "Modo: READ ONLY — nenhum token é comprado ou adicionado ao paper trading.",
        "",
        f"Tokens analisados: {report.analyzed_count}",
        f"Aptos para paper signal: {report.passed_count}",
        f"Descartados pelas barreiras: {report.analyzed_count - report.passed_count}",
    ]
    if report.rejected_by_reason:
        lines.extend(["", "PRINCIPAIS BARREIRAS"])
        for key, count in sorted(
            report.rejected_by_reason.items(), key=lambda item: (-item[1], item[0])
        ):
            lines.append(f"- {RADAR_BARRIER_LABELS.get(key, key)}: {count}")

    top = list(report.results[:top_n])
    lines.extend(["", f"TOP {len(top)} TOKENS MONITORADOS"])
    if not top:
        lines.append("Nenhum token foi retornado pela fonte nesta rodada.")
    for index, result in enumerate(top, start=1):
        token = result.token
        label = token.symbol or token.name or _short_address(token.token)
        lines.extend(
            [
                "",
                f"{index}. {label} | {'APTA PARA PAPER SIGNAL' if result.passed else 'DESCARTADA'}",
                f"Mint: {token.token}",
                f"Wave Score inicial: {result.wave_score:.1f}/100",
                (
                    f"Liquidez: US$ {_money(token.liquidity_usd)} | "
                    f"Market cap: US$ {_money(token.market_cap_usd)}"
                ),
                (
                    f"Volume 5m/1h/24h: US$ {_money(token.volume_5m_usd)} / "
                    f"US$ {_money(token.volume_1h_usd)} / US$ {_money(token.volume_24h_usd)}"
                ),
                (
                    f"Holders: {token.holders} | Transações: {token.total_transactions} | "
                    f"Idade: {_age(token.created_at_ms, now_ms)}"
                ),
                (
                    f"Top 10: {token.top10_pct:.1f}% | Dev: {token.dev_pct:.1f}% | "
                    f"Insiders: {token.insiders_pct:.1f}% | Snipers: {token.snipers_pct:.1f}%"
                    if None not in (
                        token.top10_pct,
                        token.dev_pct,
                        token.insiders_pct,
                        token.snipers_pct,
                    )
                    else "Distribuição: dados parciais"
                ),
                "Motivos: " + "; ".join(result.reasons),
            ]
        )
        if result.barriers:
            lines.append(
                "Barreiras: "
                + "; ".join(RADAR_BARRIER_LABELS.get(item, item) for item in result.barriers)
            )
    lines.extend(
        [
            "",
            "IMPORTANTE",
            "- Wave Score ordena atividade atual; não prevê valorização futura.",
            "- APTA significa apenas que passou pelos filtros para futura simulação.",
            "- Convergência de wallets e acompanhamento do preço entram no próximo marco.",
            "- Nenhuma chave privada, assinatura, compra ou venda é utilizada.",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Encontra tokens Solana com atividade recente sem executar trades."
    )
    parser.add_argument("--tokens", type=int, default=100)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--min-liquidity", type=float, default=50_000)
    parser.add_argument("--min-volume-5m", type=float, default=5_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.tokens <= 100 or not 1 <= args.top <= 100:
        print("Erro: --tokens e --top precisam estar entre 1 e 100.", file=sys.stderr)
        return 2
    if args.min_liquidity <= 0 or args.min_volume_5m <= 0:
        print("Erro: os mínimos de liquidez e volume precisam ser positivos.", file=sys.stderr)
        return 2
    policy = WaveRadarPolicy(
        min_liquidity_usd=args.min_liquidity,
        min_volume_5m_usd=args.min_volume_5m,
    )
    client = SolanaTrackerClient()
    try:
        tokens = client.wave_tokens(
            args.tokens,
            min_liquidity_usd=policy.min_liquidity_usd,
            min_volume_5m_usd=policy.min_volume_5m_usd,
        )
    except (SolanaTrackerConfigurationError, SolanaTrackerAuthenticationError) as exc:
        print(f"Configuração necessária: {exc}", file=sys.stderr)
        return 2
    except SolanaTrackerError as exc:
        print(f"Falha no Wave Radar: {exc}", file=sys.stderr)
        return 1
    print(format_report(build_wave_radar_report(tokens, policy), top_n=args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
