# Research State Ledger — Claude Migration — 2026-09-27

This ledger is a compact index. Exact protocols/results remain authoritative.

## Status vocabulary

- `PASS`: passed the exact gate defined by its protocol
- `FAIL`: failed a defined gate
- `KILL`: frozen candidate closed; do not retune on consumed data
- `INCONCLUSIVE`: no positive/negative scientific verdict beyond the exact reason
- `CLOSED_BURNED`: consumed sample/protocol cannot be rerun as the same experiment
- `NOT_EVALUATED`: no valid economic verdict exists
- `BLOCKED`: release/readiness condition not satisfied

## Systems / architecture

### Historical V9 systems profile

Status:
`PASS 11/11`

Known recorded metrics in `PROJECT_CONTEXT.md`:

- PumpSwap p95 3.151s
- Pump p95 1.478s
- coverage 99.6%
- backlog 0.408%

Interpretation:
accepted historical systems evidence only.

### Rust Signal Plane migration / V7 contract

Authority branch:
`research/rust-signal-plane-live-shadow-v0`

Key commits:

- `013ffbde...` promote V7 live evidence contract
- `b01c9f47...` freeze V7 promotion contract

Migration rule:
hot-path changes require new systems evidence.

A prior handoff reported the V7 final-head 1800s soak as PASS. That exact report artifact was not independently located during this remote migration pass, so Claude must treat the statement as **known handoff state requiring artifact confirmation if the exact metrics matter**.

### Research Plane role-normalized capacity

Status:
`CORRECTION FROZEN`

Authority:
`docs/role-normalized-research-plane-capacity-incident-2026-09-24.md`

Root cause:
Research Plane queue overflow after corrected PumpSwap opportunity-role normalization increased real opportunity-token cardinality.

Correction:

- 4096 -> 16384 queue capacity
- 60s -> 120s drain timeout
- overflow remains hard FAIL
- sequence mismatch after loss is consequential
- no Signal Plane backpressure

Later Participant Quality holdout H1/H2 both passed the Signal Plane -> Research Plane -> route-research bridge, which is verified downstream evidence of a functioning corrected path for those cohorts.

## Economic / scientific ledger

### V48 — Flow60 event count

Status:
`FAIL / CLOSED`

Do not retune bins/horizon from its consumed sample.

### V55 — causal Flow60 discovery

Status:
`COMPLETE / CLEAN`

Selected rank #1:

- `flow60_buy_share_pct`
- LOW <= 57.1429
- MID <= 65.7143
- HIGH > 65.7143
- favorable LOW
- opposite HIGH

V55 sample:
discovery-only, burned for V68 validation.

### V68 — prospective Flow60 buy-share

Status:
`NOT_EVALUATED economically`

Frozen primary:

- same feature/cutpoints/direction
- 900s primary
- support requirements frozen
- no MID rescue
- no horizon substitution
- no new bins
- no same-sample feature switch

Systems aborts do not create an economic verdict.

#### Promotion evidence progress (2026-09-28)

`V68_SIGNAL_PLANE_PROMOTION_AUTHORIZED` remains `False` in `route_research_v68_release.py`. Of the 8 sequential promotion-evidence steps in `docs/v68-signal-plane-migration-v0-2026-09-22.md`, step 1 has fresh evidence:

- step 1 (offline Rust -> episode-identity bridge audit): `PASS_V68_SIGNAL_PLANE_BRIDGE_V0`
- authority: `benchmarks/v68_signal_plane_bridge_v0/run.py`, run 2026-09-28, synthetic trace, seed=68, events=10000
- result: 100% Rust/Python trigger parity (10000/10000), 7783 triggers bridged with 0 failures (4588 Pump, 3195 PumpSwap), frozen bridge version confirmed
- this is systems-only and offline; per the audit's own `interpretation` field it does **not** prove live sustained capacity and does **not** authorize V68

Step 2 also has fresh live evidence (2026-09-28, operator-authorized network access, public `api.mainnet.solana.com`):

- precondition (PumpSwap identity bootstrap, `benchmarks/pumpswap_identity_bootstrap_v0/bootstrap.py`, 60s live warmup): `PASS_PUMPSWAP_IDENTITY_BOOTSTRAP_V0`, `valid_bootstrap=true`, 478 decoded PumpSwap pool identities, 0 unresolved, all gates true
  - artifact: `artifacts/pumpswap_identity_bootstrap_v0/pumpswap_identity_bootstrap_v0-1790620104-ba9141edcb06/report.json`
- step 2 (V5 120s live smoke, `benchmarks/integrated_market_signal_plane_v1/live_shadow.py`): `PASS_RUST_SIGNAL_PLANE_LIVE_SHADOW_V7_RUST_HOTPATH`
  - artifact: `artifacts/rust_signal_plane_live_shadow_v7/report.json`
  - trigger parity 100% (44780/44780, 0 mismatches), all 28 systems gates true, zero ingress drops, zero transport errors, `errors: []`
  - `scientific_thresholds_modified: false`, `economic_hypothesis_modified: false`
  - per the report's own `interpretation` field and `authorization: "systems_shadow_only_no_v68_no_economic_verdict"`: this is hot-path/transport evidence only and does **not** establish economic edge or authorize a fresh V68 key by itself
- steps 3-8 (sustained soak beyond 120s, Research Plane bridge smoke, feature-clock reconstruction check, hazard/Jupiter callback wiring, non-V68 end-to-end run, fresh V68 key authorization) remain undone

No economic verdict exists or is any closer to existing from these systems steps alone.

### Native Participant Quality Selection Edge V1

Status:
`KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`

Authority:
`docs/native-participant-quality-holdout-v1-result-2026-09-24.md`

Support gates:
passed.

Positive descriptive findings included:

- HIGH median > LOW median in aggregate/H1/H2
- much lower HIGH catastrophic-loss rate

Frozen failure:
HIGH profit factor did not exceed LOW profit factor.

Disposition:

- CLOSED / KILL exact selector
- no H3
- no cutoff change
- no direction flip
- no horizon rescue
- no live score integration

Possible future tail-risk/rejection research requires a new protocol and independent evidence.

### Concentration Decay V0

Authority branch:
`research/post-transition-pullback-reacceleration-v0`

Frozen rule:
`mf_top_wallet_gross_share_delta_pct_points_late_minus_early <= 0`

Discovery:
`ITERATE`

Fresh confirmation:
`INCONCLUSIVE_CONCENTRATION_DECAY_CONFIRMATION_SUPPORT`

Reason:
candidate route-usable n=9, minimum frozen support=10.

Disposition:

- no second ITERATE
- no threshold movement
- no direction flip
- no subgroup rescue
- independent replication not armed
- no positive edge claim

### Post-Transition Pullback / Reacceleration V0

Authority branch:
`research/post-transition-pullback-reacceleration-v0`

Core causal path:

`Pump birth -> later PumpSwap transition -> pullback/recovery dynamics -> transition+30s immutable decision snapshot -> future route labels`

Important constraints:

- no fake graduation claim from CreatePool
- no ambiguous reference pair
- no lookahead extrema
- no backfill of birth availability
- same-second unresolved local lineage fails closed
- structural reacceleration diagnostic only

### Post-Transition Fresh Economic Discovery V0

Status:
`CLOSED_BURNED`

Closure artifact:
`benchmarks/post_transition_reacceleration_v0/fresh_economic_discovery_v0.closed.json`

Classification:
`FAIL_POST_TRANSITION_FRESH_ECONOMIC_DISCOVERY_V0`

Facts:

- economic provider calls opened
- episodes=2
- conditional economic n=0
- replacement run not authorized
- no Fixed+60 / Fixed+300 / TP / Market Path result available

Future semantic finding:
Jupiter signed finite `priceImpact` must not be treated as missing merely because it is negative.

Future maximum-impact evaluation:
`abs(priceImpact) <= frozen_limit`

This is not a rescue:
the two burned magnitudes (~2.512pp and ~87.611pp) exceed the frozen 2pp maximum anyway.

Future work:
new frozen protocol revision, not V0 rerun.

## Execution maturity

Current state:

- route research: available in defined research paths
- funded BUY: blocked/not released
- landing/fill: not released
- shadow execution: not released
- live money: not authorized

No agent may infer execution maturity from signal quality.

## Evidence hygiene

When adding a future row to this ledger:

1. link exact protocol/result file;
2. use the protocol's exact verdict;
3. distinguish formal verdict from descriptive diagnostics;
4. mark consumed samples;
5. state whether rerun is allowed;
6. state what the result does **not** authorize.
