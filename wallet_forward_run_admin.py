import argparse
import time

from src.database import initialize_database
from src.wallet_forward_runs import (
    finish_wallet_forward_run,
    get_wallet_forward_run,
    list_wallet_forward_runs,
)
from src.wallet_quote_watch import latest_forward_observation_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Administração explícita de manifests Wallet Forward. Use somente para auditar ou "
            "reconciliar uma run ACTIVE órfã depois de confirmar que os processos pararam."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list-active", help="lista manifests ACTIVE; não modifica nada")
    list_parser.add_argument("--limit", type=int, default=20)

    abort_parser = sub.add_parser(
        "abort-stale",
        help="marca uma run ACTIVE órfã como ABORTED com confirmação forte",
    )
    abort_parser.add_argument("--run-key", required=True)
    abort_parser.add_argument(
        "--confirm-run-key",
        required=True,
        help="repita exatamente a run-key para evitar abort acidental",
    )
    abort_parser.add_argument(
        "--confirm-process-stopped",
        action="store_true",
        help="confirma que wallet/quote watcher dessa run não estão mais executando",
    )
    return parser


def _list_active(limit: int) -> int:
    if not 1 <= limit <= 100:
        print("Erro: --limit precisa ficar entre 1 e 100.")
        return 2
    active = list_wallet_forward_runs(status="ACTIVE", limit=limit)
    print("Crypto Copy Trader — Active Wallet Forward Runs")
    print("Modo: manifest audit; nenhuma coleta é iniciada ou encerrada.")
    if not active:
        print("Nenhuma run ACTIVE.")
        return 0
    for run in active:
        print(
            f"- {run.run_key} | runtime {run.runtime_version} | started_at={run.started_at} | "
            f"baseline={run.baseline_observation_id} | wallets={len(run.cohort)}"
        )
    return 0


def _abort_stale(run_key: str, confirm_run_key: str, confirm_process_stopped: bool) -> int:
    if run_key != confirm_run_key:
        print("Erro: --confirm-run-key não é idêntica à --run-key.")
        return 2
    if not confirm_process_stopped:
        print(
            "Erro: abort bloqueado. Confirme primeiro que os processos dessa run pararam e "
            "então use --confirm-process-stopped."
        )
        return 2

    run = get_wallet_forward_run(run_key)
    if run is None:
        print(f"Erro: run não encontrada: {run_key}")
        return 2
    if run.status != "ACTIVE":
        print(
            f"Erro: run {run_key} já está {run.status}; manifests finalizados são imutáveis."
        )
        return 2

    end_id = latest_forward_observation_id()
    if end_id < run.baseline_observation_id:
        print(
            "Erro: latest observation id está abaixo do baseline da run; não reconciliar "
            "automaticamente. Audite o banco primeiro."
        )
        return 2

    finished = finish_wallet_forward_run(
        run_key,
        status="ABORTED",
        ended_at=max(int(time.time()), run.started_at),
        end_observation_id=end_id,
    )
    print("Crypto Copy Trader — Stale Wallet Forward Run Reconciled")
    print(
        f"Run {finished.run_key} -> ABORTED | end observation id={finished.end_observation_id}."
    )
    print(
        "Os dados existentes não foram apagados. ABORTED preserva a evidência, mas não deve ser "
        "tratado como uma coleta COMPLETED."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    initialize_database()
    if args.command == "list-active":
        return _list_active(args.limit)
    if args.command == "abort-stale":
        return _abort_stale(
            args.run_key,
            args.confirm_run_key,
            args.confirm_process_stopped,
        )
    raise RuntimeError("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
