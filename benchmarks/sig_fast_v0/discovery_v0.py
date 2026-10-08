"""SIG-FAST-DISC-V0 discovery engine (F7 of the 2026-10-08 work order).

NOT AUTHORIZED TO RUN AGAINST REAL DATA YET. SIG-FAST-DISC-V0 is still a
RASCUNHO awaiting operator sign-off
(docs/sig-fast-disc-v0-batch-preregistration-DRAFT-2026-10-08.md). This file
is prepared infrastructure, exercised only by --self-check against synthetic
data in this repository state. Running it for real is the operator's own
call, at home, strictly after sign-off -- see
docs/sig-fast-disc-v0-runbook-v0-2026-10-08.md.

Three disciplines this module enforces structurally, not just by convention:

1. The exact input (every signal, every trade, every baseline candidate) is
   hashed and the hash is written to a manifest file BEFORE any metric is
   computed -- so the sample cannot be quietly redefined after seeing a
   result.
2. Any phase that could hang (future: a live DB/RPC call) is wrapped in a
   StallGuard with an explicit timeout, never an indefinite wait.
3. The 70/30 split is by signal_time order (temporal, deterministic), and the
   exit rule is selected ONLY on the 70% train split, then frozen and applied
   unchanged to the 30% holdout -- no re-selection after seeing holdout
   numbers.

This script does not decide what counts as a signal or a baseline candidate
for a family (H1/H2) -- that selection logic depends on decisions still open
in F5 (cohort criteria, survival window grid) and is out of scope here. The
CLI takes an already-assembled JSON input file; building the DB loader that
produces that file is future work, explicitly left for after sign-off.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import signal
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from src.opportunity_path_baseline_v0 import (
    TokenCandidate,
    build_paired_baseline,
)
from src.opportunity_path_metrics_v0 import (
    EXIT_RULE_IDS,
    CausalEntry,
    CostModel,
    PathTrade,
    find_causal_entry,
    first_barrier_touch,
    simulate_exit,
)

VERSION = "sig_fast_disc_v0"
DEFAULT_ENTRY_LATENCY_GRID_SECONDS = (5, 15, 30, 60, 120)
DEFAULT_WINDOW_SECONDS = 900
DEFAULT_TARGET_PCT = 50.0
DEFAULT_STOP_PCT = -30.0
DEFAULT_HOLDOUT_FRACTION = 0.3
DEFAULT_STALL_GUARD_SECONDS = 300


class StallGuardTimeout(Exception):
    pass


class StallGuard:
    """Aborts the wrapped phase after `seconds` instead of hanging forever.

    POSIX-only (uses SIGALRM), which matches this project's runtime. A phase
    that legitimately needs longer must raise the limit explicitly, not have
    this guard silently disabled.
    """

    def __init__(self, seconds: int, *, label: str):
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        self.seconds = seconds
        self.label = label

    def __enter__(self) -> "StallGuard":
        def _handler(signum, frame):
            raise StallGuardTimeout(f"{self.label} exceeded {self.seconds}s stall guard")

        self._previous = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(self.seconds)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self._previous)


@dataclass(frozen=True)
class DiscoverySignalInput:
    signal_token_mint: str
    family_id: str
    signal_time: int
    venue: str
    age_seconds: int
    trades: tuple[PathTrade, ...]
    baseline_pool: tuple[TokenCandidate, ...]
    baseline_trades_by_mint: dict[str, tuple[PathTrade, ...]]


def freeze_input_snapshot(signal_inputs: Sequence[DiscoverySignalInput], *, manifest_path: Path) -> str:
    """Hashes the exact input and writes the hash to `manifest_path` BEFORE
    any metric is computed. Returns the sha256 hex digest."""

    canonical_rows = []
    for item in signal_inputs:
        canonical_rows.append(
            {
                "signal_token_mint": item.signal_token_mint,
                "family_id": item.family_id,
                "signal_time": item.signal_time,
                "venue": item.venue,
                "age_seconds": item.age_seconds,
                "trades": [asdict(t) for t in item.trades],
                "baseline_pool": [asdict(c) for c in item.baseline_pool],
                "baseline_trades_by_mint": {
                    mint: [asdict(t) for t in trades]
                    for mint, trades in sorted(item.baseline_trades_by_mint.items())
                },
            }
        )
    canonical_rows.sort(key=lambda row: (row["family_id"], row["signal_token_mint"], row["signal_time"]))
    canonical_json = json.dumps(canonical_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical_json).hexdigest()

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"sha256": digest, "n_signals": len(signal_inputs)}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return digest


def _net_returns_for_rule(
    signals: Sequence[DiscoverySignalInput],
    *,
    rule_id: str,
    entry_latency_seconds: int,
    exit_latency_seconds: int,
    window_seconds: int,
    size_sol: float,
    cost_model: CostModel,
) -> list[float]:
    out = []
    for item in signals:
        entry = find_causal_entry(
            item.trades,
            signal_time=item.signal_time,
            entry_latency_seconds=entry_latency_seconds,
            size_sol=size_sol,
            cost_model=cost_model,
        )
        if entry.trade_chain_time is None or entry.execution_price_sol is None:
            continue
        exit_result = simulate_exit(
            item.trades,
            rule_id=rule_id,
            entry_chain_time=entry.trade_chain_time,
            entry_execution_price_sol=entry.execution_price_sol,
            size_sol=size_sol,
            window_seconds=window_seconds,
            exit_latency_seconds=exit_latency_seconds,
            cost_model=cost_model,
        )
        if exit_result.net_return_pct is not None:
            out.append(exit_result.net_return_pct)
    return out


def _profit_factor(returns: Sequence[float]) -> float | None:
    gains = sum(r for r in returns if r > 0)
    losses = -sum(r for r in returns if r < 0)
    if losses == 0:
        return None
    return gains / losses


def select_best_exit_rule(
    train_signals: Sequence[DiscoverySignalInput],
    *,
    entry_latency_seconds: int,
    exit_latency_seconds: int,
    window_seconds: int,
    size_sol: float,
    cost_model: CostModel,
) -> tuple[str, float | None, float | None]:
    """Picks the EXIT_RULE_IDS entry with the highest mean net return on the
    TRAIN split only. Returns (rule_id, mean_net_return_pct, profit_factor)."""

    best_rule_id = EXIT_RULE_IDS[0]
    best_mean = None
    best_pf = None
    for rule_id in EXIT_RULE_IDS:
        returns = _net_returns_for_rule(
            train_signals,
            rule_id=rule_id,
            entry_latency_seconds=entry_latency_seconds,
            exit_latency_seconds=exit_latency_seconds,
            window_seconds=window_seconds,
            size_sol=size_sol,
            cost_model=cost_model,
        )
        if not returns:
            continue
        mean_return = sum(returns) / len(returns)
        if best_mean is None or mean_return > best_mean:
            best_mean = mean_return
            best_pf = _profit_factor(returns)
            best_rule_id = rule_id
    return best_rule_id, best_mean, best_pf


@dataclass(frozen=True)
class DeltaResult:
    entry_latency_seconds: int
    exit_latency_seconds: int
    selected_exit_rule_id: str
    train_mean_net_return_pct: float | None
    train_profit_factor: float | None
    train_n: int
    holdout_mean_net_return_pct: float | None
    holdout_profit_factor: float | None
    holdout_n: int
    train_barrier_up_pct: float | None
    holdout_barrier_up_pct: float | None
    baseline_barrier_up_pct_train: float | None
    baseline_barrier_up_pct_holdout: float | None


@dataclass(frozen=True)
class DiscoveryRunResult:
    version: str
    input_sha256: str
    n_signals: int
    n_train: int
    n_holdout: int
    by_family: dict[str, list[DeltaResult]]


def _barrier_up_rate(
    signals: Sequence[DiscoverySignalInput],
    *,
    entry_latency_seconds: int,
    window_seconds: int,
    target_pct: float,
    stop_pct: float,
    size_sol: float,
    cost_model: CostModel,
) -> float | None:
    touches = []
    for item in signals:
        entry = find_causal_entry(
            item.trades,
            signal_time=item.signal_time,
            entry_latency_seconds=entry_latency_seconds,
            size_sol=size_sol,
            cost_model=cost_model,
        )
        if entry.trade_chain_time is None or entry.execution_price_sol is None:
            continue
        touch = first_barrier_touch(
            item.trades,
            entry_chain_time=entry.trade_chain_time,
            entry_execution_price_sol=entry.execution_price_sol,
            window_seconds=window_seconds,
            target_pct=target_pct,
            stop_pct=stop_pct,
        )
        touches.append(touch)
    if not touches:
        return None
    return 100.0 * sum(1 for t in touches if t == "UP") / len(touches)


def _baseline_barrier_up_rate(
    signals: Sequence[DiscoverySignalInput],
    *,
    entry_latency_seconds: int,
    window_seconds: int,
    target_pct: float,
    stop_pct: float,
    size_sol: float,
    cost_model: CostModel,
    k_baseline: int,
    seed: int,
) -> float | None:
    touches = []
    for item in signals:
        paired = build_paired_baseline(
            item.baseline_pool,
            item.baseline_trades_by_mint,
            signal_token_mint=item.signal_token_mint,
            signal_venue=item.venue,
            signal_time=item.signal_time,
            signal_age_seconds=item.age_seconds,
            entry_latency_seconds=entry_latency_seconds,
            size_sol=size_sol,
            cost_model=cost_model,
            age_tolerance_seconds=max(1, item.age_seconds // 4) if item.age_seconds else 60,
            min_activity_count=0,
            k=k_baseline,
            seed=seed,
        )
        for token_metrics in paired.token_metrics:
            entry: CausalEntry = token_metrics.entry
            if entry.trade_chain_time is None or entry.execution_price_sol is None:
                continue
            touch = first_barrier_touch(
                item.baseline_trades_by_mint.get(token_metrics.token_mint, ()),
                entry_chain_time=entry.trade_chain_time,
                entry_execution_price_sol=entry.execution_price_sol,
                window_seconds=window_seconds,
                target_pct=target_pct,
                stop_pct=stop_pct,
            )
            touches.append(touch)
    if not touches:
        return None
    return 100.0 * sum(1 for t in touches if t == "UP") / len(touches)


def run_discovery_v0(
    signal_inputs: Sequence[DiscoverySignalInput],
    *,
    cost_model: CostModel,
    manifest_path: Path,
    output_path: Path,
    entry_latency_grid_seconds: Sequence[int] = DEFAULT_ENTRY_LATENCY_GRID_SECONDS,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    target_pct: float = DEFAULT_TARGET_PCT,
    stop_pct: float = DEFAULT_STOP_PCT,
    size_sol: float = 0.01,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    k_baseline: int = 5,
    seed: int = 20261008,
    stall_guard_seconds: int = DEFAULT_STALL_GUARD_SECONDS,
) -> DiscoveryRunResult:
    if not signal_inputs:
        raise ValueError("signal_inputs cannot be empty")
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout_fraction must be between 0 and 1")

    with StallGuard(stall_guard_seconds, label="freeze_input_snapshot"):
        input_sha256 = freeze_input_snapshot(signal_inputs, manifest_path=manifest_path)

    families: dict[str, list[DiscoverySignalInput]] = {}
    for item in signal_inputs:
        families.setdefault(item.family_id, []).append(item)

    by_family: dict[str, list[DeltaResult]] = {}
    n_train_total = n_holdout_total = 0

    with StallGuard(stall_guard_seconds, label="run_discovery_v0_sweep"):
        for family_id, items in families.items():
            ordered = sorted(items, key=lambda i: i.signal_time)
            split_index = max(1, int(len(ordered) * (1 - holdout_fraction)))
            train = ordered[:split_index]
            holdout = ordered[split_index:]
            n_train_total += len(train)
            n_holdout_total += len(holdout)

            deltas: list[DeltaResult] = []
            for entry_latency_seconds in entry_latency_grid_seconds:
                exit_latency_seconds = entry_latency_seconds
                rule_id, train_mean, train_pf = select_best_exit_rule(
                    train,
                    entry_latency_seconds=entry_latency_seconds,
                    exit_latency_seconds=exit_latency_seconds,
                    window_seconds=window_seconds,
                    size_sol=size_sol,
                    cost_model=cost_model,
                )
                holdout_returns = _net_returns_for_rule(
                    holdout,
                    rule_id=rule_id,
                    entry_latency_seconds=entry_latency_seconds,
                    exit_latency_seconds=exit_latency_seconds,
                    window_seconds=window_seconds,
                    size_sol=size_sol,
                    cost_model=cost_model,
                )
                holdout_mean = sum(holdout_returns) / len(holdout_returns) if holdout_returns else None
                holdout_pf = _profit_factor(holdout_returns) if holdout_returns else None

                train_up = _barrier_up_rate(
                    train,
                    entry_latency_seconds=entry_latency_seconds,
                    window_seconds=window_seconds,
                    target_pct=target_pct,
                    stop_pct=stop_pct,
                    size_sol=size_sol,
                    cost_model=cost_model,
                )
                holdout_up = _barrier_up_rate(
                    holdout,
                    entry_latency_seconds=entry_latency_seconds,
                    window_seconds=window_seconds,
                    target_pct=target_pct,
                    stop_pct=stop_pct,
                    size_sol=size_sol,
                    cost_model=cost_model,
                )
                baseline_train_up = _baseline_barrier_up_rate(
                    train,
                    entry_latency_seconds=entry_latency_seconds,
                    window_seconds=window_seconds,
                    target_pct=target_pct,
                    stop_pct=stop_pct,
                    size_sol=size_sol,
                    cost_model=cost_model,
                    k_baseline=k_baseline,
                    seed=seed,
                )
                baseline_holdout_up = _baseline_barrier_up_rate(
                    holdout,
                    entry_latency_seconds=entry_latency_seconds,
                    window_seconds=window_seconds,
                    target_pct=target_pct,
                    stop_pct=stop_pct,
                    size_sol=size_sol,
                    cost_model=cost_model,
                    k_baseline=k_baseline,
                    seed=seed,
                )

                deltas.append(
                    DeltaResult(
                        entry_latency_seconds=entry_latency_seconds,
                        exit_latency_seconds=exit_latency_seconds,
                        selected_exit_rule_id=rule_id,
                        train_mean_net_return_pct=train_mean,
                        train_profit_factor=train_pf,
                        train_n=len(train),
                        holdout_mean_net_return_pct=holdout_mean,
                        holdout_profit_factor=holdout_pf,
                        holdout_n=len(holdout),
                        train_barrier_up_pct=train_up,
                        holdout_barrier_up_pct=holdout_up,
                        baseline_barrier_up_pct_train=baseline_train_up,
                        baseline_barrier_up_pct_holdout=baseline_holdout_up,
                    )
                )
            by_family[family_id] = deltas

    result = DiscoveryRunResult(
        version=VERSION,
        input_sha256=input_sha256,
        n_signals=len(signal_inputs),
        n_train=n_train_total,
        n_holdout=n_holdout_total,
        by_family=by_family,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "version": result.version,
                "input_sha256": result.input_sha256,
                "n_signals": result.n_signals,
                "n_train": result.n_train,
                "n_holdout": result.n_holdout,
                "by_family": {
                    family_id: [asdict(d) for d in deltas]
                    for family_id, deltas in result.by_family.items()
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return result


def _synthetic_trade(chain_time: int, price_sol: float, *, venue: str = "pump_bonding_curve") -> PathTrade:
    base_decimals, quote_decimals, liquidity = 6, 9, 1_000_000_000.0
    return PathTrade(
        chain_time=chain_time,
        venue=venue,
        base_amount_raw=10**base_decimals,
        quote_amount_raw=int(price_sol * 10**quote_decimals),
        base_reserves_raw=int(liquidity * 10**base_decimals),
        quote_reserves_raw=int(price_sol * liquidity * 10**quote_decimals),
    )


def _self_check() -> None:
    free_cost_model = CostModel(venue_fee_pct=0.0, terminal_fee_pct=0.0)
    signals = []
    for i in range(6):
        base_time = 1_000 + i * 10_000
        trades = [
            _synthetic_trade(base_time - 10, 0.0001),
            _synthetic_trade(base_time + 5, 0.0001),
            _synthetic_trade(base_time + 50, 0.00016 if i % 2 == 0 else 0.00006),
            _synthetic_trade(base_time + 200, 0.00018 if i % 2 == 0 else 0.00004),
        ]
        pool = [
            TokenCandidate(
                token_mint=f"BASE_{i}_{j}",
                venue="pump_bonding_curve",
                age_seconds_at_signal=100,
                recent_activity_count=10,
            )
            for j in range(5)
        ]
        baseline_trades = {
            candidate.token_mint: (
                _synthetic_trade(base_time + 5, 0.0001),
                _synthetic_trade(base_time + 60, 0.000102),
            )
            for candidate in pool
        }
        signals.append(
            DiscoverySignalInput(
                signal_token_mint=f"SIGNAL_{i}",
                family_id="SELF_CHECK_FAMILY",
                signal_time=base_time,
                venue="pump_bonding_curve",
                age_seconds=100,
                trades=tuple(trades),
                baseline_pool=tuple(pool),
                baseline_trades_by_mint=baseline_trades,
            )
        )

    with tempfile.TemporaryDirectory() as tmp:
        manifest_path = Path(tmp) / "manifest.json"
        output_path = Path(tmp) / "result.json"
        result = run_discovery_v0(
            signals,
            cost_model=free_cost_model,
            manifest_path=manifest_path,
            output_path=output_path,
            entry_latency_grid_seconds=(5, 30),
            window_seconds=300,
            size_sol=0.01,
            holdout_fraction=0.34,
            k_baseline=3,
            seed=1,
            stall_guard_seconds=30,
        )
        assert manifest_path.exists(), "hash manifest must be written before any metric"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["sha256"] == result.input_sha256
        assert output_path.exists()
        assert result.n_signals == 6
        assert result.n_train + result.n_holdout == 6
        assert "SELF_CHECK_FAMILY" in result.by_family
        deltas = result.by_family["SELF_CHECK_FAMILY"]
        assert len(deltas) == 2
        for delta in deltas:
            assert delta.selected_exit_rule_id in EXIT_RULE_IDS

    print("self-check OK: input_sha256=", result.input_sha256[:16], "...")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SIG-FAST-DISC-V0 discovery engine. NOT authorized to run against "
            "real data before operator sign-off of the RASCUNHO preregistration."
        )
    )
    parser.add_argument("--input", type=Path, help="JSON file with pre-assembled DiscoverySignalInput rows")
    parser.add_argument("--manifest-output", type=Path, default=Path("sig_fast_disc_v0_manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("sig_fast_disc_v0_result.json"))
    parser.add_argument("--stall-guard-seconds", type=int, default=DEFAULT_STALL_GUARD_SECONDS)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0

    parser.error(
        "No --input loader is wired yet (depends on F5 sign-off decisions). "
        "Use --self-check to exercise this engine against synthetic data."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
