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
Step 3 (sustained soak) first attempt FAILED with real evidence (2026-09-28):

- attempt 1, 600s: `FAIL_RUST_SIGNAL_PLANE_LIVE_SHADOW_V7_RUST_HOTPATH`
  - artifact: `artifacts/rust_signal_plane_live_shadow_v7/soak-600s-report.json`
  - root cause: `transport:pump_logs:ConnectionClosedError:no close frame received or sent` — the Pump WSS reader dropped uncleanly before `pump_reader_duration_elapsed`; the PumpSwap reader completed the full 600s cleanly
  - trigger parity remained 100% (187670/187670) for everything captured before the drop — no accounting corruption, the system correctly failed closed on the transport loss rather than masking it
  - this matches the risk already flagged in `V68_PROMOTION_READINESS_PLAN_2026-09-28.md`: the public `api.mainnet.solana.com` endpoint may not hold a stable `logsSubscribe` session for sustained windows
- attempt 2 (retry, same parameters, 600s): also `FAIL_RUST_SIGNAL_PLANE_LIVE_SHADOW_V7_RUST_HOTPATH`, but a **different** failure mode
  - artifact: `artifacts/rust_signal_plane_live_shadow_v7/soak-600s-retry-report.json`
  - both WSS readers completed their full duration cleanly this time (no transport error)
  - failed gate: `identity_plane_no_rpc_batch_failure` — 17 of ~865 PumpSwap identity RPC batches returned `SolanaRPCError` (1136/1160 pools still resolved via retry/backoff internal to the async identity plane; the gate has zero tolerance)
  - trigger parity remained 100% (195664/195664) both times
- attempt 3 (2026-09-29, different provider: `solana-rpc.publicnode.com`, no signup required, operator was blocked from reaching Helius by a persistent local/network proxy issue outside this session's control): also `FAIL_RUST_SIGNAL_PLANE_LIVE_SHADOW_V7_RUST_HOTPATH`
  - artifact: `artifacts/rust_signal_plane_live_shadow_v7/soak-600s-publicnode-report.json`
  - failed gate: `identity_plane_no_rpc_batch_failure` — 6 batches returned `SolanaRPCError`, only 470/593 pools resolved (79%, worse resolution rate than attempt 2's 98% on the official public endpoint)
  - trigger parity remained 100% (20890/20890)
- conclusion: three attempts across two different free/public RPC endpoints, three failure instances, same root cause class — no free-tier Solana RPC has held up under this system's sustained (600s) identity-resolution request volume. This is confirmed to be a provider-capacity ceiling, not specific to one vendor and not a code defect (`trigger_parity_100` and hot-path accounting passed in every attempt). A dedicated/paid RPC provider remains the only realistic path for step 3 to pass; further blind retries on free endpoints are not expected to change this.
- attempt 4 (2026-09-29, dedicated Helius RPC, operator-provided key): `PASS_RUST_SIGNAL_PLANE_LIVE_SHADOW_V7_RUST_HOTPATH`
  - fresh bootstrap precondition also re-run on Helius: `PASS_PUMPSWAP_IDENTITY_BOOTSTRAP_V0`, `valid_bootstrap=true`
    - artifact: `artifacts/pumpswap_identity_bootstrap_v0/pumpswap_identity_bootstrap_v0-1790709878-7fc8e4ca10f8/report.json`
  - artifact: `artifacts/rust_signal_plane_live_shadow_v7/soak-600s-helius-report.json`
  - trigger parity 100% (213021/213021, 0 mismatches), all 29 systems gates true, `pump_ingress_drops: 0`, `pumpswap_ingress_drops: 0`, `reader_errors: []`, `errors: []`
  - `scientific_thresholds_modified: false`, `economic_hypothesis_modified: false`
  - confirms the attempt 1-3 conclusion: this was purely a free-RPC capacity ceiling, not a code defect — the identical hot path passes cleanly once given a dedicated provider
  - **Step 3 is now DONE.** Steps 4-8 remain, and step 4 additionally needs `JUPITER_API_KEY` (now configured, see Participant Quality section below for its own live confirmation).
- step 4 (V5 Research Plane bridge smoke, 2026-09-29, Helius RPC, non-V68 run key `v68-promotion-step4-20260929-01`, 120s): `PASS_RUST_SIGNAL_PLANE_LIVE_SHADOW_V7_RUST_HOTPATH`
  - artifact: `artifacts/rust_signal_plane_live_shadow_v7/step4-research-plane-bridge-report.json`
  - all 36 systems gates true (includes `research_plane_new_admission_observed: true`, `research_plane_no_errors: true`, `research_plane_no_queue_overflow: true`), trigger parity 100%, `errors: []`
  - `research_plane_new_admissions: 273` (>=1 required), `scientific_thresholds_modified: false`, `economic_hypothesis_modified: false`
  - **Step 4 is now DONE.**
- step 5 (verify persisted Research Plane reconstructs frozen V55/V68 causal features without feature-clock violations, 2026-09-29): DONE via two checks, no new live network
  - existing offline mechanism test: `python -m unittest tests.test_signal_plane_v68_feature_bridge_v0 -v` -> `OK` (1 test) — synthetic trace, exact reconstruction of `flow60_buy_share_pct` and frozen V68 LOW/HIGH boundary from a persisted Research Plane record
  - real-data spot check (ad hoc, scratchpad-only, not committed) against step 4's actual persisted episodes (`acquisition_run_key='v68-promotion-step4-20260929-01'`): sampled 5 real admitted episodes, rebuilt each enrichment bundle at its own `decision_as_of`/`first_trigger_observed_at`, derived V55/V68 features successfully for all 5, `chain_as_of <= as_of` held for all 5 (0 clock violations), varied real `flow60_buy_share_pct` values (100.0, 100.0, 100.0, 66.67, 85.71) confirming the feature is actually being computed from real per-episode data, not a constant
  - **Step 5 is now DONE.**
- steps 6-7 (attach hazard/Jupiter/forward-outcome workers to the injected admission callback; systems-only end-to-end run with a non-V68 run key): discovered this wiring **already exists** as `route_research_signal_plane_bridge_v0.py` — it wires `SignalPlaneRouteResearchCoordinatorV0.admit_episode` into `run_live_shadow_v0`'s `research_plane_admit_episode_fn` injection point, refuses any run key containing `v68-flow60-fresh` unless `allow_v68_fresh_run_key=True` (default False), and its own `checks` dict already includes `research_decision_clock_violations_zero` and `research_schedule_violations_zero`. No new wiring code was needed. Ran it live with a non-V68 run key (`v68-promotion-step6-7-20260929-01`); result logged below once complete.
- steps 4-8 (Research Plane bridge smoke, feature-clock reconstruction check, hazard/Jupiter callback wiring, non-V68 end-to-end run, fresh V68 key authorization) remain undone

No economic verdict exists or is any closer to existing from these systems steps alone.

### Native Participant Quality Tail-Risk Rejection V0 (new preregistration, in progress)

Per `docs/participant-quality-tail-risk-rejection-v0-preregistration-2026-09-28.md`, operator-approved 2026-09-29.

- fresh memory build (`participant_quality_native_memory_v1.py`, base key `participant-quality-tail-risk-v0-20260929-01`, JUPITER_API_KEY now configured): `READY_TO_PREREGISTER_NATIVE_PARTICIPANT_QUALITY_HOLDOUT`
  - all 4 cohorts (M1-M4) passed bridge + forward-900 maturity
  - fresh outcome-blind cutoff: `-86.0484432047999`, favorable direction HIGH, M2-M4 available=76, M4 coverage=80.0%
  - artifact: `artifacts/participant_quality_native_memory_v1/participant-quality-tail-risk-v0-20260929-01-report.json`
- integration error found and fixed before any holdout data was consumed: `participant_quality_native_holdout_v1.py` hard-codes the **closed KILL selector's** own frozen `MEMORY_RUN_KEYS` (2026-09-24 rolefix memory) and `FROZEN_CUTOFF` (-65.65...), and fails closed (`ValueError: memory run keys do not match preregistration`) on any other memory — correct behavior, protecting the old closed result from silent substitution. Reusing that script unmodified for this new preregistration was a planning mistake on my part.
  - fix: added `participant_quality_tail_risk_holdout_v0.py`, a thin wrapper that imports `participant_quality_native_holdout_v1` and overrides only `MEMORY_RUN_KEYS`/`FROZEN_CUTOFF`/`VERSION` to this preregistration's own fresh values before calling its unmodified `run_holdout()`. The closed selector's script and frozen constants were not edited.
- holdout attempt 1 (base key `...-01`): `INCONCLUSIVE_NATIVE_PARTICIPANT_QUALITY_HOLDOUT_ACQUISITION` — H1 acquired cleanly (40 decisions), H2 failed with `identity_plane_no_rpc_batch_failure` (same free-RPC capacity ceiling seen in the V68 soak attempts, this time surfacing even at 120s). Not a scientific result; per protocol, an acquisition failure produces INCONCLUSIVE and authorizes no threshold changes. Retrying with a fresh base key rather than partially recovering H1.
- holdout attempt 2 (base key `...-02`): also `INCONCLUSIVE_NATIVE_PARTICIPANT_QUALITY_HOLDOUT_ACQUISITION` — H1 clean again, H2 failed again on `identity_plane_no_rpc_batch_failure`, but marginally (604/605 pools resolved, 1 stray `SolanaRPCError`). Same root cause as everywhere else today; H2 consistently the one to fail, consistent with cumulative rate pressure from running two cohorts back-to-back on a free endpoint.
- holdout attempt 3 (base key `...-03`): also `INCONCLUSIVE_NATIVE_PARTICIPANT_QUALITY_HOLDOUT_ACQUISITION` — this time H1 failed (previously H1 had passed twice), with both `identity_plane_no_rpc_batch_failure` and a WSS transport reader error. Confirms the failures are not ordering-specific (not "H2 always fails") — it's the free public RPC randomly failing whichever cohort hits it at the wrong moment.
- stopped retrying after 3 consecutive INCONCLUSIVE acquisition attempts (6 total free-RPC failures today counting the V68 soak attempts). No blind 4th retry — same conclusion as the V68 soak: this preregistration's acquisition also needs a dedicated/paid RPC to complete. No scientific result (PASS/FAIL/INCONCLUSIVE-support) exists yet for the tail-risk hypothesis itself; only systems/acquisition attempts have run.
- holdout attempt 4 (2026-09-29, dedicated Helius RPC, base key `...-04`): acquisition succeeded cleanly for the first time — H1 (40 decisions) and H2 (40 decisions) both `PASS_SIGNAL_PLANE_ROUTE_RESEARCH_BRIDGE_V0` / `PASS_MEMORY_FORWARD_300_900_COMPLETE`, lateness p95 = 0 on both
  - artifact: `artifacts/participant_quality_tail_risk_holdout_v0/participant-quality-tail-risk-v0-20260929-04-report.json`
  - note: the printed `classification=KEEP_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE` in that report's own stdout is `participant_quality_native_holdout_v1.py`'s **own** built-in verdict (HIGH-vs-LOW profit-factor gates — the closed selector's question). That is not this preregistration's verdict; the wrapper only reuses its acquisition/rows, not its classifier. Ran the report's raw `rows` through this preregistration's own evaluator (`participant_quality_tail_risk_rejection_v0.py`, LOW-vs-ALL catastrophic-tail gates) for the actual verdict below.
- **Tail-risk rejection evaluator result (first real scientific verdict for this preregistration): `PASS_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0`**
  - artifact: `artifacts/participant_quality_tail_risk_rejection_v0/participant-quality-tail-risk-v0-20260929-04-report.json`
  - support: `low_paired_gte_15=true` (low_n=18), `all_paired_gte_40=true` (all_n=56)
  - LOW catastrophic-loss rate (900s return <= -80%): 88.89%; ALL catastrophic-loss rate: 37.5%; gap = 51.39pp (bar: >=15pp) — gate `low_tail_worse_than_all=true`, `gap_at_least_15pp=true`
  - HIGH-only median return: -27.14%; ALL median return: -58.33% — gate `high_only_median_not_worse_than_all=true` (excluding LOW did not harm the kept group's median; it improved it)
  - all 3 primary gates true -> PASS
  - per preregistration's failure discipline: this run key/sample (`...-04-{H1,H2}`) is now burned, PASS or not — no re-running, no cutoff retune, no materiality-bar change, no switching the contrast back to LOW-vs-HIGH
  - what this PASS proves (per the preregistration's own scope): prospective evidence that the existing, already-built wallet-quality feature can act as a **fail-closed downside-risk skip filter** in a memecoin route-only context (skip LOW-flagged episodes)
  - what this PASS does **not** prove: positive alpha for HIGH, executable slippage/fee-adjusted P&L, landing/fill probability, or any live-money edge; it does **not** reopen, retune, or reinterpret the separately closed `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE` result (that was a HIGH-vs-LOW alpha question on a different contrast and different cutoff)
  - authorization: a PASS here authorizes only a fail-closed skip-gate candidate for a future, separately gated integration decision — not a live entry score, not funded execution

Status (closed selector, unchanged, not reopened by the above):
`KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`

Status (this preregistration, final per single-sample failure discipline):
`PASS_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0`

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
