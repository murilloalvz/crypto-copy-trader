import argparse
import json
from dataclasses import asdict

from src.database import initialize_database
from src.wallet_forward_runs import get_wallet_forward_run, latest_wallet_forward_run
from src.wallet_quote_provider_quality import summarize_wallet_quote_provider_quality
from src.wallet_quote_watch import load_forward_buys_after


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resume metadados de rota/impacto persistidos pelo Jupiter no grid causal da run. "
            "Não mede fill nem PnL."
        )
    )
    parser.add_argument("--run-key", help="run específica; padrão = COMPLETED mais recente")
    parser.add_argument("--json", action="store_true")
    return parser


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _fmt_usd(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.4f}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    initialize_database()
    run = (
        get_wallet_forward_run(args.run_key)
        if args.run_key
        else latest_wallet_forward_run(completed_only=True)
    )
    if run is None:
        print("Nenhuma Wallet Forward Run compatível encontrada.")
        return 0

    buys = load_forward_buys_after(
        run.baseline_observation_id,
        wallet_addresses=list(run.cohort),
        through_id=run.end_observation_id,
    )
    summary = summarize_wallet_quote_provider_quality(
        buys,
        delays_seconds=run.quote_delays_seconds if run.with_jupiter_quotes else (),
    )

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "run": asdict(run),
                    "provider_quality": asdict(summary),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Jupiter Provider Quality v1")
    print("Modo: RESEARCH / READ ONLY — provider metadata, não landing/fill/PnL.")
    print(
        f"Run: {run.run_key} | runtime {run.runtime_version} | BUYs {summary.buy_event_count} | "
        f"quotes esperadas {summary.expected_quote_count} | sucesso {summary.successful_quote_count}"
    )
    print(
        f"Quotes de sucesso com metadata nova: {summary.metadata_count}/"
        f"{summary.successful_quote_count} ({summary.metadata_coverage_pct:.1f}%)"
    )
    if summary.successful_quote_count and not summary.metadata_count:
        print(
            "Esta amostra contém quotes anteriores à persistência desses campos. "
            "Não fazemos backfill inventado de priceImpact/slippage/router."
        )

    for item in summary.delays:
        routers = ", ".join(f"{name}={count}" for name, count in item.routers) or "n/a"
        print(
            f"- +{item.delay_seconds}s | success {item.successful_quote_count}/"
            f"{item.expected_count} | metadata {item.metadata_count} "
            f"({item.metadata_coverage_pct:.1f}%) | Jupiter impact med raw "
            f"{_fmt(item.median_price_impact_pct_points)} | p95 |impact| "
            f"{_fmt(item.p95_abs_price_impact_pct_points)} | slippage bps med "
            f"{_fmt(item.median_slippage_bps)} | swap USD med "
            f"{_fmt_usd(item.median_swap_usd_value)} | routers {routers}"
        )

    print()
    print("INTERPRETAÇÃO")
    print("- priceImpact é o campo bruto do Jupiter; sinal/magnitude não são fill realizado.")
    print("- slippageBps é metadata/configuração do provider, não slippage efetivamente pago.")
    print("- assembled transaction também continua sendo candidata, não prova landing.")
    print("- Esses campos passam a ser úteis prospectivamente; a run legacy atual pode ficar sem eles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
