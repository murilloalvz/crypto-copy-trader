# Jupiter Executable Quote v31 — Frozen First Integration Protocol

Date: 2026-09-04
Mode: PAPER / RESEARCH / READ ONLY
Prerequisite: Unified Market Latency v30 = FORMAL PASS

## Objective

Validate that a newly admitted market-opportunity episode can receive a causal, route-aware Jupiter entry quote using only information available after episode admission, without signing or submitting a transaction.

This stage validates provider integration/executability evidence only. It does **not** establish economic edge or profitability.

## Frozen cohort

The first live v31 smoke selects the **first 12 newly admitted episodes** in admission order.

- Selection is fixed before seeing quote outcomes.
- Continuation hits are excluded because they are not new admissions.
- Replayed episode admissions are excluded by the idempotent admission store.
- If the run contains fewer than 12 new admissions, all available new admissions are selected and the sample-size limitation is reported; this is not silently expanded using later/historical episodes.

## Frozen quote request

For each selected episode:

- provider: `jupiter_swap_v2_order`
- purpose: `entry_executable_buy_v1`
- input asset: USDC
- input notional: US$25.00
- slippage request: 100 bps
- direction: buy opportunity token
- token decimals: causal `getTokenSupply` lookup/cache
- taker: configured **public Solana address only**
- Jupiter order timeout: 5 seconds
- quote workers: 2

The taker public key is used only so Jupiter may assemble a candidate transaction. The project does not load a private key, sign a transaction, call execute, or submit to Solana.

## Attempt lifecycle

One provider attempt is persisted **before** provider I/O for each `(run, episode, provider, purpose)`.

State starts as:

- `STARTED`

Terminal states are explicit and immutable:

- `AVAILABLE`: a quote was returned and an assembled candidate transaction is present;
- `UNAVAILABLE`: provider quote exists but no assembled candidate transaction is present;
- `CONFIG_MISSING`: required local provider configuration is missing;
- `PROVIDER_ERROR`: Jupiter request/provider failure;
- `METADATA_ERROR`: token metadata/decimals could not be resolved;
- `NORMALIZATION_ERROR`: provider response cannot be converted safely into the causal quote model.

A crash leaving `STARTED` is observable and must be reconciled. It must never be interpreted as `UNAVAILABLE`.

## Causal invariants

1. Jupiter is called only after `admit_opportunity_episode(...)` returns `True` for a newly admitted episode.
2. Continuations and replayed admissions do not cause new Jupiter calls.
3. `quote.observed_at >= episode.first_trigger_observed_at` is mandatory.
4. Missing/error results are never replaced by candles, historical quotes, or later provider values.
5. The quote artifact retains input/output amounts, route identity, router metadata, provider slippage and price-impact metadata when supplied.
6. An `AVAILABLE` result means candidate route assembly only; it is not evidence that a transaction would land successfully.
7. Replay of an already attempted episode reuses persisted attempt evidence rather than silently re-calling the provider.

## v31 first-smoke integration gate

The gate is frozen before the live result.

### PASS — all mandatory

1. The inherited v30 market pipeline still satisfies the 11 frozen Unified Market Latency conditions during the v31 run. Provider work must not break the systems gate that already passed.
2. At least one new episode is selected. If zero new episodes occur, the provider integration result is `INCONCLUSIVE_NO_SAMPLE`, not FAIL/PASS.
3. Provider attempt terminal coverage for selected episodes is 100%; no selected episode remains `STARTED` at the end.
4. `CONFIG_MISSING = 0`.
5. `quote_worker_errors = 0`.
6. `reused_attempts = 0` for the fresh run key. Reuse is valid under replay tests, but the first live smoke must use a fresh run key.
7. At least one selected episode reaches `AVAILABLE` and persists an executable quote artifact. Otherwise candidate executable-route availability has not been demonstrated in live evidence.
8. Every `AVAILABLE` artifact has `executable=True`; every persisted quote satisfies the post-admission clock invariant.
9. Missing/unavailable/error statuses remain explicit; no synthetic substitution or retroactive provider lookup occurs.

### Descriptive only in the first smoke

No arbitrary executable-availability percentage threshold is introduced after seeing the data. Counts of `AVAILABLE`, `UNAVAILABLE`, `PROVIDER_ERROR`, `METADATA_ERROR`, and `NORMALIZATION_ERROR`, plus quote latency, are reported as provider-coverage evidence for the next design step.

## Failure interpretation

- `CONFIG_MISSING > 0`: local setup failure; do not interpret as market/provider failure.
- all selected terminal but zero `AVAILABLE`: executable-route capability not demonstrated; investigate route/provider/taker assumptions before proceeding.
- provider/metadata errors: retain as evidence; inspect error taxonomy and coverage before changing provider policy.
- v30 latency regression: provider path is interfering with the market pipeline; fix isolation/backpressure before continuing.
- dangling `STARTED`: lifecycle/reconciliation bug or interrupted provider I/O; fail closed.

## Next stage after v31 PASS

Proceed to the previously frozen stage 2: minimal token hazard/risk provider with the same explicit attempt/missing/failure semantics. Do not freeze final `decision_as_of` and do not start executable +5m/+15m/+60m outcomes until required providers in the frozen sequence have been attempted.
