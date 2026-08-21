import json

from src.assets import STABLECOIN_MINTS
from src.config import settings
from src.database import connection, rows
from src.prices import GeckoTerminalPriceProvider
from src.solana import SolanaClient, parse_wallet_transaction


def reparse_wallet_transactions(address: str) -> int:
    transactions = rows(
        "SELECT signature, raw_json FROM transactions WHERE wallet_address=?", (address,)
    )
    updated = 0
    with connection() as conn:
        for item in transactions:
            parsed = parse_wallet_transaction(
                address, item["signature"], json.loads(item["raw_json"])
            )
            conn.execute(
                """UPDATE transactions SET status=?, kind=?, sol_change=?, fee_sol=?,
                token_mint=?, token_change=? WHERE signature=?""",
                (
                    parsed["status"], parsed["kind"], parsed["sol_change"],
                    parsed["fee_sol"], parsed["token_mint"], parsed["token_change"],
                    item["signature"],
                ),
            )
            updated += 1
    return updated


def sync_wallet(
    address: str,
    client: SolanaClient | None = None,
    backfill: bool = False,
) -> dict:
    client = client or SolanaClient()
    with connection() as conn:
        wallet = conn.execute(
            "SELECT oldest_signature FROM wallets WHERE address=?", (address,)
        ).fetchone()
    before = wallet["oldest_signature"] if backfill and wallet else None
    signatures = client.signatures(address, settings.max_signatures, before=before)
    inserted = skipped = failed = 0
    first_error = None
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
        try:
            tx = client.transaction(signature)
            if not tx:
                skipped += 1
                continue
            parsed = parse_wallet_transaction(address, signature, tx)
            with connection() as conn:
                cursor = conn.execute(
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
            inserted += cursor.rowcount
        except Exception as exc:
            failed += 1
            first_error = first_error or str(exc)
    if signatures:
        newest_signature = signatures[0]["signature"]
        oldest_signature = signatures[-1]["signature"]
        with connection() as conn:
            if backfill:
                conn.execute(
                    "UPDATE wallets SET oldest_signature=? WHERE address=?",
                    (oldest_signature, address),
                )
            else:
                conn.execute(
                    """UPDATE wallets SET last_signature=?,
                    oldest_signature=COALESCE(oldest_signature, ?) WHERE address=?""",
                    (newest_signature, oldest_signature, address),
                )
    return {
        "found": len(signatures),
        "inserted": inserted,
        "skipped": skipped,
        "failed": failed,
        "first_error": first_error,
    }


def generate_paper_trades(address: str) -> int:
    reparse_wallet_transactions(address)
    transactions = rows(
        """SELECT * FROM transactions WHERE wallet_address=? AND status='success'
        AND kind='swap' AND token_change IS NOT NULL ORDER BY block_time""",
        (address,),
    )
    existing = {
        item["source_signature"]
        for item in rows(
            "SELECT source_signature FROM paper_trades WHERE wallet_address=?", (address,)
        )
    }
    created = 0
    with connection() as conn:
        for tx in transactions:
            if tx["token_mint"] in STABLECOIN_MINTS:
                continue
            side = "buy" if tx["token_change"] > 0 else "sell"
            conn.execute(
                """INSERT INTO paper_trades
                (source_signature, wallet_address, token_mint, side, source_amount,
                 simulated_usd, slippage_bps, delay_seconds, source_block_time, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_price')
                ON CONFLICT(source_signature) DO UPDATE SET
                    token_mint=excluded.token_mint,
                    side=excluded.side,
                    source_amount=excluded.source_amount,
                    source_block_time=COALESCE(paper_trades.source_block_time,
                                               excluded.source_block_time)""",
                (
                    tx["signature"], address, tx["token_mint"], side,
                    abs(tx["token_change"]), settings.copy_size_usd,
                    settings.slippage_bps, settings.copy_delay_seconds, tx["block_time"],
                ),
            )
            if tx["signature"] not in existing:
                created += 1
    return created


def _consume_fifo(lots: list[list[float]], quantity: float) -> tuple[float, float]:
    remaining = quantity
    cost_basis = 0.0
    consumed = 0.0
    while lots and remaining > 1e-12:
        lot_quantity, lot_unit_cost = lots[0]
        taken = min(lot_quantity, remaining)
        cost_basis += taken * lot_unit_cost
        consumed += taken
        remaining -= taken
        lot_quantity -= taken
        if lot_quantity <= 1e-12:
            lots.pop(0)
        else:
            lots[0][0] = lot_quantity
    return consumed, cost_basis


def rebuild_paper_ledger(address: str) -> dict:
    trades = rows(
        """SELECT * FROM paper_trades WHERE wallet_address=?
        ORDER BY COALESCE(source_block_time, 0), id""",
        (address,),
    )
    lots_by_mint: dict[str, list[list[float]]] = {}
    closed = skipped = 0
    with connection() as conn:
        for trade in trades:
            price = trade.get("execution_price_usd")
            if not price:
                continue
            mint = trade["token_mint"]
            lots = lots_by_mint.setdefault(mint, [])
            if trade["side"] == "buy":
                quantity = trade["simulated_usd"] / price
                lots.append([quantity, price])
                conn.execute(
                    """UPDATE paper_trades SET token_quantity=?, realized_pnl_usd=NULL,
                    status='open' WHERE id=?""",
                    (quantity, trade["id"]),
                )
                continue

            desired_quantity = trade["simulated_usd"] / price
            quantity, cost_basis = _consume_fifo(lots, desired_quantity)
            if quantity <= 1e-12:
                skipped += 1
                conn.execute(
                    """UPDATE paper_trades SET token_quantity=0, realized_pnl_usd=NULL,
                    status='skipped_no_position' WHERE id=?""",
                    (trade["id"],),
                )
                continue
            proceeds = quantity * price
            pnl = proceeds - cost_basis
            closed += 1
            conn.execute(
                """UPDATE paper_trades SET token_quantity=?, realized_pnl_usd=?,
                status='closed' WHERE id=?""",
                (quantity, pnl, trade["id"]),
            )
    return {"closed": closed, "skipped": skipped}


def price_paper_trades(
    address: str,
    provider: GeckoTerminalPriceProvider | None = None,
) -> dict:
    provider = provider or GeckoTerminalPriceProvider()
    generate_paper_trades(address)
    trades = rows(
        """SELECT pt.*, tx.block_time FROM paper_trades pt
        JOIN transactions tx ON tx.signature=pt.source_signature
        WHERE pt.wallet_address=? ORDER BY tx.block_time, pt.id""",
        (address,),
    )
    priced = cached = failed = 0
    for trade in trades:
        if trade["market_price_usd"] is not None:
            cached += 1
            continue
        timestamp = int(trade["block_time"] or 0) + int(trade["delay_seconds"])
        try:
            market_price = provider.price_at(trade["token_mint"], timestamp)
            slippage = trade["slippage_bps"] / 10_000
            multiplier = 1 + slippage if trade["side"] == "buy" else 1 - slippage
            execution_price = market_price * multiplier
            fees_usd = trade["simulated_usd"] * slippage
            with connection() as conn:
                conn.execute(
                    """UPDATE paper_trades SET source_block_time=?, market_price_usd=?,
                    execution_price_usd=?, fees_usd=?, price_error=NULL, status='priced'
                    WHERE id=?""",
                    (timestamp, market_price, execution_price, fees_usd, trade["id"]),
                )
            priced += 1
        except Exception as exc:
            failed += 1
            with connection() as conn:
                conn.execute(
                    """UPDATE paper_trades SET source_block_time=?, price_error=?,
                    status='price_unavailable' WHERE id=?""",
                    (timestamp, str(exc), trade["id"]),
                )
    ledger = rebuild_paper_ledger(address)
    return {"priced": priced, "cached": cached, "failed": failed, **ledger}
