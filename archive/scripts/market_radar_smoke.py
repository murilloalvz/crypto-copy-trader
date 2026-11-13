import argparse
import asyncio
import hashlib
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


def _episode_display_id(episode_key: str) -> str:
    return hashlib.sha256(episode_key.encode("utf-8")).hexdigest()[:10]


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
    raw_trigger_kinds: Counter[str] = Counter()
    raw_directions: Counter[str] = Counter()
    opened_trigger_kinds: Counter[str] = Counter()
    opened_directions: Counter[str] = Counter()
    episode_token_counts: Counter[str] = Counter()
    continuation_hits = 0

    print("Crypto Copy Trader — Market Radar Live Smoke")
    print("Mode: PAPER / RESEARCH / READ ONLY — no transaction signing or submission.")
    print(f"run_key={run_key} duration={duration_seconds}s commitment={commitment}")
    print(
        "Console policy: only first sighting of each opportunity episode is printed. "
        "All qualifying raw radar triggers remain persisted."
    )

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
            raw_trigger_kinds[hit.trigger.trigger_kind] += 1
            raw_directions[hit.trigger.direction] += 1

            if hit.episode.episode_key in episode_keys:
                continuation_hits += 1
                continue

            episode_keys.add(hit.episode.episode_key)
            episode_token_counts[hit.token_mint] += 1
            opened_trigger_kinds[hit.trigger.trigger_kind] += 1
            opened_directions[hit.trigger.direction] += 1
            f = hit.trigger.features
            print(
                f"[episode-open] id={_episode_display_id(hit.episode.episode_key)} "
                f"token={hit.token_mint[:10]}… kind={hit.trigger.trigger_kind} "
                f"dir={hit.trigger.direction} fast={f.fast_event_count} "
                f"wallets={f.fast_unique_wallet_count} tx={f.fast_unique_transaction_count} "
                f"accel={f.activity_acceleration_ratio}"
            )

    elapsed = time.monotonic() - started
    raw_hits = sum(raw_trigger_kinds.values())
    repeated_episode_tokens = sum(max(0, count - 1) for count in episode_token_counts.values())
    continuation_share = (100.0 * continuation_hits / raw_hits) if raw_hits else 0.0

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
        f"raw_radar_hits={raw_hits} continuation_hits={continuation_hits} "
        f"continuation_share={continuation_share:.1f}% unique_hit_tokens={len(hit_tokens)}"
    )
    print(
        f"unique_episodes={len(episode_keys)} repeated_episode_tokens={repeated_episode_tokens} "
        f"opened_trigger_kinds={dict(opened_trigger_kinds)} "
        f"opened_directions={dict(opened_directions)}"
    )
    print(
        f"raw_trigger_kinds={dict(raw_trigger_kinds)} "
        f"raw_directions={dict(raw_directions)}"
    )
    print(
        "This smoke validates live acquisition and detector/episode plumbing only. "
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
