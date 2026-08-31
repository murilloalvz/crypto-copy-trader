import argparse
import sys
import time
from pathlib import Path

from src.database import add_wallet, initialize_database
from src.services import sync_wallet
from src.solana import SolanaRPCError
from src.wallet_forward_collector import (
    capture_new_wallet_actions,
    load_known_wallet_signatures,
)
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema


def _load_addresses(positional: list[str], file_path: str | None) -> list[str]:
    addresses = [item.strip() for item in positional if item.strip()]
    if file_path:
        path = Path(file_path)
        if not path.exists():
            raise ValueError(f"arquivo de wallets não encontrado: {path}")
        addresses.extend(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    return list(dict.fromkeys(addresses))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Observa wallets públicas via Solana RPC e persiste o instante em que novos swaps "
            "foram realmente vistos pelo coletor. RESEARCH/READ ONLY; sem Tracker Data API."
        )
    )
    parser.add_argument("addresses", nargs="*", help="wallets públicas Solana")
    parser.add_argument("--file", help="arquivo UTF-8 com uma wallet por linha")
    parser.add_argument("--hours", type=float, default=1.0, help="duração em horas (padrão: 1)")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=60,
        help="intervalo de polling por coorte (padrão: 60s)",
    )
    parser.add_argument(
        "--max-wallets",
        type=int,
        default=20,
        help="proteção contra carga acidental (padrão: 20 wallets)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 < args.hours <= 24:
        print("Erro: --hours precisa ficar entre >0 e 24.", file=sys.stderr)
        return 2
    if args.interval_seconds < 10:
        print("Erro: --interval-seconds precisa ser >= 10.", file=sys.stderr)
        return 2
    if not 1 <= args.max_wallets <= 100:
        print("Erro: --max-wallets precisa ficar entre 1 e 100.", file=sys.stderr)
        return 2

    try:
        addresses = _load_addresses(args.addresses, args.file)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    if not addresses:
        print("Erro: informe ao menos uma wallet ou use --file.", file=sys.stderr)
        return 2
    if len(addresses) > args.max_wallets:
        print(
            f"Erro: {len(addresses)} wallets excedem --max-wallets={args.max_wallets}.",
            file=sys.stderr,
        )
        return 2

    initialize_database()
    ensure_wallet_forward_observation_schema()
    for address in addresses:
        add_wallet(address, "Forward Wallet Watch")

    print("Crypto Copy Trader — Forward Wallet Watch v1")
    print("Modo: RESEARCH / READ ONLY — Solana RPC, sem ordens e sem Tracker Data API.")
    print(
        f"Wallets: {len(addresses)} | polling {args.interval_seconds}s | "
        f"duração {args.hours:.2f}h"
    )
    print()
    print("BOOTSTRAP")
    print(
        "O primeiro sync estabelece a linha de base e NÃO vira confirmação forward. "
        "Somente transações novas após essa linha de base recebem observed_at."
    )

    known: dict[str, set[str]] = {}
    bootstrap_failures = 0
    for address in addresses:
        try:
            result = sync_wallet(address)
            print(
                f"[bootstrap] {address[:10]}… encontrados {result['found']} | "
                f"novos SQLite {result['inserted']} | falhas {result['failed']} | "
                f"endpoint {result['rpc_endpoint']}"
            )
        except (SolanaRPCError, ValueError) as exc:
            bootstrap_failures += 1
            print(f"[bootstrap] {address[:10]}… RPC falhou: {exc}", file=sys.stderr)
        known[address] = load_known_wallet_signatures(address)

    started = time.monotonic()
    deadline = started + args.hours * 3_600
    cycles = sync_failures = recorded_actions = ignored_rows = 0

    try:
        while time.monotonic() < deadline:
            cycle_started = time.monotonic()
            cycles += 1
            for address in addresses:
                previous = known[address]
                try:
                    result = sync_wallet(address)
                except (SolanaRPCError, ValueError) as exc:
                    sync_failures += 1
                    print(f"[rpc] {address[:10]}… falhou: {exc}", file=sys.stderr)
                    continue

                observed_at = int(time.time())
                try:
                    capture = capture_new_wallet_actions(
                        address,
                        known_signatures=previous,
                        observed_at=observed_at,
                    )
                except ValueError as exc:
                    sync_failures += 1
                    print(
                        f"[capture] {address[:10]}… observação rejeitada: {exc}",
                        file=sys.stderr,
                    )
                    known[address] = load_known_wallet_signatures(address)
                    continue

                known[address] = set(capture.known_signatures)
                recorded_actions += capture.recorded_action_count
                ignored_rows += capture.ignored_new_transaction_count
                if capture.new_transaction_count or result["failed"]:
                    print(
                        f"[cycle {cycles}] {address[:10]}… novos tx "
                        f"{capture.new_transaction_count} | ações forward "
                        f"{capture.recorded_action_count} | ignorados "
                        f"{capture.ignored_new_transaction_count} | RPC falhas {result['failed']}"
                    )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            elapsed = time.monotonic() - cycle_started
            time.sleep(min(remaining, max(0.0, args.interval_seconds - elapsed)))
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário; observações já persistidas permanecem no SQLite.")
        return_code = 130
    else:
        return_code = 0

    print()
    print("RESUMO")
    print(
        f"Ciclos: {cycles} | ações forward persistidas: {recorded_actions} | "
        f"linhas novas ignoradas: {ignored_rows} | falhas de sync/capture: {sync_failures} | "
        f"falhas no bootstrap: {bootstrap_failures}"
    )
    print(
        "Estas observações podem alimentar Opportunity Intelligence porque preservam chain_time "
        "e o observed_at real do coletor. Elas ainda não são sinal de compra nem prova de edge."
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
