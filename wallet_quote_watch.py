import argparse
import sys
import time
from pathlib import Path

from src.assets import USDC_MINT
from src.causal_quote_store import load_causal_quotes, record_causal_quote
from src.config import settings
from src.database import initialize_database
from src.jupiter_swap_v2 import (
    JupiterOrderError,
    JupiterSwapV2Client,
    jupiter_order_to_causal_quote,
)
from src.solana import SolanaClient, SolanaRPCError
from src.token_metadata import TokenDecimalsCache
from src.wallet_quote_watch import (
    latest_forward_observation_id,
    load_forward_events_after,
    quote_attempt_exists,
    record_quote_attempt,
    schedule_buy_quotes,
    schedule_sell_quote,
)
from src.wallet_sell_quote_lineage import load_same_run_successful_buy_quote_lineage


USDC_DECIMALS = 6


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


def _poll_new_events(
    cursor_id: int,
    *,
    addresses: list[str],
):
    """Freeze MAX(id), then read exactly that interval before advancing the cursor."""
    newest_id = latest_forward_observation_id()
    if newest_id <= cursor_id:
        return cursor_id, []
    events = load_forward_events_after(
        cursor_id,
        wallet_addresses=addresses or None,
        through_id=newest_id,
    )
    return newest_id, events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Observa novas ações já persistidas pelo Forward Wallet Watch e captura snapshots "
            "causais de rota via Jupiter Swap V2. RESEARCH/READ ONLY: nunca assina nem executa."
        )
    )
    parser.add_argument("addresses", nargs="*", help="wallets da coorte; vazio = todas")
    parser.add_argument("--file", help="arquivo UTF-8 com uma wallet por linha")
    parser.add_argument("--hours", type=float, default=1.0)
    parser.add_argument(
        "--after-id",
        type=int,
        help=(
            "baseline explícito de wallet_forward_observations. Quando omitido, congela o "
            "último id existente no startup."
        ),
    )
    parser.add_argument(
        "--delays-seconds",
        type=int,
        nargs="+",
        default=[0, 15, 30, 60, 120],
        help="snapshots após observed_at da wallet (padrão: 0 15 30 60 120)",
    )
    parser.add_argument(
        "--copy-size-usd",
        type=float,
        default=settings.copy_size_usd,
        help="notional de compra em USDC usado apenas para cotação",
    )
    parser.add_argument(
        "--taker",
        help=(
            "chave pública opcional usada apenas para Jupiter montar a transação. "
            "Nenhuma chave privada é usada e nenhuma transação é enviada."
        ),
    )
    parser.add_argument(
        "--db-poll-seconds",
        type=float,
        default=0.5,
        help="polling do SQLite local por novas ações forward (padrão: 0.5s)",
    )
    parser.add_argument(
        "--min-request-gap-seconds",
        type=float,
        default=1.1,
        help="proteção conservadora para o limite Free do Jupiter (padrão: 1.1s)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 < args.hours <= 24.1:
        print("Erro: --hours precisa ficar entre >0 e 24.1.", file=sys.stderr)
        return 2
    if args.after_id is not None and args.after_id < 0:
        print("Erro: --after-id precisa ser >= 0.", file=sys.stderr)
        return 2
    delays = tuple(dict.fromkeys(args.delays_seconds))
    if not delays or any(delay < 0 for delay in delays):
        print("Erro: delays precisam ser >= 0.", file=sys.stderr)
        return 2
    if args.copy_size_usd <= 0:
        print("Erro: --copy-size-usd precisa ser > 0.", file=sys.stderr)
        return 2
    if args.db_poll_seconds <= 0 or args.min_request_gap_seconds < 0:
        print("Erro: intervalos precisam ser positivos.", file=sys.stderr)
        return 2
    if not settings.jupiter_api_key:
        print(
            "Erro: JUPITER_API_KEY ausente. Configure a chave no .env antes da coleta de quotes.",
            file=sys.stderr,
        )
        return 2

    try:
        addresses = _load_addresses(args.addresses, args.file)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    amount_raw = int(round(args.copy_size_usd * (10**USDC_DECIMALS)))
    if amount_raw <= 0:
        print("Erro: notional virou zero em unidades de USDC.", file=sys.stderr)
        return 2

    initialize_database()
    jupiter = JupiterSwapV2Client(api_key=settings.jupiter_api_key)
    decimals = TokenDecimalsCache(SolanaClient())

    cursor_id = (
        args.after_id if args.after_id is not None else latest_forward_observation_id()
    )
    pending = []
    started = time.monotonic()
    intake_deadline = started + args.hours * 3_600
    drain_deadline = intake_deadline + max(delays) + 60
    last_request_mono: float | None = None
    discovered_events = discovered_buys = attempts = successes = failures = duplicates = 0
    intake_closed = False

    print("Crypto Copy Trader — Wallet Quote Watch v2")
    print("Modo: RESEARCH / READ ONLY — Jupiter GET /order; sem assinatura e sem /execute.")
    print(
        f"Baseline wallet_forward_observations id={cursor_id} | duração {args.hours:.3f}h | "
        f"delays {list(delays)} | notional USDC ${args.copy_size_usd:.2f} | "
        f"wallets {'todas' if not addresses else len(addresses)}"
    )
    print(
        "Taker: "
        + (
            "configurado — Jupiter pode montar transação candidata, ainda sem execução"
            if args.taker
            else "não configurado — snapshots serão quote-only e NÃO executáveis"
        )
    )

    def ingest_once(*, final_sweep: bool = False) -> None:
        nonlocal cursor_id, discovered_events, discovered_buys, pending
        cursor_id, events = _poll_new_events(cursor_id, addresses=addresses)
        if not events:
            if final_sweep:
                print(f"[final intake] cursor fechado em observation id={cursor_id}; sem evento novo.")
            return
        discovered_events += len(events)
        discovered_buys += sum(event.side == "buy" for event in events)
        pending.extend(
            schedule_buy_quotes(
                [event for event in events if event.side == "buy"],
                delays_seconds=delays,
            )
        )
        for event in (item for item in events if item.side == "sell"):
            prior = load_same_run_successful_buy_quote_lineage(event.observation_key)
            for row in prior:
                loaded = load_causal_quotes(quote_keys=[row.quote_key])
                if loaded and loaded[0].output_amount_raw:
                    pending.append(
                        schedule_sell_quote(
                            event,
                            input_amount_raw=int(loaded[0].output_amount_raw),
                            entry_event_key=row.source_event_key,
                            entry_delay_seconds=max(
                                0,
                                row.target_at - row.entry_observed_at,
                            ),
                        )
                    )
        pending.sort(key=lambda item: (item.target_at, item.event_id, item.delay_seconds))
        prefix = "final wallet event" if final_sweep else "wallet event"
        for event in events:
            print(
                f"[{prefix} {event.side}] {event.wallet_address[:10]}… "
                f"token {event.token_mint[:10]}… observed_at={event.observed_at}"
            )
        if final_sweep:
            print(
                f"[final intake] {len(events)} evento(s) adicionados; cursor fechado em id={cursor_id}."
            )

    try:
        while time.monotonic() < drain_deadline:
            now_mono = time.monotonic()
            if now_mono < intake_deadline:
                ingest_once()
            elif not intake_closed:
                # One explicit bounded sweep closes the intake so rows committed near the
                # deadline are not lost merely because quote processing occupied the loop.
                ingest_once(final_sweep=True)
                intake_closed = True

            if not pending and intake_closed:
                break

            now_epoch = int(time.time())
            if pending and pending[0].target_at <= now_epoch:
                probe = pending.pop(0)
                if quote_attempt_exists(probe.attempt_key):
                    duplicates += 1
                    continue

                if last_request_mono is not None:
                    wait = args.min_request_gap_seconds - (
                        time.monotonic() - last_request_mono
                    )
                    if wait > 0:
                        time.sleep(wait)

                requested_at = int(time.time())
                attempts += 1
                try:
                    token_decimals = decimals.get(probe.token_mint)
                    is_sell = probe.side == "sell"
                    order = jupiter.order(
                        input_mint=probe.token_mint if is_sell else USDC_MINT,
                        output_mint=USDC_MINT if is_sell else probe.token_mint,
                        amount_raw=probe.amount_raw if is_sell else amount_raw,
                        taker=args.taker,
                    )
                    last_request_mono = time.monotonic()
                    quote = jupiter_order_to_causal_quote(
                        order,
                        token_mint=probe.token_mint,
                        side=probe.side,
                        token_decimals=token_decimals,
                    )
                    inserted = record_causal_quote(quote, quote_key=probe.quote_key)
                    completed_at = int(time.time())
                    record_quote_attempt(
                        probe,
                        requested_at=requested_at,
                        completed_at=completed_at,
                        status="success",
                        quote_key=probe.quote_key,
                    )
                    successes += 1
                    print(
                        f"[quote +{probe.delay_seconds}s] {probe.token_mint[:10]}… "
                        f"price=${quote.price_usd:.8g} | router={order.router or 'unknown'} | "
                        f"assembled_tx={'yes' if quote.executable else 'no'} | "
                        f"target_lag={completed_at - probe.target_at}s | "
                        f"persisted={'yes' if inserted else 'duplicate'}"
                    )
                except (JupiterOrderError, SolanaRPCError, ValueError) as exc:
                    last_request_mono = time.monotonic()
                    completed_at = int(time.time())
                    record_quote_attempt(
                        probe,
                        requested_at=requested_at,
                        completed_at=completed_at,
                        status="error",
                        error=exc,
                    )
                    failures += 1
                    print(
                        f"[quote +{probe.delay_seconds}s] {probe.token_mint[:10]}… falhou: {exc}",
                        file=sys.stderr,
                    )
                continue

            if pending:
                until_due = max(0.0, pending[0].target_at - time.time())
                sleep_for = min(args.db_poll_seconds, until_due or args.db_poll_seconds)
            else:
                sleep_for = args.db_poll_seconds
            time.sleep(max(0.05, sleep_for))
    except KeyboardInterrupt:
        print("\nInterrompido; quotes e tentativas já persistidos permanecem no SQLite.")
        return_code = 130
    else:
        return_code = 0

    print()
    print("RESUMO")
    print(
        f"eventos forward novos: {discovered_events} | compras forward novas: {discovered_buys} | "
        f"probes tentados: {attempts} | sucesso: {successes} | falhas: {failures} | "
        f"duplicados ignorados: {duplicates} | pendentes não executados: {len(pending)} | "
        f"final cursor id={cursor_id}"
    )
    if pending:
        print(
            "ATENÇÃO: o drain deadline terminou com probes ainda pendentes; o checkpoint deve "
            "comparar tentativas reais contra BUYs×delays esperados e manter essa missingness visível.",
            file=sys.stderr,
        )
    print(
        "Quote-only sem taker permanece proxy. Mesmo assembled_tx=yes é só uma transação "
        "candidata montada pelo provider; não prova landing nem fill real."
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
