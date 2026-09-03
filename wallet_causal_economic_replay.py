import argparse
import json
from dataclasses import asdict
from types import SimpleNamespace

from src.causal_quote_store import ensure_causal_quote_schema, load_causal_quotes
from src.database import connection, initialize_database
from src.wallet_forward_enrollments import load_wallet_forward_enrollments
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_forward_runs import get_wallet_forward_run
from src.wallet_quote_watch import load_successful_quote_keys_by_event
from src.wallet_economic_replay import (
    EconomicReplayConfig,
    replay_source_wallet,
    summarize_economic_replay,
)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Replay econômico causal de wallets (RESEARCH/READ ONLY)."
    )
    p.add_argument("--run-key", help="run COMPLETED/ACTIVE com enrollment econômico congelado")
    p.add_argument("--delays", type=int, nargs="*", default=[0, 15, 30, 60, 120])
    p.add_argument("--allow-proxy-quotes", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    initialize_database()
    ensure_causal_quote_schema()
    if not args.run_key:
        p.error("--run-key é obrigatório para evitar mistura entre runs")
    run = get_wallet_forward_run(args.run_key)
    if run is None:
        p.error(f"run não encontrada: {args.run_key}")
    if run.baseline_observation_id < 0 or run.end_observation_id is None:
        p.error("run precisa ter baseline e end_observation_id")
    if run.enrollment_ends_at is None or run.follow_up_ends_at is None:
        p.error(
            "run não possui protocolo de enrollment/follow-up congelado; "
            "replay econômico legado é bloqueado por segurança"
        )
    if run.enrollment_cutoff_observation_id is None:
        p.error("run ainda não possui enrollment_cutoff_observation_id congelado")

    enrolled = load_wallet_forward_enrollments(run.run_key)
    enrolled_keys = {item.observation_key for item in enrolled}

    ensure_wallet_forward_observation_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, observation_key, wallet_address, token_mint, side,
                chain_time, observed_at, token_delta_raw, token_decimals,
                token_balance_before_raw, token_balance_after_raw,
                token_quantity_flags, source_reduction_fraction
            FROM wallet_forward_observations
            WHERE run_key=? AND id>? AND id<=?
            ORDER BY id""",
            (run.run_key, run.baseline_observation_id, run.end_observation_id),
        ).fetchall()

    # Follow-up-only BUYs remain in the source inventory timeline. They can never
    # open copy lots, but their quantities must prevent a later SELL from being
    # misattributed to the enrolled inventory.
    followup_only_buy_count = 0
    actions = []
    economic_event_keys = []
    for row in rows:
        side = str(row["side"])
        observation_key = str(row["observation_key"])
        economic_eligible = not (side == "buy" and observation_key not in enrolled_keys)
        if side == "buy" and not economic_eligible:
            followup_only_buy_count += 1
        else:
            economic_event_keys.append(observation_key)

        actions.append(
            SimpleNamespace(
                address=str(row["wallet_address"]),
                token_mint=str(row["token_mint"]),
                side=side,
                chain_time=int(row["chain_time"]),
                observed_at=int(row["observed_at"]),
                observation_key=observation_key,
                economic_eligible=economic_eligible,
                token_delta_raw=row["token_delta_raw"],
                token_decimals=row["token_decimals"],
                token_balance_before_raw=row["token_balance_before_raw"],
                token_balance_after_raw=row["token_balance_after_raw"],
                token_quantity_flags=row["token_quantity_flags"],
                source_reduction_fraction=row["source_reduction_fraction"],
            )
        )

    grouped_buy = load_successful_quote_keys_by_event(economic_event_keys, side="buy")
    grouped_sell = load_successful_quote_keys_by_event(economic_event_keys, side="sell")
    grouped = {
        event: tuple(
            dict.fromkeys(grouped_buy.get(event, ()) + grouped_sell.get(event, ()))
        )
        for event in economic_event_keys
    }
    quote_keys = tuple(key for values in grouped.values() for key in values)
    quotes = load_causal_quotes(quote_keys=quote_keys)
    quotes_by_key = {quote_key: quote for quote_key, quote in zip(quote_keys, quotes)}
    quotes_by_event = {
        event: tuple(quotes_by_key[key] for key in keys if key in quotes_by_key)
        for event, keys in grouped.items()
    }
    cfg = EconomicReplayConfig(
        delays=tuple(dict.fromkeys(args.delays)),
        require_executable_quote=not args.allow_proxy_quotes,
    )
    reports = []
    buys = len(enrolled)
    for delay in cfg.delays:
        trades = replay_source_wallet(
            actions,
            quotes,
            config=cfg,
            delay_seconds=delay,
            quotes_by_event=quotes_by_event,
            run_completed=run.status != "ACTIVE",
        )
        reports.append(
            {
                "delay_seconds": delay,
                "summary": asdict(summarize_economic_replay(trades, buy_count=buys)),
            }
        )

    economic_action_count = len(rows) - followup_only_buy_count
    payload = {
        "mode": "RESEARCH_READ_ONLY",
        "economic_sample": (
            "INSUFFICIENT"
            if not any(row["summary"]["closed_count"] for row in reports)
            else "DESCRIPTIVE"
        ),
        "full_run_action_count": len(rows),
        "economic_action_count": economic_action_count,
        "enrolled_buy_count": buys,
        "followup_only_buy_count": followup_only_buy_count,
        "quote_count": len(quotes),
        "reports": reports,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print("Crypto Copy Trader — Causal Economic Replay v1.2 quantity-aware")
    print("Modo: RESEARCH / READ ONLY — nenhum trade é inventado.")
    print(
        f"Ações full-run: {len(rows)} | ações econômicas: {economic_action_count} | "
        f"BUYs enrolled: {buys} | BUYs follow-up-only: {followup_only_buy_count} | "
        f"quotes: {len(quotes)}"
    )
    print(f"Amostra econômica: {payload['economic_sample']}")
    for row in reports:
        summary = row["summary"]
        print(
            f"DELAY +{row['delay_seconds']}s | fechados {summary['closed_count']} | "
            f"open {summary['open_count']} | censurados {summary['censored_count']} | "
            f"média líquida {summary['mean_net_return_pct']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
