import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone

from src.database import initialize_database
from src.wallet_forward_run_compare import compare_wallet_forward_run_regimes
from src.wallet_forward_runs import (
    get_wallet_forward_run,
    list_wallet_forward_runs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compara manifests de Wallet Forward Runs sem misturar suas observações. "
            "Mostra se pertencem ao mesmo regime técnico."
        )
    )
    parser.add_argument(
        "--run-key",
        action="append",
        dest="run_keys",
        help="run específica; pode repetir. Sem este argumento usa as COMPLETED mais recentes.",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    return parser


def _iso(epoch: int | None) -> str:
    if epoch is None:
        return "n/a"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.limit <= 50:
        print("Erro: --limit precisa ficar entre 1 e 50.")
        return 2

    initialize_database()
    if args.run_keys:
        runs = []
        for key in args.run_keys:
            run = get_wallet_forward_run(key)
            if run is None:
                print(f"Erro: run não encontrada: {key}")
                return 2
            runs.append(run)
    else:
        runs = list(list_wallet_forward_runs(status="COMPLETED", limit=args.limit))

    compatibility = compare_wallet_forward_run_regimes(runs)
    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "compatibility": asdict(compatibility),
                    "runs": [asdict(item) for item in runs],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Wallet Forward Run Compare v1")
    print("Modo: RESEARCH / READ ONLY — manifests separados; nenhuma amostra é pooled.")
    print(f"Runs: {len(runs)} | COMPATIBILITY: {compatibility.label}")
    if compatibility.differing_fields:
        print("Campos de regime diferentes: " + ", ".join(compatibility.differing_fields))
    print("Pooling automático: NÃO")

    for run in runs:
        duration = (
            run.ended_at - run.started_at
            if run.ended_at is not None
            else None
        )
        print()
        print(f"- {run.run_key}")
        print(
            f"  status {run.status} | start {_iso(run.started_at)} | "
            f"duration {duration if duration is not None else 'n/a'}s"
        )
        print(
            f"  runtime {run.runtime_version} | wallets {len(run.cohort)} | "
            f"polling {run.interval_seconds}s"
        )
        print(
            f"  Jupiter {run.with_jupiter_quotes} | mode {run.quote_mode} | "
            f"delays {list(run.quote_delays_seconds)} | notional ${run.copy_size_usd:.2f} | "
            f"intake grace {run.quote_intake_grace_seconds}s"
        )

    print()
    print("INTERPRETAÇÃO")
    print("- SAME_TECHNICAL_REGIME ainda não autoriza juntar dados automaticamente.")
    print("- MIXED_TECHNICAL_REGIME significa comparar como coortes/regimes separados.")
    print("- Runtime v1 e v2 nunca devem ser silenciosamente fundidos como se tivessem a mesma causalidade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
