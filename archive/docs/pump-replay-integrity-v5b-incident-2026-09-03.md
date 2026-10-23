# Pump replay integrity incident — v5b — 2026-09-03

## Status

RESOLVED IN CODE / LIVE REVALIDATION PENDING.

Mode remains **PAPER / RESEARCH / READ ONLY**.

## Incident

The first `unified-market-smoke-20260903-05b` capacity stress aborted before SUMMARY with:

```text
ValueError: market trade event already exists with different data
```

The failure originated in `src/pump_batch_persistence.py` while multiple Pump persistence workers processed observations concurrently.

## What the failure means

`pump:{signature}:{event_index}` is the local event key. A later delivery can reuse the same key while presenting a different causal identity. Under `confirmed` commitment, duplicate/replayed deliveries and competing observation order must be treated explicitly rather than silently overwritten.

The old batch path also assumed SQLite completion order matched collector observation order. With multiple workers that assumption is false: a notification observed later can complete persistence before an earlier websocket delivery.

## Frozen causal rule

For the concurrent Pump batch path:

1. `observed_at` is the collector availability clock and is authoritative over SQLite completion order.
2. Exact replay is idempotent.
3. If an exact replay with an earlier `observed_at` completes later, the stored row is corrected to the earlier collector timestamp.
4. If the same signature/index reappears with a different causal identity, both identities are persisted to `pump_replay_conflicts`.
5. Among conflicting deliveries, the identity with the earliest collector `observed_at` is canonical for the market observation row.
6. A later conflicting delivery never overwrites a causally earlier observation.
7. Conflict handling is non-fatal for acquisition; it remains visible and auditable.

This does **not** turn conflicting observations into additional flow events and therefore avoids inflating transaction breadth/activity from replay artifacts.

## Validation

Regression coverage now includes:

- exact replay idempotence;
- later worker completion with earlier collector timestamp;
- conflicting later replay retained only in audit;
- conflicting earlier observation replacing a later-completed canonical row;
- Pump radar bridge compatibility.

CI at commit `8ea590a8dbe8f54de29135c567e17895a3dbbd2e`:

- `python -m compileall -q .`: PASS;
- `python -m unittest discover -s tests -q`: 563 tests, 0 failures.

The v5 smoke wrapper also reports `pump_replay_conflicts` and canonical actions after a completed run.

## Scientific interpretation

The aborted v5b run is **not** a throughput/latency result because it did not reach SUMMARY. It only establishes that replay identity instability exists under the stressed concurrent path and must be handled causally.

No radar thresholds were changed. No economic inference is allowed from this incident.

## Next gate

Repeat the same 120s v5b capacity configuration after syncing the fix:

- Pump workers: 8;
- PumpSwap workers: 24;
- max concurrent PumpSwap resolutions: 18;
- max hydrations: 1500;
- queue size: 5000.

The pre-existing throughput/latency gate remains unchanged.
