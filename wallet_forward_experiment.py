import argparse
import subprocess
import sys
import time
from pathlib import Path

from src.config import settings


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cohort = Path(args.file)
    if not cohort.exists():
        print(f"Erro: arquivo de wallets não encontrado: {cohort}", file=sys.stderr)
        return 2
    if not 0 < args.hours <= 24:
        print("Erro: --hours precisa ficar entre >0 e 24.", file=sys.stderr)
        return 2
    if args.interval_seconds < 10:
        print("Erro: --interval-seconds precisa ser >= 10.", file=sys.stderr)
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

    python = sys.executable
    quote_process: subprocess.Popen | None = None
    if args.with_jupiter_quotes:
        quote_command = [
            python,
            "wallet_quote_watch.py",
            "--file",
            str(cohort),
            "--hours",
            str(args.hours),
            "--copy-size-usd",
            str(args.copy_size_usd),
        ]
        if args.taker:
            quote_command.extend(["--taker", args.taker])
        print("Iniciando Wallet Quote Watch antes do watcher RPC para congelar o baseline local.")
        quote_process = subprocess.Popen(quote_command)
        time.sleep(1.0)
        if quote_process.poll() is not None:
            print(
                f"Erro: Wallet Quote Watch encerrou cedo com código {quote_process.returncode}.",
                file=sys.stderr,
            )
            return int(quote_process.returncode or 1)

    wallet_command = [
        python,
        "wallet_watch_forward.py",
        "--file",
        str(cohort),
        "--hours",
        str(args.hours),
        "--interval-seconds",
        str(args.interval_seconds),
    ]

    print("Iniciando Forward Wallet Watch.")
    try:
        wallet_result = subprocess.run(wallet_command)
    except KeyboardInterrupt:
        _terminate(quote_process)
        return 130

    if wallet_result.returncode != 0:
        print(
            f"Forward Wallet Watch encerrou com código {wallet_result.returncode}; "
            "encerrando coletor de quotes para não criar uma coorte desalinhada.",
            file=sys.stderr,
        )
        _terminate(quote_process)
        return wallet_result.returncode

    if quote_process is not None:
        print(
            "Forward Watch terminou. Aguardando o Quote Watch drenar snapshots agendados "
            "até +120s."
        )
        try:
            return quote_process.wait()
        except KeyboardInterrupt:
            _terminate(quote_process)
            return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
