import argparse
import asyncio
import time
from collections import Counter

from src.config import settings
from src.market_radar_bridge import process_pump_notification_for_radar
from src.pump_bonding_stream import iter_pump_log_notifications


MAX_SMOKE_SECONDS = 900


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded READ ONLY live smoke for Pump -> Market Radar -> Opportunity Episode."
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument(
        "--commitment",
        choices=("processed", "confirmed", "finalized"),
        default="confirmed",
    )
    return parser.parse_args()


async def run_smoke(*, run_key: str, duration_seconds: int, commitment: str) -> None:
    if duration_seconds <= 0 or duration_seconds > MAX_SMOKE_SECONDS:
        raise SystemExit(f"--duration-seconds must be between 1 and {MAX_SMOKE_SECONDS}")

    started = time.monotonic()
    notifications = 0
    decoded_trade_events = 0
    decoded_lifecycle_events = 0
    sol_eligible_trade_events = 0
    persisted_trades = 0
    duplicate_or_replayed_eligible = 0
    filtered_non_sol_prefix = 0
    evaluated_tokens: set[str] = set()
    hit_tokens: set[str] = set()
    episode_keys: set[str] = set()
    trigger_kinds: Counter[str] = Counter()
    directions: Counter[str] = Counter()

    print("Crypto Copy Trader — Market Radar Live Smoke")
    print("Mode: PAPER / RESEARCH / READ ONLY — no transaction signing or submission.")
    print(f"run_key={run_key} duration={duration_seconds}s commitment={commitment}")

    iterator = iter_pump_log_notifications(
        rpc_url=settings.rpc_url,
        commitment=commitment,
    ).__aiter__()

    while True:
        remaining = duration_seconds - (time.monotonic() - started)
        if remaining <= 0:
            break
        try:
            notification = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
        except asyncio.TimeoutError:
            break
        except StopAsyncIteration:
            break

        notifications += 1
        decoded_trade_events += len(notification.events)
        decoded_lifecycle_events += len(notification.lifecycle_events)
        eligible = sum(1 for event in notification.events if event.sol_amount > 0)
        filtered_non_sol_prefix += len(notification.events) - eligible
        sol_eligible_trade_events += eligible

        result = process_pump_notification_for_radar(
            notification,
            acquisition_run_key=run_key,
        )
        persisted_trades += result.newly_persisted_trades
        duplicate_or_replayed_eligible += max(0, eligible - result.newly_persisted_trades)
        evaluated_tokens.update(result.affected_tokens)

        for hit in result.hits:
            hit_tokens.add(hit.token_mint)
            episode_keys.add(hit.episode.episode_key)
            trigger_kinds[hit.trigger.trigger_kind] += 1
            directions[hit.trigger.direction] += 1
            f = hit.trigger.features
            print(
                f"[radar] token={hit.token_mint[:10]}… kind={hit.trigger.trigger_kind} "
                f"dir={hit.trigger.direction} fast={f.fast_event_count} "
                f"wallets={f.fast_unique_wallet_count} tx={f.fast_unique_transaction_count} "
                f"accel={f.activity_acceleration_ratio} episode={hit.episode.episode_key[-18:]}"
            )

    elapsed = time.monotonic() - started
    print("\nSUMMARY")
    print(
        f"elapsed={elapsed:.1f}s notifications={notifications} "
        f"decoded_trades={decoded_trade_events} lifecycle_events={decoded_lifecycle_events} "
        f"sol_eligible={sol_eligible_trade_events} persisted={persisted_trades}"
    )
    print(
        f"filtered_non_sol_prefix={filtered_non_sol_prefix} "
        f"duplicate_or_replayed_eligible={duplicate_or_replayed_eligible} "
        f"evaluated_tokens={len(evaluated_tokens)}"
    )
    print(
        f"radar_hits={sum(trigger_kinds.values())} unique_hit_tokens={len(hit_tokens)} "
        f"unique_episodes={len(episode_keys)} trigger_kinds={dict(trigger_kinds)} "
        f"directions={dict(directions)}"
    )
    print(
        "This smoke validates live acquisition and detector plumbing only. "
        "It does not measure edge, profitability or executable fills."
    )


def main() -> None:
    args = parse_args()
    asyncio.run(
        run_smoke(
            run_key=args.run_key.strip(),
            duration_seconds=args.duration_seconds,
            commitment=args.commitment,
        )
    )


if __name__ == "__main__":
    main()
