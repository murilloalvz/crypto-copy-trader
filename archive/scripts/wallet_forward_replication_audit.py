import argparse
import json

from src.database import initialize_database
from src.wallet_forward_replication_audit import (
    build_wallet_forward_replication_audit,
    replication_audit_as_dict,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audita replicações Wallet Forward separadamente, com replay quantity-aware, "
            "dependência e cobertura causal. RESEARCH/READ ONLY."
        )
    )
    parser.add_argument(
        "--run-key",
        action="append",
        dest="run_keys",
        required=True,
        help="run específica; repita pelo menos duas vezes",
    )
    parser.add_argument("--delays", type=int, nargs="*", default=[0, 15, 30, 60, 120])
    parser.add_argument("--allow-proxy-quotes", action="store_true")
    parser.add_argument("--slippage-bps", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    return parser


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if len(set(args.run_keys)) < 2:
        print("Erro: informe pelo menos duas --run-key distintas.")
        return 2
    if any(delay < 0 for delay in args.delays):
        print("Erro: --delays precisa conter apenas valores >= 0.")
        return 2
    if args.slippage_bps < 0:
        print("Erro: --slippage-bps precisa ser >= 0.")
        return 2

    initialize_database()
    try:
        audit = build_wallet_forward_replication_audit(
            args.run_keys,
            delays=tuple(args.delays),
            allow_proxy_quotes=args.allow_proxy_quotes,
            slippage_bps=args.slippage_bps,
        )
    except ValueError as exc:
        print(f"Erro: {exc}")
        return 2

    if args.json:
        print(json.dumps(replication_audit_as_dict(audit), ensure_ascii=False, indent=2))
        return 0

    print("Crypto Copy Trader — Wallet Forward Replication Audit v1")
    print("Modo: RESEARCH / READ ONLY — runs nunca são pooled automaticamente.")
    print(
        f"Compatibilidade: {audit.compatibility.label} | "
        f"interpretação: {audit.interpretation}"
    )
    if audit.compatibility.differing_fields:
        print("Diferenças técnicas: " + ", ".join(audit.compatibility.differing_fields))
    print("Pooling automático: NÃO")

    for run in audit.runs:
        dep = run.dependence
        qc = run.quote_coverage
        print()
        print(f"RUN {run.run_key}")
        print(
            f"status {run.status} | runtime {run.runtime_version} | "
            f"duração {run.duration_seconds if run.duration_seconds is not None else 'n/a'}s"
        )
        print(
            f"ações {run.full_run_action_count} | BUY {run.full_run_buy_count} | "
            f"SELL {run.full_run_sell_count} | wallets ativas {run.active_wallet_count} | "
            f"tokens {run.active_token_count}"
        )
        print(
            f"BUYs enrolled {run.enrolled_buy_count} | follow-up-only "
            f"{run.followup_only_buy_count} | clusters enrolled "
            f"{dep.wallet_token_cluster_count} | repetição {dep.repeated_wallet_token_buy_share_pct:.1f}%"
        )
        print(
            f"maior wallet {dep.largest_wallet_buy_share_pct:.1f}% | maior token "
            f"{dep.largest_token_buy_share_pct:.1f}% | maior cluster "
            f"{dep.largest_wallet_token_cluster_share_pct:.1f}%"
        )
        print(
            f"entry quotes {qc.successful_buy_probe_count}/{qc.expected_buy_probe_count} "
            f"sucesso ({qc.success_coverage_pct:.1f}%) | falhas {qc.failed_buy_probe_count} | "
            f"missing {qc.missing_buy_probe_count}"
        )
        if run.protocol_flags:
            print("PROTOCOL FLAGS: " + ", ".join(run.protocol_flags))
        for item in run.economics:
            print(
                f"  +{item.delay_seconds}s | closed {item.closed_count} | open {item.open_count} | "
                f"censored {item.censored_count} | mean {_pct(item.mean_net_return_pct)} | "
                f"median {_pct(item.median_net_return_pct)} | PF "
                f"{item.profit_factor if item.profit_factor is not None else 'n/a'}"
            )

    print()
    print("FLAGS: " + ", ".join(audit.interpretation_flags))
    print("Finality continua sendo gate separado; este relatório não inventa estado de rede ausente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
