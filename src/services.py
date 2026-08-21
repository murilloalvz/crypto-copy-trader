from src.config import settings
from src.database import connection, rows
from src.solana import SolanaClient, parse_wallet_transaction


def sync_wallet(address: str, client: SolanaClient | None = None) -> dict:
    client = client or SolanaClient()
    signatures = client.signatures(address, settings.max_signatures)
    inserted = skipped = 0
    with connection() as conn:
        known = {
            row["signature"]
            for row in conn.execute(
                "SELECT signature FROM transactions WHERE wallet_address=?", (address,)
            ).fetchall()
        }
    for item in reversed(signatures):
        signature = item["signature"]
        if signature in known:
            skipped += 1
            continue
        tx = client.transaction(signature)
        if not tx:
            skipped += 1
            continue
        parsed = parse_wallet_transaction(address, signature, tx)
        with connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO transactions
                (signature, wallet_address, block_time, status, kind, sol_change, fee_sol,
                 token_mint, token_change, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    parsed["signature"], address, parsed["block_time"], parsed["status"],
                    parsed["kind"], parsed["sol_change"], parsed["fee_sol"],
                    parsed["token_mint"], parsed["token_change"], parsed["raw_json"],
                ),
            )
            conn.execute("UPDATE wallets SET last_signature=? WHERE address=?", (signature, address))
        inserted += 1
    return {"found": len(signatures), "inserted": inserted, "skipped": skipped}


def generate_paper_trades(address: str) -> int:
    transactions = rows(
        """SELECT * FROM transactions WHERE wallet_address=? AND status='success'
        AND kind='swap' AND token_change IS NOT NULL ORDER BY block_time""",
        (address,),
    )
    created = 0
    with connection() as conn:
        for tx in transactions:
            side = "buy" if tx["token_change"] > 0 else "sell"
            cursor = conn.execute(
                """INSERT OR IGNORE INTO paper_trades
                (source_signature, wallet_address, token_mint, side, source_amount,
                 simulated_usd, slippage_bps, delay_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tx["signature"], address, tx["token_mint"], side,
                    abs(tx["token_change"]), settings.copy_size_usd,
                    settings.slippage_bps, settings.copy_delay_seconds,
                ),
            )
            created += cursor.rowcount
    return created

