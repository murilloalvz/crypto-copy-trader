import argparse
import sys

from src.discovery.ranking import REJECTION_LABELS
from src.discovery.solana_tracker import (
    SolanaTrackerAuthenticationError,
    SolanaTrackerConfigurationError,
    SolanaTrackerError,
)
from src.discovery.tracker_service import SolanaTrackerDiscoveryService


def _short_address(address: str) -> str:
    return f"{address[:5]}...{address[-5:]}"


def _money(value: float) -> str:
    return f"{value:+,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "indisponível"
    if seconds < 60:
        return "<1s" if seconds < 1 else f"{seconds:.0f}s"
    if seconds < 3_600:
        return f"{seconds / 60:.1f}min"
    return f"{seconds / 3_600:.1f}h"


def format_report(report, top_n: int = 10) -> str:
    lines = [
        "Crypto Copy Trader — Wallet Discovery",
        "",
        "Fonte: Solana Tracker PnL V2 | Rede: Solana | Janela principal: 30d",
        "Amostra: PnL, ROI, win rate, dias ativos e menor frequência, sem duplicatas.",
        "Proteções da fonte: arbitragem excluída, PnL estrito e no máximo 30% do lucro por token.",
        "",
        f"Wallets analisadas: {report.source_count}",
        f"Passaram pelos filtros locais: {report.prefiltered_count}",
        f"Históricos avaliados: {report.fully_evaluated_count}",
        f"Passaram para o ranking: {report.passed_count}",
        f"Eliminadas pelos filtros locais: {report.rejected_count}",
        f"Falhas de dados: {len(report.data_errors)}",
    ]
    if report.rejected_by_reason:
        lines.extend(["", "PRINCIPAIS ELIMINAÇÕES"])
        for key, count in sorted(
            report.rejected_by_reason.items(), key=lambda item: (-item[1], item[0])
        ):
            lines.append(f"- {REJECTION_LABELS.get(key, key)}: {count}")

    top = list(report.candidates[:top_n])
    lines.extend(["", f"TOP {len(top)} CANDIDATAS"])
    if not top:
        lines.append("Nenhuma wallet reuniu dados suficientes para o ranking.")
    for position, candidate in enumerate(top, start=1):
        metrics = candidate.metrics_30d
        signals = candidate.signals
        lines.extend(
            [
                "",
                f"{position}. {_short_address(candidate.address)}",
                f"Endereço: {candidate.address}",
                f"Candidate Score: {candidate.candidate_score:.1f}/100",
                f"PnL realizado 30d: US$ {_money(metrics.realized_pnl_usd)}",
                f"ROI 30d: {metrics.roi_pct:+.1f}% | Win rate: {metrics.win_rate_pct:.1f}%",
                f"Capital investido 30d: US$ {_money(metrics.total_invested_usd)}",
                f"Trades: {metrics.total_trade} | Tokens: {metrics.unique_tokens}",
                (
                    f"PnL 7d/90d: US$ {_money(candidate.metrics_7d.realized_pnl_usd)} / "
                    f"US$ {_money(candidate.metrics_90d.realized_pnl_usd)}"
                    if candidate.metrics_90d is not None
                    else f"PnL 7d: US$ {_money(candidate.metrics_7d.realized_pnl_usd)}"
                ),
            ]
        )
        if signals is not None:
            lines.append(
                f"Drawdown realizado: {signals.realized_drawdown_pct:.1f}% | "
                f"Posição média: {_duration(signals.avg_hold_seconds)}"
            )
        lines.append("Motivos: " + "; ".join(candidate.reasons[:6]))
        if candidate.penalties:
            lines.append("Penalizações: " + "; ".join(candidate.penalties))

    if top:
        lines.extend(
            [
                "",
                "WALLET DE LABORATÓRIO SUGERIDA",
                top[0].address,
                "Use esse endereço público no tracker atual. Isso não é recomendação financeira.",
            ]
        )
    lines.extend(
        [
            "",
            "LIMITAÇÕES DESTA ETAPA",
            "- O score serve apenas para ordenar candidatas; não mede copyability completa.",
            "- A fonte filtra concentração por token, mas não retorna a distribuição de cada trade.",
            "- Liquidez dos tokens operados ainda não entra no score.",
            "- Nenhuma chave privada, assinatura ou ordem é usada.",
        ]
    )
    return "\n".join(lines)


def _progress(stage: str, current: int, total: int, address: str) -> None:
    if not total:
        return
    message = f"[{stage}] {current}/{total} {_short_address(address)}"
    if sys.stderr.isatty():
        print(f"\r{message:<70}", end="", file=sys.stderr, flush=True)
        if current == total:
            print(file=sys.stderr)
    elif current == 1 or current == total or current % 25 == 0:
        print(message, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Descobre e ranqueia wallets públicas da Solana sem executar trades."
    )
    parser.add_argument(
        "--wallets", type=int, default=250, help="quantidade a analisar (padrão: 250)"
    )
    parser.add_argument(
        "--top", type=int, default=10, help="quantidade exibida no ranking (padrão: 10)"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="oculta o progresso durante a coleta"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.wallets <= 10_000:
        print("Erro: --wallets precisa estar entre 1 e 10000.", file=sys.stderr)
        return 2
    if not 1 <= args.top <= 100:
        print("Erro: --top precisa estar entre 1 e 100.", file=sys.stderr)
        return 2
    service = SolanaTrackerDiscoveryService(
        progress=None if args.quiet else _progress
    )
    try:
        report = service.discover(args.wallets)
    except (SolanaTrackerConfigurationError, SolanaTrackerAuthenticationError) as exc:
        print(f"Configuração necessária: {exc}", file=sys.stderr)
        return 2
    except SolanaTrackerError as exc:
        print(f"Falha na fonte de discovery: {exc}", file=sys.stderr)
        return 1
    print(format_report(report, args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
