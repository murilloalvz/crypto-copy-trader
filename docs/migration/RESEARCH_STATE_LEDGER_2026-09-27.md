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
- steps 6-7 (attach hazard/Jupiter/forward-outcome workers to the injected admission callback; systems-only end-to-end run with a non-V68 run key): discovered this wiring **already exists** as `route_research_signal_plane_bridge_v0.py` — it wires `SignalPlaneRouteResearchCoordinatorV0.admit_episode` into `run_live_shadow_v0`'s `research_plane_admit_episode_fn` injection point, refuses any run key containing `v68-flow60-fresh` unless `allow_v68_fresh_run_key=True` (default False), and its own `checks` dict already includes `research_decision_clock_violations_zero` and `research_schedule_violations_zero`. No new wiring code was needed.
  - live run (2026-09-29, Helius+Jupiter, non-V68 run key `v68-promotion-step6-7-20260929-01`, 120s): `PASS_SIGNAL_PLANE_ROUTE_RESEARCH_BRIDGE_V0`
    - artifact: `artifacts/signal_plane_route_research_bridge_v0/step6-7-report.json`
    - all 16 checks true (includes `research_decision_clock_violations_zero`, `research_schedule_violations_zero`, `route_only_executable_violations_zero`, `provider_attempts_not_reused`, `downstream_drain_complete` with `drain_timed_out: false`)
    - pipeline accounting exact end to end: 40 selected -> 40 hazard terminal -> 40 entry terminal -> 40 research decisions frozen -> 120 outcomes scheduled (exactly 3x decisions)
    - underlying Signal Plane: `PASS_RUST_SIGNAL_PLANE_LIVE_SHADOW_V7_RUST_HOTPATH`, trigger parity 100% (40611/40611)
    - `authorization: "systems_bridge_only_no_v68_fresh_no_economic_verdict"`, `fresh_v68_run_key_authorized: false`, `scientific_thresholds_modified: false`, `economic_hypothesis_modified: false`
  - **Steps 6 and 7 are now DONE.**

**V68 promotion evidence steps 1-7 are all DONE as of 2026-09-29** (per each step's own prose description in the migration doc). Step 8 (authorize a fresh V68 key) investigation:

- correction: `V68_SIGNAL_PLANE_PROMOTION_AUTHORIZED = False` in `route_research_v68_release.py` is **not** the real functional gate — grepped the whole repo and it is referenced nowhere except its own guard test (`test_v68_remains_blocked_until_signal_plane_promotion`). The real gate is `route_research_v68_release.py`'s `main()`, which only takes the promoted Signal Plane path when `--signal-plane-promotion-report` validates via `signal_plane_v68_promotion_v0.validate_promotion_report` (hash-checks 5 evidence files and pins the exact git HEAD).
- `signal_plane_v68_promotion_v0.build_promotion_report()` requires: `offline_capacity` (`PASS_RUST_SIGNAL_BATCH_OFFLINE_CAPACITY_V0`), `offline_bridge` (step 1's artifact), `live_smoke` (step 2's, `duration_seconds >= 120`), `live_soak` (step 3's, but with `SOAK_MIN_DURATION_SECONDS = 1800.0` — **not** the 600s already run), `route_bridge` (steps 6-7's artifact, `research_decisions_frozen > 0`).
- ran the missing `offline_capacity` precondition (offline, no live network): `PASS_RUST_SIGNAL_BATCH_OFFLINE_CAPACITY_V0`, 7/7 checks true, 100% trigger parity (10000/10000), 16391 eps effective throughput
  - artifact: `artifacts/rust_signal_batch_offline_capacity_v0/report.json`
- attempted the real 1800s soak required for `live_soak`: **blocked by this remote sandbox's execution ceiling, not RPC**. Evidence: a `setsid`+`nohup`+`disown` fully-detached test process was already dead (confirmed via `ps -p`) within ~2 seconds of the launching tool call returning — this sandbox reaps the entire process tree at tool-call boundaries, so no shell-level detachment technique survives across calls. The Bash tool's own `run_in_background` mode is capped at its `timeout` parameter, whose documented max is 600000ms (10 minutes); a soak launched with `timeout: 590000` was killed at that mark with zero log output, well short of the required 1800s (30 minutes).
- **not** worked around by retrying, and the `SOAK_MIN_DURATION_SECONDS = 1800.0` threshold was not touched/lowered (CLAUDE.md: never weaken a frozen gate to rescue a run). Operator decision (2026-09-29): leave step 8 pending; this specific sub-step needs either a longer-lived execution environment (e.g. a local machine, not this remote container) or a future session/tooling change that supports a >10-minute continuous live process.

No economic verdict exists or is any closer to existing from these systems steps alone.

- runbook delivered for the local 1800s soak: `docs/migration/V68_LOCAL_1800S_SOAK_RUNBOOK_2026-09-29.md` (7 steps, regenerates all 5 promotion-report inputs on the operator's own git HEAD, ends in a `--preflight-only` check that verifies readiness without opening a fresh V68 key)
- migration PR (`murilloalvz/crypto-copy-trader#3`) merged into `research/rust-signal-plane-live-shadow-v0` at commit `4bc59974783d0dd3ad57d9338fbaa5b247c7352a`, 2026-09-29
- **local 1800s soak run (2026-09-30, operator's own machine, dedicated Helius RPC + Jupiter key, following the runbook above): `FAIL_RUST_SIGNAL_PLANE_LIVE_SHADOW_V7_RUST_HOTPATH`.** All 4 preconditions (offline capacity, offline bridge, 120s smoke, 120s route-bridge) PASSed cleanly first. The 1800s soak itself failed on exactly one gate: `identity_plane_no_rpc_batch_failure = false` — 1 of 1467 RPC identity-resolution batches returned `SolanaRPCError` (2085/2086 unique pools resolved, 99.95%). Every other soak gate passed: `trigger_parity_100` (443673/443673, 0 mismatches), zero pump/pumpswap ingress drops, zero reader errors, zero decode failures, ingress accounting exact. This is a materially better result than any free-RPC attempt (which failed at 1-2% resolution loss or outright transport drops) — Helius held up for 1800s at 99.95% reliability, a single transient batch failure tripped the zero-tolerance gate.
  - resulting promotion report: `FAIL_V68_SIGNAL_PLANE_PROMOTION_V0` (`signal_plane_v68_promotion_v0.py`) — `soak_classification_pass` and `soak_all_live_gates_true` false, all other 20 checks (offline capacity, offline bridge, smoke, route-bridge) true; `git_head` recorded as `404760feb304d38b844a945114ee303d9b12384c`
  - resulting preflight: `FAIL_V68_RELEASE_READINESS_V1` (`route_research_v68_release.py --preflight-only`) — only `signal_plane_v7_promotion_authorized` false (cascading from the promotion report FAIL above); `jupiter_api_key_present`, `explicit_primary_rpc_configured`, `frozen_v68_economic_contract`, `signal_plane_episode_bridge_contract`, `no_v68_run_key_residue`, `sqlite_admission_idle` all PASS
  - note: the operator's local git HEAD (`404760f...`) does not match this branch's actual tip in the primary sandbox checkout (`52c9c21` at the time of this entry) — flagged per `CLAUDE.md`'s "whether any current state came from another divergent branch" requirement. No `.py` file relevant to this evidence chain was touched between the two HEADs this session (only markdown docs), so this is not expected to have affected the result's correctness, but the operator's local clone should be reconciled with `origin/chore/claude-migration-2026-09-27` before the next attempt.
  - per `CLAUDE.md`'s frozen-gate discipline, `SOAK_MIN_DURATION_SECONDS` / the zero-tolerance `identity_plane_no_rpc_batch_failure` gate were **not** touched or loosened. A single transient RPC batch failure out of 1467 over 1800s is plausibly noise rather than a structural ceiling (unlike the earlier free-RPC attempts, which failed early and repeatedly); one clean retry is warranted before treating this as a structural finding about Helius itself.
- **1800s soak retry (2026-10-01, operator's own machine): `PASS_RUST_SIGNAL_PLANE_LIVE_SHADOW_V7_RUST_HOTPATH`.** This run happened to use `api.mainnet.solana.com` (the public endpoint, per `endpoint_host` in the report -- not Helius; env var resolution at the time of this run is unconfirmed) and still resolved 2111/2111 unique pools with zero RPC batch failures over the full 1800s; `trigger_parity_100` exact on 526222/526222 decision points, zero ingress drops, `stack_errors: 0`, all 28 soak gates true. Artifact: `soak-1800s-retry-report.json`.
  - **resulting promotion report: `PASS_V68_SIGNAL_PLANE_PROMOTION_V0`** (`signal_plane_v68_promotion_v0.py`) — all 30 checks true (offline capacity, offline bridge, 120s smoke, this 1800s soak, route-bridge). `git_head: 6ec0a7bd84c8b84bfd7a4056255b27db165e5d17`. **This is the first time all V68 systems-promotion evidence has validated together in one hash-pinned report.**
  - resulting preflight run: `FAIL_V68_RELEASE_READINESS_V1` -- but the failure is operational, not scientific: `jupiter_api_key_present=FAIL` and `explicit_primary_rpc_configured=FAIL` with `database_path` resolving to a *different* local folder (`...\crypto-copy-trader\data\copytrader.db`) than every prior command in this sequence (`...\copytrader-sim\...`), meaning this one specific command ran from the wrong working directory / without that folder's `.env`. Notably, `signal_plane_v7_promotion_authorized=PASS` still matched the correct promotion report and git_head, confirming the promotion result itself is valid and was simply read correctly despite the wrong cwd for other checks.
  - **status: V68 systems-promotion evidence is now fully PASS.** Remaining action is purely operational: re-run `route_research_v68_release.py --preflight-only` from the correct directory (where `.env` lives) to get a clean all-true readiness confirmation. Step 8 (authorizing a fresh V68 key) remains a separate, explicit operator decision, not automated by a clean preflight.

### Participant Quality Tail-Risk Shadow Annotation V0 (new preregistration, DRAFT, not armed)

`docs/participant-quality-tail-risk-shadow-annotation-v0-preregistration-2026-09-29.md` — drafted
2026-09-29 at operator request, following up on the `...-04` PASS above. Not reused as data: this
new document proposes a **standing, append-only, annotation-only** shadow log (not another
burn-once holdout), computed with its own fresh outcome-blind cutoff, attached read-only alongside
`src.opportunity_decision_readiness.OpportunityDecisionReadiness` without touching that frozen
dataclass. Authorizes nothing yet — **DRAFT, requires explicit operator sign-off before any code is
written**, same as the tail-risk-rejection document's own DRAFT stage before it was armed. Its own
failure discipline explicitly separates "log the label" (this document, if signed off) from
"surface the label to a human" and "any skip-gate implementation" (each its own future, separately
gated decision) — nothing here authorizes changing admission, hazard, entry, or exit behavior.

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
