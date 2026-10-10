# Live paper signal log v0 — spec (RESERVE 1, self-check only)

## Status

SELF-CHECK ONLY. No live wiring, no RPC listener, no network call, no private
key, no order. This closes RESERVE task 1 from the autonomous mandate
("spec+codigo do paper ao vivo (self-check only)") after H2's discovery block
came back `INCONCLUSIVE_SYSTEM` (`docs/sig-fast-h2-RESULTADO-2026-10-10.md`).

## Where this sits in the roadmap

`docs/signal-first-human-execution-roadmap-2026-09-08.md`'s stage 3:

> the bot logs real-time signals and measures the outcome WITHOUT trading.

This is lighter than Shadow Execution (stage 5, `docs/shadow-execution-v1.md`
/ `src/shadow_execution_store.py`), which audits a *frozen candidate
strategy*'s intended fills. Here there is no frozen strategy to promote yet
(H2 is still open) — the only job is: record what a signal looked like the
moment it fired, then later record what actually happened to price, so that
a future hypothesis has a prospective (not retrospective) record to validate
against.

## Design

`benchmarks/sig_fast_v0/live_paper_log_v0.py` adds two append-only SQLite
tables via the existing `src.database.connection()`:

- `sig_fast_live_paper_signal_v0` — one row per signal, written at detection
  time, before any outcome exists. Freezes `config_json` (entry/exit
  latency, window, size, exit rule, cost model) and `context_json` (whatever
  evidence the detector saw as of `decision_as_of`). Same anti-tamper
  discipline as `shadow_execution_store.start_shadow_run`: replaying the same
  `signal_id` with different content raises, it is never silently
  reconfigured. `decision_as_of < detected_at` is rejected (no lookahead).
- `sig_fast_live_paper_outcome_v0` — one row per signal, written later, via
  `evaluate_paper_signal_outcome`, a pure function that only calls the
  existing causal primitives in `src/opportunity_path_metrics_v0.py`
  (`find_causal_entry`, `first_barrier_touch`, `simulate_exit`) against
  whatever trades have actually been observed by `measured_at`. The first
  persisted outcome is canonical (systems invariant 7) — a later call for the
  same `signal_id` is ignored, never overwritten, even if given a longer
  trade history.

Missingness stays explicit: if no trade exists yet at/after the entry or
exit latency, the outcome records F2's own `missing_reason` string, never a
zero or an invented return.

## Explicitly out of scope here

- No code listens to a live feed, Signal Plane output, or RPC in this file.
  There is no "run live" mode — only `--self-check`, which only uses
  synthetic, in-memory `PathTrade` fixtures.
- No position, PnL ledger, or execution engine. Measuring path outcome is not
  holding or selling anything.
- No decision about which detector/strategy produces the `signal_id` this
  logs — that is whichever hypothesis (H1, H2, or a future one) eventually
  reaches `VALIDADA`. This module is strategy-agnostic by design.
- Wiring a real detector feed into `record_signal` and a periodic
  `evaluate_paper_signal_outcome` sweep into `record_outcome` is future work
  that needs its own authorization once there is a validated signal to feed
  it (per CLAUDE.md's execution-automation path); this spec only prepares
  the audit-trail contract that stage would write to.

## Self-check coverage

`python -m benchmarks.sig_fast_v0.live_paper_log_v0 --self-check` proves:

1. a signal is frozen on first write and idempotent on replay; a content
   change on replay raises; lookahead (`decision_as_of < detected_at`)
   raises.
2. `evaluate_paper_signal_outcome` correctly wires synthetic trades through
   F2's entry/barrier/exit primitives (a token that touches the barrier
   `UP`, net return computed and positive, fees correctly applied) — this is
   the same price-path wiring already proven for the historical H2 pipeline
   in `h2_discovery_evaluation_v0.py`'s self-check.
3. the first persisted outcome for a signal_id is canonical: a second,
   later measurement with more trade history is recorded as ignored, and the
   original value is unchanged on reload.
4. missing data is explicit, never fabricated: zero trades yields
   `NOT_AVAILABLE` / `no_trade_at_or_after_entry_time`, never a return; an
   outcome timestamped before its own signal's `decision_as_of`, or
   referencing an unknown `signal_id`, is rejected.
