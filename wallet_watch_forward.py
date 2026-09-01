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
from src.wallet_forward_rpc import (
    VALID_WALLET_FORWARD_COMMITMENTS,
    WalletForwardSolanaClient,
)


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


def _rotated_poll_order(addresses: list[str], cycle_number: int) -> list[str]:
    """Rotate which wallet is polled first so sequential RPC latency is not permanently biased."""
    if cycle_number < 1:
        raise ValueError("cycle_number must be >= 1")
    if not addresses:
        return []
    offset = (cycle_number - 1) % len(addresses)
    return addresses[offset:] + addresses[:offset]


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
        "--rpc-commitment",
        choices=sorted(VALID_WALLET_FORWARD_COMMITMENTS),
        default="finalized",
        help=(
            "nível de confirmação RPC explícito. finalized preserva o comportamento histórico; "
            "confirmed reduz espera para experimentos de latência e exige auditoria de finality."
        ),
    )
    parser.add_argument(
        "--max-wallets",
        type=int,
        default=20,
        help="proteção contra carga acidental (padrão: 20 wallets)",
    )
    parser.add_argument("--run-key", help="run manifest para lineage direta das observações")
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
    client = WalletForwardSolanaClient(commitment=args.rpc_commitment)

    print("Crypto Copy Trader — Forward Wallet Watch v4")
    print("Modo: RESEARCH / READ ONLY — Solana RPC, sem ordens e sem Tracker Data API.")
    print(
        f"Wallets: {len(addresses)} | polling {args.interval_seconds}s | "
        f"duração {args.hours:.2f}h | RPC commitment {args.rpc_commitment}"
    )
    print(
        "Polling order: rotação por ciclo para reduzir vantagem sistemática da primeira wallet "
        "em um coletor RPC sequencial."
    )
    if args.rpc_commitment == "confirmed":
        print(
            "Commitment confirmed: observação chega antes de finalized. A run deve ser auditada "
            "depois para verificar se as assinaturas observadas chegaram à finalização."
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
            result = sync_wallet(address, client=client)
            print(
                f"[bootstrap] {address[:10]}… encontrados {result['found']} | "
                f"novos SQLite {result['inserted']} | falhas {result['failed']} | "
                f"endpoint {result['rpc_endpoint']}"
            )
        except (SolanaRPCError, ValueError) as exc:
            bootstrap_failures += 1
            print(f"[bootstrap] {address[:10]}… RPC falhou: {exc}", file=sys.stderr)
        known[address] = load_known_wallet_signatures(address)

    # Strict causal boundary independent from signature hydration. If an old transaction failed
    # to hydrate during bootstrap and becomes readable later, it remains historical rather than
    # being mislabeled as a live forward action.
    forward_started_at = int(time.time())
    started = time.monotonic()
    deadline = started + args.hours * 3_600
    cycles = sync_failures = recorded_actions = ignored_rows = prestart_ignored = 0
    print(f"Forward causal boundary (chain_time >=): {forward_started_at}")

    try:
        while time.monotonic() < deadline:
            cycle_started = time.monotonic()
            cycles += 1
            poll_order = _rotated_poll_order(addresses, cycles)
            for address in poll_order:
                previous = known[address]
                try:
                    result = sync_wallet(address, client=client)
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
                        not_before_chain_time=forward_started_at,
                        run_key=args.run_key,
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
                prestart_ignored += capture.prestart_new_transaction_count
                if capture.new_transaction_count or result["failed"]:
                    print(
                        f"[cycle {cycles}] {address[:10]}… novos tx "
                        f"{capture.new_transaction_count} | ações forward "
                        f"{capture.recorded_action_count} | ignorados "
                        f"{capture.ignored_new_transaction_count} | pré-início "
                        f"{capture.prestart_new_transaction_count} | RPC falhas {result['failed']}"
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
        f"linhas novas ignoradas: {ignored_rows} | pré-início bloqueadas: {prestart_ignored} | "
        f"falhas de sync/capture: {sync_failures} | falhas no bootstrap: {bootstrap_failures}"
    )
    print(
        "Estas observações podem alimentar Opportunity Intelligence porque preservam chain_time "
        "e o observed_at real do coletor. Elas ainda não são sinal de compra nem prova de edge."
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
