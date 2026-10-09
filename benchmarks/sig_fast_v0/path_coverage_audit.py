"""SIG-FAST V0 -- price-path coverage audit (F1c of the 2026-10-08 work order).

Read-only, systems-only diagnostic. Reports, per token, how many already-captured
trades have the raw on-chain fields needed to derive a price (base/quote amounts,
and separately pool reserves), the duration of the captured price path, and the
largest observed gap between consecutive trades. Reports COUNTS ONLY -- never a
price value, a return, or any other outcome-bearing number. Running this script
does not read any economic outcome and does not spend a hypothesis attempt
(registry rule 5: a systems/coverage check is not an economic test).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import ensure_market_observation_schema, record_market_trade
from src.market_opportunity_radar import MarketTradeObservation

VERSION = "sig_fast_price_path_coverage_audit_v0"

DEFAULT_DATABASE = Path("data/copytrader.db")

# Item (b) (2026-10-09 operator review): a token "graduates" when it gets a
# trade on the PumpSwap AMM pool (venue == "pumpswap"), confirmed as the
# literal venue string used by the real adapter (src/carbon_market_trade_
# adapter.py). The operator wants to know whether the engine keeps
# persisting trades for a graduated token for at least this long afterward --
# if it stops ("solta") the token early, that truncates the price path SIG-FAST
# needs to measure outcomes, and is a systems question, never an economic one.
GRADUATION_CONTINUITY_FLOOR_SECONDS = 3_600


@dataclass(frozen=True)
class TokenPathCoverage:
    token_mint: str
    n_trades: int
    n_price_from_amounts: int
    n_price_from_reserves: int
    pct_missing_price_from_amounts: float
    path_duration_seconds: int
    max_gap_seconds: int


def _token_mints_for_run(
    conn: sqlite3.Connection, acquisition_run_key: str, *, min_trades: int, limit: int
) -> list[str]:
    rows = conn.execute(
        """SELECT token_mint, COUNT(*) AS n
        FROM market_trade_observations
        WHERE acquisition_run_key = ?
        GROUP BY token_mint
        HAVING n >= ?
        ORDER BY n DESC
        LIMIT ?""",
        (acquisition_run_key, min_trades, limit),
    ).fetchall()
    return [str(row[0]) for row in rows]


def audit_token(
    conn: sqlite3.Connection, acquisition_run_key: str, token_mint: str
) -> TokenPathCoverage:
    agg = conn.execute(
        """SELECT
            COUNT(*) AS n_trades,
            SUM(CASE WHEN base_amount_raw IS NOT NULL AND base_amount_raw > 0
                      AND quote_amount_raw IS NOT NULL THEN 1 ELSE 0 END) AS n_price_from_amounts,
            SUM(CASE WHEN base_reserves_raw IS NOT NULL AND base_reserves_raw > 0
                      AND quote_reserves_raw IS NOT NULL THEN 1 ELSE 0 END) AS n_price_from_reserves,
            MIN(chain_time) AS first_chain_time,
            MAX(chain_time) AS last_chain_time
        FROM market_trade_observations
        WHERE acquisition_run_key = ? AND token_mint = ?""",
        (acquisition_run_key, token_mint),
    ).fetchone()

    n_trades = int(agg[0] or 0)
    n_price_from_amounts = int(agg[1] or 0)
    n_price_from_reserves = int(agg[2] or 0)
    first_chain_time = agg[3]
    last_chain_time = agg[4]

    if n_trades == 0:
        return TokenPathCoverage(
            token_mint=token_mint,
            n_trades=0,
            n_price_from_amounts=0,
            n_price_from_reserves=0,
            pct_missing_price_from_amounts=100.0,
            path_duration_seconds=0,
            max_gap_seconds=0,
        )

    ordered_times = [
        int(row[0])
        for row in conn.execute(
            """SELECT chain_time FROM market_trade_observations
            WHERE acquisition_run_key = ? AND token_mint = ?
            ORDER BY chain_time""",
            (acquisition_run_key, token_mint),
        ).fetchall()
    ]
    max_gap = 0
    for earlier, later in zip(ordered_times, ordered_times[1:]):
        max_gap = max(max_gap, later - earlier)

    pct_missing = 100.0 * (1.0 - (n_price_from_amounts / n_trades))

    return TokenPathCoverage(
        token_mint=token_mint,
        n_trades=n_trades,
        n_price_from_amounts=n_price_from_amounts,
        n_price_from_reserves=n_price_from_reserves,
        pct_missing_price_from_amounts=round(pct_missing, 2),
        path_duration_seconds=int(last_chain_time) - int(first_chain_time),
        max_gap_seconds=max_gap,
    )


def audit_run(
    conn: sqlite3.Connection,
    acquisition_run_key: str,
    *,
    min_trades: int = 1,
    limit: int = 50,
) -> list[TokenPathCoverage]:
    if min_trades < 1:
        raise ValueError("min_trades must be positive")
    if limit < 1:
        raise ValueError("limit must be positive")
    token_mints = _token_mints_for_run(
        conn, acquisition_run_key, min_trades=min_trades, limit=limit
    )
    return [audit_token(conn, acquisition_run_key, mint) for mint in token_mints]


@dataclass(frozen=True)
class TokenGraduationContinuity:
    token_mint: str
    graduation_chain_time: int
    last_chain_time: int
    continuity_seconds: int
    meets_60min_floor: bool
    drop_reason: str


def _graduated_token_mints_for_run(
    conn: sqlite3.Connection, acquisition_run_key: str
) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT token_mint
        FROM market_trade_observations
        WHERE acquisition_run_key = ? AND venue = 'pumpswap'""",
        (acquisition_run_key,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def audit_graduation_continuity(
    conn: sqlite3.Connection, acquisition_run_key: str
) -> list[TokenGraduationContinuity]:
    """Item (b) (2026-10-08 operator review): for every token that graduated to
    PumpSwap in this run (>=1 trade with venue='pumpswap'), how long after
    graduation does the engine keep persisting trades for that same token?

    drop_reason is a systems-only classification, derived purely from already-
    captured chain_time -- never a price, a return, or any other economic
    signal:
    - "meets_60min_floor": continuity_seconds >= GRADUATION_CONTINUITY_FLOOR_SECONDS.
    - "dropped_before_60min_floor": continuity_seconds is short BUT the run kept
      observing other tokens for at least the floor duration afterward -- this
      specific token stopped while the engine kept working, i.e. the engine
      "let it go" (radar window, episode admission, etc. -- which one requires
      reading the live engine's own state, out of scope for this read-only
      SQL audit).
    - "run_ended_before_60min_floor": continuity_seconds is short because the
      run itself ended shortly after -- not (necessarily) a drop.
    """
    run_last_chain_time_row = conn.execute(
        """SELECT MAX(chain_time) FROM market_trade_observations
        WHERE acquisition_run_key = ?""",
        (acquisition_run_key,),
    ).fetchone()
    if run_last_chain_time_row[0] is None:
        return []
    run_last_chain_time = int(run_last_chain_time_row[0])

    results: list[TokenGraduationContinuity] = []
    for token_mint in _graduated_token_mints_for_run(conn, acquisition_run_key):
        agg = conn.execute(
            """SELECT
                MIN(CASE WHEN venue = 'pumpswap' THEN chain_time END) AS graduation_chain_time,
                MAX(chain_time) AS last_chain_time
            FROM market_trade_observations
            WHERE acquisition_run_key = ? AND token_mint = ?""",
            (acquisition_run_key, token_mint),
        ).fetchone()
        graduation_chain_time = int(agg[0])
        last_chain_time = int(agg[1])
        continuity_seconds = last_chain_time - graduation_chain_time
        meets_floor = continuity_seconds >= GRADUATION_CONTINUITY_FLOOR_SECONDS
        trailing_gap_seconds = run_last_chain_time - last_chain_time

        if meets_floor:
            drop_reason = "meets_60min_floor"
        elif trailing_gap_seconds >= GRADUATION_CONTINUITY_FLOOR_SECONDS:
            drop_reason = "dropped_before_60min_floor"
        else:
            drop_reason = "run_ended_before_60min_floor"

        results.append(
            TokenGraduationContinuity(
                token_mint=token_mint,
                graduation_chain_time=graduation_chain_time,
                last_chain_time=last_chain_time,
                continuity_seconds=continuity_seconds,
                meets_60min_floor=meets_floor,
                drop_reason=drop_reason,
            )
        )
    return results


def summarize_graduation_continuity(
    items: list[TokenGraduationContinuity],
) -> dict[str, object]:
    """Distribution of post-graduation continuity + drop-reason counts. Counts
    and durations only -- no price, no return, no outcome."""
    durations = sorted(item.continuity_seconds for item in items)
    n = len(durations)

    def _pct(p: float) -> int | None:
        if not durations:
            return None
        index = min(n - 1, int(round(p * (n - 1))))
        return durations[index]

    reasons = Counter(item.drop_reason for item in items)
    return {
        "n_graduated_tokens": n,
        "n_meets_60min_floor": reasons.get("meets_60min_floor", 0),
        "n_dropped_before_60min_floor": reasons.get("dropped_before_60min_floor", 0),
        "n_run_ended_before_60min_floor": reasons.get("run_ended_before_60min_floor", 0),
        "continuity_seconds_min": durations[0] if durations else None,
        "continuity_seconds_p50": _pct(0.50),
        "continuity_seconds_p95": _pct(0.95),
        "continuity_seconds_max": durations[-1] if durations else None,
    }


@dataclass(frozen=True)
class RunCoverageSummary:
    n_tokens: int
    n_trades_total: int
    n_graduated_tokens: int
    run_span_seconds: int
    trades_per_hour: float | None
    graduations_per_hour: float | None
    pct_missing_price_from_amounts_overall: float


def audit_run_summary(
    conn: sqlite3.Connection, acquisition_run_key: str
) -> RunCoverageSummary:
    """Item (b) (2026-10-09): whole-run counts for the Passo 0 runbook --
    trades/hour and graduations/hour are the best proxy available *today* for
    "signal rate", never the per-family H1/H2 signal rate itself (that needs
    the discovery loader docs/sig-fast-disc-v0-runbook-v0-2026-10-08.md
    deliberately defers until after DRAFT sign-off). Counts and a duration
    only -- never a price or outcome."""
    agg = conn.execute(
        """SELECT
            COUNT(DISTINCT token_mint) AS n_tokens,
            COUNT(*) AS n_trades_total,
            COUNT(DISTINCT CASE WHEN venue = 'pumpswap' THEN token_mint END) AS n_graduated_tokens,
            SUM(CASE WHEN base_amount_raw IS NOT NULL AND base_amount_raw > 0
                      AND quote_amount_raw IS NOT NULL THEN 1 ELSE 0 END) AS n_price_from_amounts_total,
            MIN(chain_time) AS run_first_chain_time,
            MAX(chain_time) AS run_last_chain_time
        FROM market_trade_observations
        WHERE acquisition_run_key = ?""",
        (acquisition_run_key,),
    ).fetchone()

    n_trades_total = int(agg[1] or 0)
    if n_trades_total == 0:
        return RunCoverageSummary(
            n_tokens=0,
            n_trades_total=0,
            n_graduated_tokens=0,
            run_span_seconds=0,
            trades_per_hour=None,
            graduations_per_hour=None,
            pct_missing_price_from_amounts_overall=100.0,
        )

    run_span_seconds = int(agg[5]) - int(agg[4])
    run_span_hours = run_span_seconds / 3600.0
    n_graduated_tokens = int(agg[2] or 0)
    n_price_from_amounts_total = int(agg[3] or 0)

    return RunCoverageSummary(
        n_tokens=int(agg[0] or 0),
        n_trades_total=n_trades_total,
        n_graduated_tokens=n_graduated_tokens,
        run_span_seconds=run_span_seconds,
        trades_per_hour=(
            round(n_trades_total / run_span_hours, 2) if run_span_hours > 0 else None
        ),
        graduations_per_hour=(
            round(n_graduated_tokens / run_span_hours, 2) if run_span_hours > 0 else None
        ),
        pct_missing_price_from_amounts_overall=round(
            100.0 * (1.0 - (n_price_from_amounts_total / n_trades_total)), 2
        ),
    )


def database_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _self_check() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "self_check.db"
        with patch.object(database, "settings", SimpleNamespace(database_path=db_path)):
            ensure_market_observation_schema()
            for index, (chain_time, base_amt, quote_amt, base_res, quote_res) in enumerate(
                [
                    (1_000, 50_000_000, 2_000_000_000, 1_073_000_000_000_000, 30_000_000_000),
                    (1_010, 40_000_000, 1_600_000_000, 1_033_000_000_000_000, 31_600_000_000),
                    (1_100, 10_000_000, 500_000_000, None, None),
                ]
            ):
                record_market_trade(
                    acquisition_run_key="self-check-run",
                    event_key=f"token-a:{index}",
                    source_provider="self_check",
                    observation=MarketTradeObservation(
                        token_mint="TOKEN_A",
                        side="buy",
                        chain_time=chain_time,
                        observed_at=chain_time,
                        venue="pump_bonding_curve",
                        base_amount_raw=base_amt,
                        quote_amount_raw=quote_amt,
                        base_reserves_raw=base_res,
                        quote_reserves_raw=quote_res,
                    ),
                )
            # Token B: 1 trade, nothing derivable (pre-F1b capture, raw fields NULL).
            record_market_trade(
                acquisition_run_key="self-check-run",
                event_key="token-b:0",
                source_provider="self_check",
                observation=MarketTradeObservation(
                    token_mint="TOKEN_B",
                    side="buy",
                    chain_time=5_000,
                    observed_at=5_000,
                    venue="pumpswap",
                ),
            )
            # Item (b) continuity fixtures. TOKEN_C graduates and keeps getting
            # trades for >=60min after: meets_60min_floor. TOKEN_D graduates and
            # stops quickly, but TOKEN_E's later trade proves the run kept
            # observing other tokens well past TOKEN_D's floor deadline:
            # dropped_before_60min_floor. TOKEN_F graduates right at the run's
            # own tail: run_ended_before_60min_floor (short, but not a drop).
            for token_mint, event_key, chain_time, venue in (
                ("TOKEN_C", "token-c:0", 10_000, "pump"),
                ("TOKEN_C", "token-c:1", 10_050, "pumpswap"),
                ("TOKEN_C", "token-c:2", 14_000, "pumpswap"),
                ("TOKEN_D", "token-d:0", 20_000, "pump"),
                ("TOKEN_D", "token-d:1", 20_050, "pumpswap"),
                ("TOKEN_D", "token-d:2", 20_100, "pumpswap"),
                ("TOKEN_E", "token-e:0", 30_000, "pump"),
                ("TOKEN_F", "token-f:0", 29_950, "pumpswap"),
                ("TOKEN_F", "token-f:1", 30_000, "pumpswap"),
            ):
                record_market_trade(
                    acquisition_run_key="self-check-run",
                    event_key=event_key,
                    source_provider="self_check",
                    observation=MarketTradeObservation(
                        token_mint=token_mint,
                        side="buy",
                        chain_time=chain_time,
                        observed_at=chain_time,
                        venue=venue,
                    ),
                )

            with database_connection(db_path) as conn:
                results = audit_run(conn, "self-check-run", min_trades=1, limit=10)
                continuity = audit_graduation_continuity(conn, "self-check-run")
                run_summary = audit_run_summary(conn, "self-check-run")

    by_mint = {item.token_mint: item for item in results}
    token_a = by_mint["TOKEN_A"]
    assert token_a.n_trades == 3, token_a
    assert token_a.n_price_from_amounts == 3, token_a
    assert token_a.n_price_from_reserves == 2, token_a
    assert token_a.pct_missing_price_from_amounts == 0.0, token_a
    assert token_a.path_duration_seconds == 100, token_a
    assert token_a.max_gap_seconds == 90, token_a

    token_b = by_mint["TOKEN_B"]
    assert token_b.n_trades == 1, token_b
    assert token_b.n_price_from_amounts == 0, token_b
    assert token_b.pct_missing_price_from_amounts == 100.0, token_b
    assert token_b.path_duration_seconds == 0, token_b
    assert token_b.max_gap_seconds == 0, token_b

    continuity_by_mint = {item.token_mint: item for item in continuity}
    assert set(continuity_by_mint) == {"TOKEN_B", "TOKEN_C", "TOKEN_D", "TOKEN_F"}, continuity

    # TOKEN_B graduates at t=5000 with no further trades, while the run keeps
    # observing other tokens all the way to t=30000 -- dropped, not just a
    # short run.
    token_b_continuity = continuity_by_mint["TOKEN_B"]
    assert token_b_continuity.continuity_seconds == 0, token_b_continuity
    assert token_b_continuity.drop_reason == "dropped_before_60min_floor", token_b_continuity

    token_c = continuity_by_mint["TOKEN_C"]
    assert token_c.graduation_chain_time == 10_050, token_c
    assert token_c.continuity_seconds == 3_950, token_c
    assert token_c.meets_60min_floor is True, token_c
    assert token_c.drop_reason == "meets_60min_floor", token_c

    token_d = continuity_by_mint["TOKEN_D"]
    assert token_d.continuity_seconds == 50, token_d
    assert token_d.meets_60min_floor is False, token_d
    assert token_d.drop_reason == "dropped_before_60min_floor", token_d

    token_f = continuity_by_mint["TOKEN_F"]
    assert token_f.continuity_seconds == 50, token_f
    assert token_f.drop_reason == "run_ended_before_60min_floor", token_f

    continuity_summary = summarize_graduation_continuity(continuity)
    assert continuity_summary["n_graduated_tokens"] == 4, continuity_summary
    assert continuity_summary["n_meets_60min_floor"] == 1, continuity_summary
    assert continuity_summary["n_dropped_before_60min_floor"] == 2, continuity_summary
    assert continuity_summary["n_run_ended_before_60min_floor"] == 1, continuity_summary

    print("self-check OK:", json.dumps([asdict(r) for r in results], sort_keys=True))
    print(
        "self-check continuity OK:",
        json.dumps([asdict(r) for r in continuity], sort_keys=True),
    )
    print("self-check continuity summary OK:", json.dumps(continuity_summary, sort_keys=True))

    assert run_summary.n_tokens == 6, run_summary
    assert run_summary.n_trades_total == 13, run_summary
    assert run_summary.n_graduated_tokens == 4, run_summary
    assert run_summary.run_span_seconds == 29_000, run_summary
    assert run_summary.trades_per_hour == 1.61, run_summary
    assert run_summary.graduations_per_hour == 0.5, run_summary
    assert run_summary.pct_missing_price_from_amounts_overall == 76.92, run_summary

    print("self-check run summary OK:", json.dumps(asdict(run_summary), sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SIG-FAST V0 price-path coverage audit: per-token counts of trades "
            "with a derivable price, never outcome/return values."
        )
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--acquisition-run-key", type=str, default=None)
    parser.add_argument("--min-trades", type=int, default=1)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0

    if not args.acquisition_run_key:
        parser.error("--acquisition-run-key is required outside --self-check")

    with patch.object(database, "settings", SimpleNamespace(database_path=args.database)):
        ensure_market_observation_schema()
        with database_connection(args.database) as conn:
            results = audit_run(
                conn,
                args.acquisition_run_key,
                min_trades=args.min_trades,
                limit=args.limit,
            )
            continuity = audit_graduation_continuity(conn, args.acquisition_run_key)
            run_summary = audit_run_summary(conn, args.acquisition_run_key)

    continuity_summary = summarize_graduation_continuity(continuity)
    payload = {
        "version": VERSION,
        "database": str(args.database),
        "acquisition_run_key": args.acquisition_run_key,
        "classification": "SYSTEMS_COVERAGE_ONLY_NOT_AN_ECONOMIC_TEST",
        "tokens": [asdict(item) for item in results],
        "run_summary": asdict(run_summary),
        "graduation_continuity_summary": continuity_summary,
        "graduation_continuity_tokens": [asdict(item) for item in continuity],
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
