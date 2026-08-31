from dataclasses import dataclass

from src.assets import STABLECOIN_MINTS
from src.database import rows
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_observations import record_wallet_forward_observation


@dataclass(frozen=True)
class ForwardWalletCaptureSummary:
    address: str
    new_transaction_count: int
    recorded_action_count: int
    ignored_new_transaction_count: int
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
) -> ForwardWalletCaptureSummary:
    """Persist swaps that appeared in SQLite after the caller's previous signature snapshot.

    The caller is responsible for taking a bootstrap snapshot before forward collection starts.
    That bootstrap prevents historical RPC backfill from being mislabeled as a live action.
    """
    if observed_at < 0:
        raise ValueError("observed_at must be non-negative")

    txs = rows(
        """SELECT signature, block_time, status, kind, dex, token_mint, token_change
        FROM transactions WHERE wallet_address=? ORDER BY block_time, signature""",
        (address,),
    )
    all_signatures = {str(item["signature"]) for item in txs}
    new_rows = [item for item in txs if str(item["signature"]) not in known_signatures]

    recorded = ignored = 0
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

        side = "buy" if float(token_change) > 0 else "sell"
        signature = str(item["signature"])
        observation = WalletActionObservation(
            address=address,
            token_mint=str(token_mint),
            side=side,
            chain_time=int(block_time),
            observed_at=observed_at,
        )
        inserted = record_wallet_forward_observation(
            observation,
            observation_key=f"{address}:{signature}:{token_mint}:{side}",
            signature=signature,
            dex=str(item["dex"]),
        )
        if inserted:
            recorded += 1

    return ForwardWalletCaptureSummary(
        address=address,
        new_transaction_count=len(new_rows),
        recorded_action_count=recorded,
        ignored_new_transaction_count=ignored,
        known_signatures=frozenset(all_signatures),
    )
