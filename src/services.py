import json
from collections import Counter

from src.assets import STABLECOIN_MINTS
from src.config import settings
from src.database import connection, rows
from src.prices import GeckoTerminalPriceProvider, PriceProviderError
from src.solana import (
    DEX_PROGRAM_LABELS,
    INFRASTRUCTURE_PROGRAM_IDS,
    SolanaClient,
    parse_wallet_transaction,
    transaction_program_ids,
)


def wallet_protocol_diagnostics(address: str, limit: int = 500) -> dict:
    transactions = rows(
        """SELECT kind, dex, raw_json FROM transactions WHERE wallet_address=?
        ORDER BY block_time DESC LIMIT ?""",
        (address, limit),
    )
    supported = Counter()
    unknown = Counter()
    unreadable = 0
    for item in transactions:
        try:
            program_ids = transaction_program_ids(json.loads(item["raw_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            unreadable += 1
            continue
        for program_id in program_ids:
            label = DEX_PROGRAM_LABELS.get(program_id)
            if label:
                supported[(label, program_id)] += 1
            elif program_id not in INFRASTRUCTURE_PROGRAM_IDS:
                unknown[program_id] += 1

    return {
        "analyzed": len(transactions),
        "unreadable": unreadable,
        "dex_activity": sum(item["kind"] == "dex_activity" for item in transactions),
        "supported": [
            {"protocolo": label, "program_id": program_id, "transações": count}
            for (label, program_id), count in supported.most_common()
        ],
        "unknown": [
            {"program_id": program_id, "transações": count}
            for program_id, count in unknown.most_common(12)
        ],
    }


def reparse_wallet_transactions(address: str) -> int:
    transactions = rows(
        """SELECT signature, status, kind, dex, sol_change, fee_sol, token_mint,
        token_change, raw_json FROM transactions WHERE wallet_address=?""",
        (address,),
    )
    updated = 0
    with connection() as conn:
        for item in transactions:
            parsed = parse_wallet_transaction(
                address, item["signature"], json.loads(item["raw_json"])
            )
            current = (
                item["status"], item["kind"], item.get("dex"), item["sol_change"],
                item["fee_sol"], item["token_mint"], item["token_change"],
            )
            refreshed = (
                parsed["status"], parsed["kind"], parsed["dex"], parsed["sol_change"],
                parsed["fee_sol"], parsed["token_mint"], parsed["token_change"],
            )
            if current == refreshed:
                continue
            conn.execute(
                """UPDATE transactions SET status=?, kind=?, dex=?, sol_change=?, fee_sol=?,
                token_mint=?, token_change=? WHERE signature=?""",
                (
                    parsed["status"], parsed["kind"], parsed["dex"],
                    parsed["sol_change"], parsed["fee_sol"], parsed["token_mint"],
                    parsed["token_change"], item["signature"],
                ),
            )
            updated += 1

        # Preserve the old simulation row for auditability, but remove it from
        # performance whenever the stricter parser rejects its source transaction.
        conn.execute(
            """UPDATE paper_trades SET status='filtered_non_swap',
            token_quantity=NULL, realized_pnl_usd=NULL,
            price_error='Ignorada: a transação não é um swap confirmado por DEX suportada.'
            WHERE wallet_address=? AND status!='filtered_non_swap'
            AND source_signature IN (
                SELECT signature FROM transactions
                WHERE wallet_address=? AND (kind!='swap' OR dex IS NULL)
            )""",
            (address, address),
        )
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
                    (signature, wallet_address, block_time, status, kind, dex, sol_change,
                     fee_sol, token_mint, token_change, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        parsed["signature"], address, parsed["block_time"], parsed["status"],
                        parsed["kind"], parsed["dex"], parsed["sol_change"],
                        parsed["fee_sol"], parsed["token_mint"], parsed["token_change"],
                        parsed["raw_json"],
                    ),
                )
                conn.execute(
                    "UPDATE wallets SET last_signature=? WHERE address=?",
                    (signature, address),
                )
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
        "rpc_endpoint": client.rpc_host,
    }


def generate_paper_trades(address: str) -> int:
    reparse_wallet_transactions(address)
    transactions = rows(
        """SELECT * FROM transactions WHERE wallet_address=? AND status='success'
        AND kind='swap' AND dex IS NOT NULL AND token_change IS NOT NULL ORDER BY block_time""",
        (address,),
    )
    existing = {
        item["source_signature"]: item
        for item in rows(
            """SELECT source_signature, token_mint, side, status
            FROM paper_trades WHERE wallet_address=?""",
            (address,),
        )
    }
    created = 0
    with connection() as conn:
        for tx in transactions:
            if tx["token_mint"] in STABLECOIN_MINTS:
                continue
            side = "buy" if tx["token_change"] > 0 else "sell"
            previous = existing.get(tx["signature"])
            if previous is None:
                conn.execute(
                    """INSERT INTO paper_trades
                    (source_signature, wallet_address, token_mint, side, source_amount,
                     simulated_usd, slippage_bps, delay_seconds, source_block_time, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_price')""",
                    (
                        tx["signature"], address, tx["token_mint"], side,
                        abs(tx["token_change"]), settings.copy_size_usd,
                        settings.slippage_bps, settings.copy_delay_seconds, tx["block_time"],
                    ),
                )
                created += 1
                continue

            classification_changed = (
                previous["token_mint"] != tx["token_mint"]
                or previous["side"] != side
                or previous["status"] == "filtered_non_swap"
            )
            if classification_changed:
                conn.execute(
                    """UPDATE paper_trades SET token_mint=?, side=?, source_amount=?,
                    source_block_time=?, market_price_usd=NULL, execution_price_usd=NULL,
                    token_quantity=NULL, fees_usd=NULL, realized_pnl_usd=NULL,
                    price_error=NULL, price_error_code=NULL, price_retry_count=0,
                    last_price_attempt_at=NULL, status='pending_price'
                    WHERE source_signature=?""",
                    (
                        tx["token_mint"], side, abs(tx["token_change"]), tx["block_time"],
                        tx["signature"],
                    ),
                )
            else:
                conn.execute(
                    """UPDATE paper_trades SET source_amount=?
                    WHERE source_signature=?""",
                    (abs(tx["token_change"]), tx["signature"]),
                )
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
        """SELECT pt.* FROM paper_trades pt
        JOIN transactions tx ON tx.signature=pt.source_signature
        WHERE pt.wallet_address=? AND tx.kind='swap' AND tx.dex IS NOT NULL
        AND pt.status NOT IN ('filtered_non_swap', 'skipped_illiquid', 'skipped_low_volume')
        ORDER BY COALESCE(pt.source_block_time, 0), pt.id""",
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
        WHERE pt.wallet_address=? AND tx.kind='swap' AND tx.dex IS NOT NULL
        AND pt.status NOT IN (
            'filtered_non_swap', 'skipped_illiquid', 'skipped_low_volume',
            'price_no_pool', 'price_no_historical_candle',
            'price_distant_historical_candle', 'price_permanent_error',
            'price_retry_exhausted'
        ) ORDER BY tx.block_time, pt.id""",
        (address,),
    )
    priced = cached = failed = illiquid = low_volume = 0
    retryable_failures = permanent_failures = exhausted_failures = 0
    for trade in trades:
        if trade["market_price_usd"] is not None:
            cached += 1
            continue
        timestamp = int(trade["block_time"] or 0) + int(trade["delay_seconds"])
        try:
            market_for = getattr(provider, "market_for", None)
            if market_for is not None:
                market = market_for(trade["token_mint"])
                min_liquidity = getattr(settings, "min_signal_liquidity_usd", 50_000.0)
                min_volume = getattr(settings, "min_signal_volume_24h_usd", 10_000.0)
                if market.reserve_usd < min_liquidity:
                    illiquid += 1
                    with connection() as conn:
                        conn.execute(
                            """UPDATE paper_trades SET source_block_time=?,
                            market_price_usd=NULL, execution_price_usd=NULL,
                            token_quantity=NULL, fees_usd=NULL, realized_pnl_usd=NULL,
                            price_error=?, price_error_code='market_liquidity_low',
                            last_price_attempt_at=CURRENT_TIMESTAMP,
                            status='skipped_illiquid' WHERE id=?""",
                            (
                                timestamp,
                                f"Ignorada: liquidez atual US$ {market.reserve_usd:,.2f} "
                                f"abaixo do mínimo US$ {min_liquidity:,.2f}.",
                                trade["id"],
                            ),
                        )
                    continue
                if market.volume_usd_24h < min_volume:
                    low_volume += 1
                    with connection() as conn:
                        conn.execute(
                            """UPDATE paper_trades SET source_block_time=?,
                            market_price_usd=NULL, execution_price_usd=NULL,
                            token_quantity=NULL, fees_usd=NULL, realized_pnl_usd=NULL,
                            price_error=?, price_error_code='market_volume_low',
                            last_price_attempt_at=CURRENT_TIMESTAMP,
                            status='skipped_low_volume' WHERE id=?""",
                            (
                                timestamp,
                                f"Ignorada: volume 24h US$ {market.volume_usd_24h:,.2f} "
                                f"abaixo do mínimo US$ {min_volume:,.2f}.",
                                trade["id"],
                            ),
                        )
                    continue
            market_price = provider.price_at(trade["token_mint"], timestamp)
            slippage = trade["slippage_bps"] / 10_000
            multiplier = 1 + slippage if trade["side"] == "buy" else 1 - slippage
            execution_price = market_price * multiplier
            fees_usd = trade["simulated_usd"] * slippage
            with connection() as conn:
                conn.execute(
                    """UPDATE paper_trades SET source_block_time=?, market_price_usd=?,
                    execution_price_usd=?, fees_usd=?, price_error=NULL,
                    price_error_code=NULL, last_price_attempt_at=CURRENT_TIMESTAMP,
                    status='priced'
                    WHERE id=?""",
                    (timestamp, market_price, execution_price, fees_usd, trade["id"]),
                )
            priced += 1
        except Exception as exc:
            failed += 1
            retry_count = int(trade.get("price_retry_count") or 0) + 1
            max_retries = max(1, getattr(settings, "max_price_retry_attempts", 3))
            retryable = isinstance(exc, PriceProviderError) and exc.retryable
            error_code = getattr(exc, "code", "unexpected_provider_error")
            if retryable and retry_count < max_retries:
                failure_status = "price_retryable"
                retryable_failures += 1
            elif retryable:
                failure_status = "price_retry_exhausted"
                exhausted_failures += 1
            else:
                failure_status = f"price_{error_code}"
                if failure_status not in {
                    "price_no_pool",
                    "price_no_historical_candle",
                    "price_distant_historical_candle",
                }:
                    failure_status = "price_permanent_error"
                permanent_failures += 1
            with connection() as conn:
                conn.execute(
                    """UPDATE paper_trades SET source_block_time=?, price_error=?,
                    price_error_code=?, price_retry_count=?,
                    last_price_attempt_at=CURRENT_TIMESTAMP, status=? WHERE id=?""",
                    (
                        timestamp, str(exc), error_code, retry_count,
                        failure_status, trade["id"],
                    ),
                )
    ledger = rebuild_paper_ledger(address)
    return {
        "priced": priced,
        "cached": cached,
        "failed": failed,
        "retryable_failures": retryable_failures,
        "permanent_failures": permanent_failures,
        "exhausted_failures": exhausted_failures,
        "skipped_illiquid": illiquid,
        "skipped_low_volume": low_volume,
        **ledger,
    }
