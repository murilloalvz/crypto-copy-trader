import argparse
import json
from dataclasses import asdict

from src.causal_quote_store import ensure_causal_quote_schema, load_causal_quotes
from src.database import connection, initialize_database
from src.database import connection
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_forward_runs import get_wallet_forward_run
from src.wallet_quote_watch import load_successful_quote_keys_by_event
from src.wallet_economic_replay import EconomicReplayConfig, replay_source_wallet, summarize_economic_replay


def main(argv=None):
    p = argparse.ArgumentParser(description="Replay econômico causal de wallets (RESEARCH/READ ONLY).")
    p.add_argument("--run-key", help="reservado para escopo futuro; ações atuais devem ser run-scoped")
    p.add_argument("--delays", type=int, nargs="*", default=[0, 15, 30, 60, 120])
    p.add_argument("--allow-proxy-quotes", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    initialize_database(); ensure_causal_quote_schema()
    if not args.run_key:
        p.error("--run-key é obrigatório para evitar mistura entre runs")
    run = get_wallet_forward_run(args.run_key)
    if run is None:
        p.error(f"run não encontrada: {args.run_key}")
    if run.baseline_observation_id < 0 or run.end_observation_id is None:
        p.error("run precisa ter baseline e end_observation_id")
    ensure_wallet_forward_observation_schema()
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, observation_key, wallet_address, token_mint, side, chain_time, observed_at "
            "FROM wallet_forward_observations WHERE id > ? AND id <= ? ORDER BY id",
            (run.baseline_observation_id, run.end_observation_id),
        ).fetchall()
    actions = [WalletActionObservation(str(r["wallet_address"]), str(r["token_mint"]), str(r["side"]), int(r["chain_time"]), int(r["observed_at"])) for r in rows]
    event_keys = [str(r["observation_key"]) for r in rows]
    grouped = load_successful_quote_keys_by_event(event_keys)
    quote_keys = tuple(key for values in grouped.values() for key in values)
    quotes = load_causal_quotes(quote_keys=quote_keys)
    cfg = EconomicReplayConfig(delays=tuple(dict.fromkeys(args.delays)), require_executable_quote=not args.allow_proxy_quotes)
    reports = []
    buys = sum(a.side == "buy" for a in actions)
    for delay in cfg.delays:
        trades = replay_source_wallet(actions, quotes, config=cfg, delay_seconds=delay)
        reports.append({"delay_seconds": delay, "summary": asdict(summarize_economic_replay(trades, buy_count=buys))})
    payload = {"mode": "RESEARCH_READ_ONLY", "economic_sample": "INSUFFICIENT" if not any(r["summary"]["closed_count"] for r in reports) else "DESCRIPTIVE", "action_count": len(actions), "quote_count": len(quotes), "reports": reports}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2)); return 0
    print("Crypto Copy Trader — Causal Economic Replay v1")
    print("Modo: RESEARCH / READ ONLY — nenhum trade é inventado.")
    print(f"Ações: {len(actions)} | BUYs: {buys} | quotes: {len(quotes)}")
    print(f"Amostra econômica: {payload['economic_sample']}")
    for row in reports:
        s=row["summary"]
        print(f"DELAY +{row['delay_seconds']}s | fechados {s['closed_count']} | open {s['open_count']} | censurados {s['censored_count']} | média líquida {s['mean_net_return_pct']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
