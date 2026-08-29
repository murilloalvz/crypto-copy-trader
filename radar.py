import argparse
import sys
import time
from datetime import datetime, timezone

from src.discovery.solana_tracker import (
    SolanaTrackerAuthenticationError,
    SolanaTrackerConfigurationError,
    SolanaTrackerError,
    SolanaTrackerClient,
)
from src.database import initialize_database
from src.wave_radar import (
    RADAR_BARRIER_LABELS,
    RADAR_CAUTION_LABELS,
    WaveRadarPolicy,
    build_wave_radar_report,
)
from src.wave_paper import latest_paper_signals, run_wave_paper_cycle
from src.wave_funnel import record_discovery_run, record_failed_discovery


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
        "Modo: READ ONLY — nenhum token é comprado; sinais ficam somente no banco local.",
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
                    f"Holders: {token.holders if token.holders is not None else 'indisponível'} | "
                    f"Transações: {token.total_transactions} | "
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
        if result.cautions:
            lines.append(
                "Atenções: "
                + "; ".join(RADAR_CAUTION_LABELS.get(item, item) for item in result.cautions)
            )
    lines.extend(
        [
            "",
            "IMPORTANTE",
            "- Wave Score ordena atividade atual; não prevê valorização futura.",
            "- APTA significa apenas que passou pelos filtros para simulação local.",
            "- Convergência de wallets ainda será uma confirmação adicional futura.",
            "- Nenhuma chave privada, assinatura, compra ou venda é utilizada.",
        ]
    )
    return "\n".join(lines)


def format_paper_report(update, signals: list[dict], *, now: int) -> str:
    lines = [
        "LABORATÓRIO PAPER DO RADAR",
        "",
        f"Novos sinais salvos: {update.created_signals}",
        f"Horizontes atualizados nesta rodada: {update.completed_checks}",
        f"Horizontes com falha definitiva: {update.failed_checks}",
        f"Horizontes ainda pendentes: {update.pending_checks}",
        (
            "Exit engine v1: "
            f"{getattr(update, 'exit_enrolled_signals', 0)} sinais pareados | "
            f"{getattr(update, 'exit_created_positions', 0)} posições abertas | "
            f"{getattr(update, 'exit_closed_positions', 0)} fechadas nesta rodada | "
            f"{getattr(update, 'exit_open_positions', 0)} ainda abertas | "
            f"{getattr(update, 'exit_price_failures', 0)} falhas de observação"
        ),
    ]
    if not signals:
        lines.extend(["", "Nenhum sinal apto foi salvo até agora."])
        return "\n".join(lines)

    lines.extend(["", "SINAIS MAIS RECENTES"])
    for signal in signals:
        label = signal["symbol"] or signal["name"] or _short_address(signal["token_mint"])
        lines.extend(
            [
                "",
                f"{label} | {signal['status'].upper()}",
                f"Estratégia: {signal.get('strategy_version', 'não versionada')}",
                f"Mint: {signal['token_mint']}",
                (
                    f"Entrada observada: US$ {signal['entry_market_price_usd']:.10g} | "
                    f"execução paper: US$ {signal['entry_execution_price_usd']:.10g}"
                ),
                (
                    f"Tamanho fictício: US$ {_money(signal['copy_size_usd'])} | "
                    f"slippage por lado: {signal['slippage_bps'] / 100:.2f}%"
                ),
            ]
        )
        for check in signal["checks"]:
            horizon = f"{check['horizon_minutes']}m"
            if check["status"] == "completed":
                lines.append(
                    f"- {horizon}: retorno líquido {check['return_pct']:+.2f}% | "
                    f"P&L paper US$ {check['pnl_usd']:+.2f}"
                )
            elif check["status"] == "failed":
                lines.append(f"- {horizon}: falha de preço — {check['error']}")
            else:
                remaining = max(0, int((check["target_at"] - now + 59) / 60))
                lines.append(f"- {horizon}: pendente (aprox. {remaining} min)")
    lines.extend(
        [
            "",
            "O retorno líquido aplica o slippage configurado na entrada e na saída.",
            "Nenhuma ordem, assinatura ou movimentação de dinheiro é realizada.",
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
    parser.add_argument("--min-acceleration", type=float, default=1.2)
    parser.add_argument("--min-wave-score", type=float, default=55)
    parser.add_argument(
        "--no-paper",
        action="store_true",
        help="Não salva nem atualiza o laboratório paper nesta execução.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.tokens <= 100 or not 1 <= args.top <= 100:
        print("Erro: --tokens e --top precisam estar entre 1 e 100.", file=sys.stderr)
        return 2
    if (
        args.min_liquidity <= 0
        or args.min_volume_5m <= 0
        or args.min_acceleration <= 0
        or not 0 <= args.min_wave_score <= 100
    ):
        print(
            "Erro: os limites de liquidez, volume, aceleração e score são inválidos.",
            file=sys.stderr,
        )
        return 2
    policy = WaveRadarPolicy(
        min_liquidity_usd=args.min_liquidity,
        min_volume_5m_usd=args.min_volume_5m,
        min_volume_acceleration=args.min_acceleration,
        min_wave_score=args.min_wave_score,
    )
    discovery_started_at_ms = int(time.time() * 1_000)
    client = SolanaTrackerClient()
    try:
        tokens = client.wave_tokens(
            args.tokens,
            min_liquidity_usd=policy.min_liquidity_usd,
            min_volume_5m_usd=policy.min_volume_5m_usd,
        )
    except (SolanaTrackerConfigurationError, SolanaTrackerAuthenticationError) as exc:
        if not args.no_paper:
            initialize_database()
            record_failed_discovery(
                requested_token_limit=args.tokens,
                policy=policy,
                error=str(exc),
                started_at_ms=discovery_started_at_ms,
            )
        print(f"Configuração necessária: {exc}", file=sys.stderr)
        return 2
    except SolanaTrackerError as exc:
        if not args.no_paper:
            initialize_database()
            record_failed_discovery(
                requested_token_limit=args.tokens,
                policy=policy,
                error=str(exc),
                started_at_ms=discovery_started_at_ms,
            )
        print(f"Falha no Wave Radar: {exc}", file=sys.stderr)
        return 1
    report = build_wave_radar_report(tokens, policy)
    print(format_report(report, top_n=args.top))
    if not args.no_paper:
        initialize_database()
        now = int(datetime.now(timezone.utc).timestamp())
        update = run_wave_paper_cycle(report.results, now=now)
        funnel = record_discovery_run(
            report,
            requested_token_limit=args.tokens,
            returned_count=len(tokens),
            source_item_count=getattr(client, "last_wave_diagnostics", {}).get(
                "source_item_count", len(tokens)
            ),
            source_invalid_count=getattr(client, "last_wave_diagnostics", {}).get(
                "source_invalid_count", 0
            ),
            source_duplicate_count=getattr(client, "last_wave_diagnostics", {}).get(
                "source_duplicate_count", 0
            ),
            policy=policy,
            outcomes=update.persistence_outcomes,
            started_at_ms=discovery_started_at_ms,
        )
        print()
        print(format_paper_report(update, latest_paper_signals(10), now=now))
        print()
        print("FUNIL AUDITÁVEL DESTA RODADA")
        print(
            f"Solicitados à fonte: até {funnel.requested_limit} | "
            f"itens brutos: {funnel.source_items} | retornados únicos: {funnel.discovered} | "
            f"dados válidos: {funnel.data_valid} | "
            f"candidatos v3: {funnel.candidates} | sinais novos: {funnel.signals_created}"
        )
        print(
            f"Fonte inválidos/duplicados: {funnel.source_invalid}/{funnel.source_duplicates} | "
            f"Cooldown/duplicados de sinal: {funnel.duplicates} | "
            f"rejeitados na persistência: {funnel.persistence_rejected} | "
            f"run_id: {funnel.run_id}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
