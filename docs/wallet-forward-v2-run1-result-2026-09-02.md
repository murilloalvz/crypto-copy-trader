# Wallet Forward v2 — Run 1 Result (2026-09-02)

## Status

**CAUSAL REPLAY DATA GATE PASSED / ECONOMIC INTERPRETATION STILL BLOCKED.**

Run: `wallet-forward-1788360461-8a3986f9`

Mode: **RESEARCH / READ ONLY**.

This was the first full 10h forward run using the frozen Wallet Forward Acquisition v2 cohort.

## Protocol

- cohort: 3 frozen wallets
- enrollment: 4h
- follow-up: 6h
- polling interval: 10s
- RPC commitment: `confirmed`
- Jupiter quote delays: 0 / 15 / 30 / 60 / 120s after wallet detection
- copy notional: USDC 25
- quote mode: proxy / quote-only
- runtime: `wallet_forward_runtime_v5_enrollment_followup_rotating_poll_confirmed_commitment`

## Run completion

The manifest reached `COMPLETED` after approximately 10 hours.

- observation scope: `(31, 46]`
- forward actions: 15
- BUYs: 9
- SELLs: 6
- active wallets: 2/3
- observed tokens: 7

The enrollment cutoff froze at observation id 35 after the planned 4h enrollment window.

- enrolled BUYs: 4
- follow-up-only BUYs: 5

Follow-up-only BUYs were excluded from the frozen economic denominator as designed.

## Causal integrity

Post-run integrity gate: `CAUSAL_BOUNDARY_CLEAN`.

- observed before run: 0
- chain time before run: 0
- negative source lag: 0
- source lag >5m: 0
- source lag p50/p95/max: 8s / 28s / 28s
- 100% of observations detected within 30s

No run-scoped RPC FAILURE/RECOVERED telemetry was persisted for this run.

The laptop was accidentally suspended briefly during the collection. The current schema does not persist a per-cycle heartbeat, so absence of a short polling gap cannot be proven. However, no observed action shows backlog/staleness contamination and all source lags remained <=28s.

## Jupiter causal quote path

For all 9 forward BUY events:

- expected probes: 45
- attempted: 45
- success: 45
- failed: 0
- missing: 0
- unexpected: 0
- BUYs with all delays attempted: 9/9

Therefore the project readiness classifier returned:

`CAUSAL_REPLAY_SAMPLE_READY`

This means only that the run has sufficient causal data completeness for descriptive replay. It does **not** validate fill, edge, wallet copyability, shadow execution or live execution.

The run remained quote-only:

- assembled candidate transactions: 0
- proxy quotes: 45

## Finality

Post-run `getSignatureStatuses` audit:

- observations: 15
- unique signatures: 15
- missing signatures: 0
- finalized: 15/15 (100%)
- finalized success: 15
- finalized error: 0
- still confirmed: 0
- processed: 0
- missing: 0

The forward sample therefore persisted cleanly on-chain.

## Sample dependence

The run is technically valid but economically small and concentrated.

- BUY events: 9
- wallets with BUYs: 2
- tokens with BUYs: 6
- wallet×token clusters: 6
- repeated BUY events in the same wallet×token cluster: 3/9 (33.3%)
- largest wallet share: 7/9 BUYs (77.8%)
- largest token share: 3/9 BUYs (33.3%)
- `2RssnB7hcr...`: 0 forward actions

No multi-wallet convergence event was observed.

## Follow-up exposure

All 9 BUYs had enough in-run exposure for 15m and 1h analyses.

- >=15m exposure: 9/9
- >=1h exposure: 9/9
- >=6h exposure: 4/9
- >=24h exposure: 0/9

Long-horizon holding hypotheses therefore remain partially right-censored.

## Economic replay — current implementation

The enrollment-aware economic replay reported:

- full-run actions: 15
- economic actions: 10
- enrolled BUYs: 4
- follow-up-only BUYs excluded: 5
- economic sample label: `DESCRIPTIVE`

Current event-lot matching results using proxy quotes:

| Delay | Closed | Censored | Open | Mean net return |
| ---: | ---: | ---: | ---: | ---: |
| +0s | 1 | 3 | 0 | +0.52% |
| +15s | 1 | 3 | 0 | +1.36% |
| +30s | 0 | 4 | 0 | n/a |
| +60s | 1 | 2 | 1 | +2.97% |
| +120s | 0 | 3 | 1 | n/a |

These returns **must not be interpreted as strategy performance**.

## Quantity-aware replay blocker discovered

The run exposed a structural limitation in the current economic replay.

For token `5TVs...pump`, wallet `3tc4...` produced three enrolled BUY events before a later observed SELL. The persisted inventory evidence shows that the SELL reduced the wallet's accumulated token balance from the full post-BUY inventory to zero (`source_reduction_fraction = 1.0`).

The current replay still models one BUY as one independent lot and one SELL as closing only one FIFO lot. That can leave other BUY lots incorrectly right-censored even when the observed source SELL liquidated the full accumulated position.

Because quantity/inventory semantics are now persisted, economic replay must become quantity-aware before any PnL, win-rate, profit-factor or strategy comparison is trusted.

Required behavior includes:

1. represent each enrolled BUY as a quantity-bearing lot;
2. propagate source inventory reductions into copied position reductions;
3. allow one SELL to close multiple accumulated BUY lots when the source liquidation fraction requires it;
4. support partial liquidation across lots;
5. preserve pre-existing inventory isolation;
6. keep missing quote/censoring semantics explicit;
7. never use follow-up-only BUYs to enlarge the frozen economic denominator.

## Decision

### Passed

- frozen v2 acquisition cohort
- 10h run completion
- enrollment cutoff semantics
- non-zero enrolled forward BUY sample
- causal observation boundary
- BUY event → Jupiter quote path
- quote completeness
- finality
- descriptive causal replay readiness

### Not passed / not claimed

- executable fill validation
- economic edge
- robust PnL inference
- wallet copyability ranking
- shadow readiness
- live readiness

### Next engineering gate

**Implement and test quantity-aware causal economic replay before collecting or interpreting additional economic evidence.**

Do not promote the current positive `n=1` closed-trade returns. They are an artifact of the present event-lot exit matching and are not a valid strategy conclusion.
