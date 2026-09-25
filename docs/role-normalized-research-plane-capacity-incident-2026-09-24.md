# Role-Normalized Research Plane Capacity Incident — 2026-09-24

Mode: SYSTEMS / RESEARCH / NO ECONOMIC VERDICT

## Evidence

After PumpSwap opportunity-asset normalization, a clean Participant Quality V1 acquisition produced:

- 35,714 Signal Plane records;
- 35,639 trade decision points;
- 8,220 Pump adapted trades;
- 27,419 PumpSwap adapted trades;
- 40 selected route-research episodes;
- 40 terminal hazard attempts;
- 40 terminal entry attempts;
- 40 frozen research decisions;
- 120 scheduled route outcomes.

The Signal Plane shadow failed because the bounded Research Plane persistence queue overflowed. Once
records were dropped, later batches necessarily observed sequence gaps. Sequence mismatch is therefore
a consequence of queue loss, not an independent root cause.

## Interpretation

The opportunity-asset correction increased correct PumpSwap token cardinality. Pre-fix reversed pools
could collapse onto a reference mint such as USDC. Post-fix, distinct non-reference opportunity tokens
create more first/out-of-window episode work in the durable Research Plane.

Rust V7 hot-path logic, detector thresholds, and economic hypotheses are unchanged.

## Systems hardening

- Research Plane queue capacity: 4,096 -> 16,384.
- Research Plane drain timeout: 60s -> 120s.
- Queue overflow remains a hard FAIL gate.
- Overflow count remains exact; only the repeated human-readable error string is deduplicated.
- No backpressure is added to the Signal Plane hot path.
- No dropped record is treated as acceptable.

## Validation plan

Before collecting another Participant Quality memory cohort, run a separate systems-only 120-second
Route -> Research Bridge preflight with the corrected opportunity semantics. Require:

- Signal Plane PASS;
- Research Plane attempted = enqueued = completed;
- queue overflow = 0;
- sequence mismatch batches = 0;
- Research Plane errors = 0;
- exact trigger parity;
- downstream 40/40 terminal accounting and 120 scheduled outcomes.

Only after that systems preflight may a new clean Participant Quality V1 memory epoch begin.
