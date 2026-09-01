import json
from dataclasses import dataclass

from src.assets import STABLECOIN_MINTS
from src.database import rows
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_observations import record_wallet_forward_observation
from src.solana import parse_wallet_transaction


@dataclass(frozen=True)
class ForwardWalletCaptureSummary:
    address: str
    new_transaction_count: int
    recorded_action_count: int
    ignored_new_transaction_count: int
    prestart_new_transaction_count: int
    known_signatures: frozenset[str]


def load_known_wallet_signatures(address: str) -> set[str]:
    return {
        str(item["signature"])
        for item in rows(
            "SELECT signature FROM transactions WHERE wallet_address=?",
            (address,),
        )
    }


def capture_new_wallet_actions(
    address: str,
    *,
    known_signatures: set[str] | frozenset[str],
    observed_at: int,
    not_before_chain_time: int | None = None,
    run_key: str | None = None,
) -> ForwardWalletCaptureSummary:
    """Persist newly observed swaps while keeping historical backfill out of forward data.

    ``known_signatures`` remains the primary bootstrap boundary. ``not_before_chain_time`` is a
    second causal guard: if bootstrap/RPC transaction hydration was incomplete, a transaction
    whose chain timestamp predates the forward collection boundary is never relabeled as a live
    action merely because its details became readable later.
    """
    if observed_at < 0:
        raise ValueError("observed_at must be non-negative")
    if not_before_chain_time is not None and not_before_chain_time < 0:
        raise ValueError("not_before_chain_time must be non-negative")
    if not_before_chain_time is not None and not_before_chain_time > observed_at:
        raise ValueError("not_before_chain_time cannot be after observed_at")

    txs = rows(
        """SELECT signature, block_time, status, kind, dex, token_mint, token_change, raw_json
        FROM transactions WHERE wallet_address=? ORDER BY block_time, signature""",
        (address,),
    )
    all_signatures = {str(item["signature"]) for item in txs}
    new_rows = [item for item in txs if str(item["signature"]) not in known_signatures]

    recorded = ignored = prestart = 0
    for item in new_rows:
        token_mint = item.get("token_mint")
        token_change = item.get("token_change")
        block_time = item.get("block_time")
        if (
            item.get("status") != "success"
            or item.get("kind") != "swap"
            or not item.get("dex")
            or not token_mint
            or token_mint in STABLECOIN_MINTS
            or token_change is None
            or float(token_change) == 0
            or block_time is None
        ):
            ignored += 1
            continue

        chain_time = int(block_time)
        if not_before_chain_time is not None and chain_time < not_before_chain_time:
            # Keep it in known_signatures for later cycles, but never publish it as forward.
            ignored += 1
            prestart += 1
            continue

        side = "buy" if float(token_change) > 0 else "sell"
        signature = str(item["signature"])
        raw_fields = {}
        if item.get("raw_json"):
            try:
                raw_fields = parse_wallet_transaction(address, signature, json.loads(item["raw_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                raw_fields = {}
        observation = WalletActionObservation(
            address=address,
            token_mint=str(token_mint),
            side=side,
            chain_time=chain_time,
            observed_at=observed_at,
        )
        inserted = record_wallet_forward_observation(
            observation,
            observation_key=f"{address}:{signature}:{token_mint}:{side}",
            signature=signature,
            dex=str(item["dex"]),
            run_key=run_key,
            token_delta_raw=raw_fields.get("token_delta_raw"),
            token_decimals=raw_fields.get("token_decimals"),
            token_balance_before_raw=raw_fields.get("token_balance_before_raw"),
            token_balance_after_raw=raw_fields.get("token_balance_after_raw"),
            token_quantity_flags=raw_fields.get("token_quantity_flags"),
        )
        if inserted:
            recorded += 1

    return ForwardWalletCaptureSummary(
        address=address,
        new_transaction_count=len(new_rows),
        recorded_action_count=recorded,
        ignored_new_transaction_count=ignored,
        prestart_new_transaction_count=prestart,
        known_signatures=frozenset(all_signatures),
    )
