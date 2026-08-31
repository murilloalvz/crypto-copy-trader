import argparse
import json
from dataclasses import asdict
from pathlib import Path

from src.database import initialize_database
from src.wallet_quote_metrics import summarize_wallet_quote_metrics


def _load_addresses(path_value: str | None) -> list[str]:
    if not path_value:
        return []
    path = Path(path_value)
    if not path.exists():
        raise ValueError(f"arquivo de wallets não encontrado: {path}")
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resume cobertura e timing dos probes causais Jupiter do Wallet Quote Watch."
    )
    parser.add_argument("--file", help="coorte opcional de wallets")
    parser.add_argument("--json", action="store_true")
    return parser


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}s"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        addresses = _load_addresses(args.file)
    except ValueError as exc:
        print(f"Erro: {exc}")
        return 2

    initialize_database()
    metrics = summarize_wallet_quote_metrics(wallet_addresses=addresses or None)
    if args.json:
        print(json.dumps(asdict(metrics), ensure_ascii=False, indent=2))
        return 0

    print("Crypto Copy Trader — Wallet Quote Watch Evaluation v1")
    print("Modo: RESEARCH / READ ONLY — cobertura de observabilidade, não PnL.")
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
        print("Sem tentativas causais persistidas ainda.")
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
        "Interpretação: request/completion lag > 0 significa que o snapshot saiu depois do "
        "target planejado. Quote-only não valida execução. Uma transação montada pelo provider "
        "também não prova landing; isso só será testado em estágios posteriores."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
