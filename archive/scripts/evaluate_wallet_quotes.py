import argparse
import json
from dataclasses import asdict
from pathlib import Path

from src.database import initialize_database
from src.wallet_forward_runs import get_wallet_forward_run, latest_wallet_forward_run
from src.wallet_quote_metrics import summarize_wallet_quote_metrics
from src.wallet_quote_watch import load_forward_buys_after


def _load_addresses(path_value: str | None) -> list[str]:
    if not path_value:
        return []
    path = Path(path_value)
    if not path.exists():
        raise ValueError(f"arquivo de wallets não encontrado: {path}")
    return list(
        dict.fromkeys(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resume cobertura e timing dos probes causais Jupiter. Por padrão usa a "
            "Wallet Forward Run COMPLETED mais recente e somente seus BUYs."
        )
    )
    parser.add_argument("--file", help="coorte opcional no modo --all-history")
    parser.add_argument("--run-key", help="run específica; padrão = COMPLETED mais recente")
    parser.add_argument(
        "--all-history",
        action="store_true",
        help="modo legado explícito: agrega attempts históricos sem run manifest",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}s"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.run_key and args.all_history:
        print("Erro: --run-key e --all-history são mutuamente exclusivos.")
        return 2
    if args.file and not args.all_history:
        print("Erro: --file é permitido somente com --all-history; use o cohort congelado da run.")
        return 2

    initialize_database()
    run = None
    addresses: list[str] = []
    source_event_keys: list[str] | None = None
    if args.all_history:
        try:
            addresses = _load_addresses(args.file)
        except ValueError as exc:
            print(f"Erro: {exc}")
            return 2
    else:
        run = (
            get_wallet_forward_run(args.run_key)
            if args.run_key
            else latest_wallet_forward_run(completed_only=True)
        )
        if args.run_key and run is None:
            print(f"Erro: run não encontrada: {args.run_key}")
            return 2
        if run is not None:
            addresses = list(run.cohort)
            buys = load_forward_buys_after(
                run.baseline_observation_id,
                wallet_addresses=addresses,
                through_id=run.end_observation_id,
            )
            source_event_keys = [item.observation_key for item in buys]
        else:
            # No manifest exists yet: keep the old aggregate behavior visible rather than
            # pretending the historical rows belong to one run.
            source_event_keys = None

    metrics = summarize_wallet_quote_metrics(
        wallet_addresses=addresses or None,
        source_event_keys=source_event_keys,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "scope": (
                        {"mode": "RUN_MANIFEST", "run": asdict(run)}
                        if run is not None
                        else {"mode": "ALL_HISTORY"}
                    ),
                    "metrics": asdict(metrics),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Wallet Quote Watch Evaluation v2")
    print("Modo: RESEARCH / READ ONLY — cobertura de observabilidade, não PnL.")
    if run is not None:
        print(
            f"Escopo: {run.run_key} | runtime {run.runtime_version} | status {run.status} | "
            f"BUYs event-scoped {len(source_event_keys or [])}"
        )
    else:
        print("Escopo: ALL_HISTORY — sem run manifest; coletas diferentes podem estar misturadas.")
    print(
        f"Tentativas: {metrics.attempt_count} | sucesso {metrics.success_count} "
        f"({metrics.success_pct:.1f}%) | falhas {metrics.failure_count} | "
        f"wallets {metrics.wallet_count} | tokens {metrics.token_count}"
    )
    print(
        f"Quotes com transação candidata montada: {metrics.executable_count} | "
        f"quote-only/proxy: {metrics.proxy_count}"
    )
    if not metrics.delays:
        print("Sem tentativas causais persistidas neste escopo.")
        return 0

    print()
    print("POR DELAY")
    for item in metrics.delays:
        print(
            f"+{item.delay_seconds}s | {item.success_count}/{item.attempt_count} "
            f"({item.success_pct:.1f}%) | tx candidata {item.executable_count} | "
            f"proxy {item.proxy_count} | request lag med/p95 "
            f"{_fmt(item.median_request_lag_seconds)}/{_fmt(item.p95_request_lag_seconds)} | "
            f"complete lag med/p95 "
            f"{_fmt(item.median_completion_lag_seconds)}/{_fmt(item.p95_completion_lag_seconds)}"
        )
        if item.errors:
            print("  erros: " + ", ".join(f"{name}={count}" for name, count in item.errors))

    print()
    print(
        "Interpretação: attempt coverage mede apenas probes iniciados; use também "
        "wallet_quote_completeness.py para manter probes nunca iniciados no denominador. "
        "Quote-only não valida execução e transação montada não prova landing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
