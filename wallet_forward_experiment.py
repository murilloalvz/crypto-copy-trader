import argparse
import subprocess
import sys
import time
import uuid
from pathlib import Path

from src.config import settings
from src.database import initialize_database
from src.wallet_forward_runs import create_wallet_forward_run, finish_wallet_forward_run
from src.wallet_quote_watch import latest_forward_observation_id


DEFAULT_QUOTE_DELAYS = (0, 15, 30, 60, 120)


def _load_cohort(path: Path) -> list[str]:
    if not path.exists():
        raise ValueError(f"arquivo de wallets não encontrado: {path}")
    addresses = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    addresses = list(dict.fromkeys(addresses))
    if not addresses:
        raise ValueError("arquivo da coorte está vazio")
    return addresses


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Orquestra o Forward Wallet Watch e, opcionalmente, o Wallet Quote Watch em processo "
            "separado. RESEARCH/READ ONLY; nenhum processo assina ou envia transações."
        )
    )
    parser.add_argument("--file", required=True, help="arquivo da coorte de wallets")
    parser.add_argument("--hours", type=float, default=6.0)
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument(
        "--with-jupiter-quotes",
        action="store_true",
        help="captura também snapshots de rota Jupiter para novas compras forward",
    )
    parser.add_argument(
        "--quote-delays-seconds",
        type=int,
        nargs="+",
        default=list(DEFAULT_QUOTE_DELAYS),
        help="delays dos snapshots Jupiter após detecção (padrão: 0 15 30 60 120)",
    )
    parser.add_argument(
        "--taker",
        help=(
            "chave pública opcional para Jupiter montar transação candidata. "
            "Nenhuma chave privada é lida ou usada."
        ),
    )
    parser.add_argument(
        "--copy-size-usd",
        type=float,
        default=settings.copy_size_usd,
    )
    return parser


def _terminate(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _finish_run(run_key: str, *, status: str) -> None:
    finish_wallet_forward_run(
        run_key,
        status=status,
        ended_at=int(time.time()),
        end_observation_id=latest_forward_observation_id(),
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cohort_path = Path(args.file)
    try:
        addresses = _load_cohort(cohort_path)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    if not 0 < args.hours <= 24:
        print("Erro: --hours precisa ficar entre >0 e 24.", file=sys.stderr)
        return 2
    if args.interval_seconds < 10:
        print("Erro: --interval-seconds precisa ser >= 10.", file=sys.stderr)
        return 2
    quote_delays = tuple(dict.fromkeys(args.quote_delays_seconds))
    if not quote_delays or any(delay < 0 for delay in quote_delays):
        print("Erro: --quote-delays-seconds precisa conter valores >= 0.", file=sys.stderr)
        return 2
    if args.copy_size_usd <= 0:
        print("Erro: --copy-size-usd precisa ser > 0.", file=sys.stderr)
        return 2
    if args.with_jupiter_quotes and not settings.jupiter_api_key:
        print(
            "Erro: --with-jupiter-quotes requer JUPITER_API_KEY no .env.",
            file=sys.stderr,
        )
        return 2

    initialize_database()
    baseline_id = latest_forward_observation_id()
    started_at = int(time.time())
    run_key = f"wallet-forward-{started_at}-{uuid.uuid4().hex[:8]}"
    quote_mode = (
        "assembled_candidate" if args.with_jupiter_quotes and args.taker else
        "proxy" if args.with_jupiter_quotes else
        "none"
    )
    create_wallet_forward_run(
        run_key=run_key,
        started_at=started_at,
        baseline_observation_id=baseline_id,
        cohort=addresses,
        interval_seconds=args.interval_seconds,
        quote_delays_seconds=quote_delays if args.with_jupiter_quotes else (),
        with_jupiter_quotes=args.with_jupiter_quotes,
        copy_size_usd=args.copy_size_usd,
        quote_mode=quote_mode,
    )

    print("Crypto Copy Trader — Wallet Forward Experiment")
    print("Modo: RESEARCH / READ ONLY — nenhum processo assina ou envia transações.")
    print(
        f"Run key: {run_key} | baseline observation id={baseline_id} | "
        f"wallets={len(addresses)} | duração={args.hours:.2f}h"
    )
    print(
        "Run manifest: configuração e limites da coleta foram congelados no SQLite para "
        "o checkpoint não misturar observações de execuções diferentes."
    )

    python = sys.executable
    quote_process: subprocess.Popen | None = None
    wallet_process: subprocess.Popen | None = None
    final_status = "ABORTED"
    return_code = 1

    try:
        if args.with_jupiter_quotes:
            quote_command = [
                python,
                "wallet_quote_watch.py",
                "--file",
                str(cohort_path),
                "--hours",
                str(args.hours),
                "--after-id",
                str(baseline_id),
                "--copy-size-usd",
                str(args.copy_size_usd),
                "--delays-seconds",
                *[str(delay) for delay in quote_delays],
            ]
            if args.taker:
                quote_command.extend(["--taker", args.taker])
            print("Iniciando Wallet Quote Watch com o mesmo baseline congelado da run.")
            quote_process = subprocess.Popen(quote_command)
            time.sleep(1.0)
            if quote_process.poll() is not None:
                print(
                    f"Erro: Wallet Quote Watch encerrou cedo com código {quote_process.returncode}.",
                    file=sys.stderr,
                )
                return_code = int(quote_process.returncode or 1)
                return return_code

        wallet_command = [
            python,
            "wallet_watch_forward.py",
            "--file",
            str(cohort_path),
            "--hours",
            str(args.hours),
            "--interval-seconds",
            str(args.interval_seconds),
        ]
        print("Iniciando Forward Wallet Watch.")
        wallet_process = subprocess.Popen(wallet_command)

        while wallet_process.poll() is None:
            if (
                quote_process is not None
                and quote_process.poll() is not None
                and quote_process.returncode != 0
            ):
                print(
                    f"Wallet Quote Watch falhou com código {quote_process.returncode}; "
                    "encerrando watcher RPC para preservar alinhamento da run.",
                    file=sys.stderr,
                )
                _terminate(wallet_process)
                return_code = int(quote_process.returncode or 1)
                return return_code
            time.sleep(0.5)

        if wallet_process.returncode != 0:
            print(
                f"Forward Wallet Watch encerrou com código {wallet_process.returncode}; "
                "encerrando coletor de quotes para não criar uma coorte desalinhada.",
                file=sys.stderr,
            )
            _terminate(quote_process)
            return_code = int(wallet_process.returncode or 1)
            return return_code

        if quote_process is not None:
            print(
                "Forward Watch terminou. Aguardando o Quote Watch drenar snapshots agendados "
                f"até +{max(quote_delays)}s."
            )
            quote_return = quote_process.wait()
            if quote_return != 0:
                print(
                    f"Wallet Quote Watch encerrou com código {quote_return}.",
                    file=sys.stderr,
                )
                return_code = int(quote_return or 1)
                return return_code

        final_status = "COMPLETED"
        return_code = 0
        return 0
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário; a run será marcada como ABORTED.")
        _terminate(wallet_process)
        _terminate(quote_process)
        return_code = 130
        return 130
    finally:
        _terminate(wallet_process)
        _terminate(quote_process)
        try:
            _finish_run(run_key, status=final_status)
            print(f"Run {run_key} finalizada com status {final_status}.")
        except Exception as exc:
            print(
                f"ALERTA: não foi possível finalizar o manifest da run {run_key}: {exc}",
                file=sys.stderr,
            )
            if return_code == 0:
                print(
                    "A coleta terminou, mas o checkpoint deve ser tratado como BLOQUEADO "
                    "até o manifest ser reconciliado.",
                    file=sys.stderr,
                )


if __name__ == "__main__":
    raise SystemExit(main())
