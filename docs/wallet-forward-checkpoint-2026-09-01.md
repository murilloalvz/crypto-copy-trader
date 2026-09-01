# Wallet Forward + Jupiter — first real forward checkpoint (2026-09-01)

## Scope

Run:

- key: `wallet-forward-1788217626-543a9b6b`
- runtime: `wallet_forward_runtime_v1_unversioned`
- quote mode: `proxy`
- cohort: 7mPti, Gf9X, 3tc4
- observation ids: `(0, 21]`
- nominal duration: ~6h

This run started before the causal-boundary/runtime-v2/v3 changes. It is kept as legacy evidence and is not retroactively relabeled.

## Technical integrity

Post-run audit completed with all steps returning exit code 0.

- forward actions: 21
- BUY / SELL: 13 / 8
- active wallets: 2/3
- observed tokens: 3
- causal integrity: `CAUSAL_BOUNDARY_CLEAN`
- pre-run `observed_at`: 0
- pre-run `chain_time`: 0
- negative lag: 0
- source lag >5m: 0
- source lag p50/p95/max: 37s / 43s / 43s

Therefore this legacy run is usable as a descriptive causal observability sample. This does not promote any strategy or wallet economically.

## Wallet activity

### 7mPti

- 0 forward actions
- 0 BUYs

H1 receives no new evidence from this run.

### Gf9X

- 1 forward action
- 1 BUY
- source lag: 33s

This is far below the frozen H2 sample requirement. No pass/fail is allowed.

### 3tc4

- 20 forward actions
- 12 BUYs / 8 SELLs
- only 2 observed tokens
- source lag p50/p95/max: 37.5s / 43s / 43s

This is operationally useful because the wallet generated real events, but 12 BUY rows across only 2 tokens are not 12 independent market opportunities. H3 still requires broader token/cycle evidence before evaluation.

## Censoring / follow-up exposure

Across the 13 BUYs:

- >=15m follow-up: 13/13 (100%)
- >=1h follow-up: 4/13 (30.8%)
- >=6h follow-up: 0/13
- >=24h follow-up: 0/13

Consequences:

- H1 (`first exit >6h`) cannot be tested by this run.
- A BUY without a SELL before run end cannot be called a long hold unless its required follow-up window was actually observed.
- Future strategy-reconstruction runs need explicit intake vs follow-up handling rather than treating nominal run duration as equal follow-up for every BUY.

## Jupiter quote path

Frozen delays after **our detection**: `0, 15, 30, 60, 120s`.

- expected probes: 65
- attempted: 65
- success: 65
- failures: 0
- missing: 0
- BUYs with all delays attempted: 13/13
- assembled transaction candidates: 0
- proxy / quote-only: 65

This is the first real operational validation of:

```text
public wallet action
-> RPC detection
-> event-scoped Jupiter quote schedule
-> quote persistence
-> causal replay data path
```

in proxy mode.

`CAUSAL_REPLAY_SAMPLE_READY` means only that the data path is complete enough for descriptive causal replay. It does not mean executable fill, edge, copyability, shadow approval or live approval.

## Important latency interpretation

The configured quote delay starts at `wallet_observed_at`, not at the source transaction's `chain_time`.

Therefore `+0s` means:

```text
source swap on-chain
-> RPC/polling detection lag
-> immediate quote request after detection
```

not zero seconds after the source wallet traded.

This run already shows source detection lag of roughly 31–43s. The quote scheduler then added several more seconds on typical +0 requests. Consequently the actual route availability is materially later than the label `+0s` suggests when viewed from source chain time.

A dedicated end-to-end latency audit was added after this checkpoint to report `chain_time -> quote_observed_at` directly.

## Route-price drift

Event-level drift relative to the same BUY's +0 quote:

### All BUYs

- +15s: median +9.62%, p95 +108.36%
- +30s: median -19.76%, p95 +38.48%
- +60s: median -37.64%, p95 +1.81%
- +120s: median -80.58%, p95 +0.24%

Positive drift means worse price for the copier. Negative drift means the delayed route price became cheaper.

### Gf9X

Only one BUY, therefore purely anecdotal:

- +15s: 0.00%
- +30s: +0.19%
- +60s: +0.04%
- +120s: +0.24%

### 3tc4

12 BUY events but only 2 tokens:

- +15s: median +17.04%, p95 +108.36%
- +30s: median -21.98%, p95 +38.48%
- +60s: median -45.84%, p95 +1.81%
- +120s: median -81.16%, p95 -7.09%

The pattern is extreme and non-monotonic. It must not be interpreted as a robust copy rule because repeated BUYs from the same wallet/token create strong dependence. A token-clustered sample-quality audit was added after this run so each token can receive equal descriptive weight instead of treating every event row as independent evidence.

## Multi-wallet convergence

- 13 BUYs
- 3 tokens
- 0 convergence events under the exploratory 300s / >=2-wallet rule

No evidence for multi-wallet confirmation was produced by this run.

## Provider metadata limitation

This legacy run predates persistence of the newer Jupiter fields:

- router
- `priceImpact`
- `slippageBps`
- `swapUsdValue`

Therefore metadata coverage is 0/65 by design. No retroactive values are invented.

## Status decisions

### VALIDATED OPERATIONALLY

- real forward wallet action detection in a long run
- event-scoped Jupiter quote scheduling
- 65/65 proxy quote attempts completed successfully
- quote persistence and descriptive causal replay path
- run-scoped post-run audit

### EM TESTE / NOT VALIDATED ECONOMICALLY

- Gf9X and 3tc4 strategy hypotheses
- copyability after real end-to-end latency
- quote drift generalization across independent tokens
- wallet confirmation edge

### NOT VALIDATED

- assembled transaction route coverage
- signing/submission/landing/fill
- real slippage paid
- live execution
- H1 for 7mPti

## Next technical priorities

1. Use the new end-to-end latency audit so quote delays are interpreted from source chain time correctly.
2. Use token-clustered dependence analysis before treating 3tc4's 12 BUY events as `n=12` economic evidence.
3. Run the next collection with rotating polling order runtime v3 and prospective Jupiter provider metadata.
4. Design explicit intake + follow-up windows for wallet-strategy hypotheses so 6h/24h holding questions are not defeated by right-censoring.
5. Keep all wallet hypotheses frozen; do not retune thresholds from this small sample.
