import argparse
import asyncio
import time

from src.config import settings
from src.pump_bonding_stream import iter_pump_log_notifications, persist_pump_notification


async def run_smoke(*, run_key: str, duration_seconds: int, commitment: str) -> None:
    if duration_seconds <= 0 or duration_seconds > 900:
        raise ValueError("duration_seconds must be between 1 and 900 for the smoke")

    started = time.time()
    notifications = 0
    decoded_events = 0
    persisted = 0
    unique_tokens: set[str] = set()
    unique_wallets: set[str] = set()

    print("Crypto Copy Trader — Pump Market Stream Smoke v1")
    print("Mode: PAPER / RESEARCH / READ ONLY — no transaction signing or sending.")
    print(f"Run key: {run_key}")
    print(f"Duration: {duration_seconds}s | commitment={commitment}")
    print("Source: native Solana logsSubscribe -> Pump TradeEvent -> market observation store")

    iterator = iter_pump_log_notifications(rpc_url=settings.rpc_url, commitment=commitment)
    try:
        while True:
            remaining = duration_seconds - (time.time() - started)
            if remaining <= 0:
                break
            try:
                notification = await asyncio.wait_for(anext(iterator), timeout=remaining)
            except asyncio.TimeoutError:
                break
            notifications += 1
            decoded_events += len(notification.events)
            for event in notification.events:
                unique_tokens.add(event.mint)
                unique_wallets.add(event.user)
            newly_persisted = persist_pump_notification(
                notification,
                acquisition_run_key=run_key,
            )
            persisted += newly_persisted
            print(
                f"[pump slot={notification.slot}] {notification.signature[:10]}… "
                f"events={len(notification.events)} persisted={newly_persisted}"
            )
    finally:
        await iterator.aclose()

    elapsed = time.time() - started
    print("\nSUMMARY")
    print(
        f"elapsed={elapsed:.1f}s notifications={notifications} decoded_events={decoded_events} "
        f"persisted={persisted} unique_tokens={len(unique_tokens)} unique_wallets={len(unique_wallets)}"
    )
    print("This smoke validates acquisition plumbing only. It does not measure edge or profitability.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded native Pump market-stream smoke test")
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument(
        "--commitment",
        choices=("confirmed", "finalized"),
        default="confirmed",
    )
    args = parser.parse_args()
    asyncio.run(
        run_smoke(
            run_key=args.run_key,
            duration_seconds=args.duration_seconds,
            commitment=args.commitment,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
