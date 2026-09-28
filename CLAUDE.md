# CLAUDE.md — Crypto Copy Trader

This file defines the operating contract for Claude Code on this repository.

## Read first

Before making any non-trivial change, read:

1. `docs/migration/START_HERE_CLAUDE_2026-09-27.md`
2. `docs/migration/BRANCH_AUTHORITY_MAP_2026-09-27.md`
3. `docs/migration/CODEBASE_MAP_2026-09-27.md`
4. the branch-local `PROJECT_CONTEXT.md`
5. the protocol/result documents directly related to the requested subsystem

Do not treat one branch's `PROJECT_CONTEXT.md` as the global state of the whole project. The repository has intentionally divergent systems and economic/research lines.

## Product direction

The project is an **Opportunity Intelligence Engine / Signal-First system**.

Current intended product path:

`opportunity intelligence -> research signal -> validated signal -> human TAKE/SKIP -> manual execution -> automated outcome collection -> shadow execution -> selective/assisted automation -> only eventually full automation`

Current operating mode is:

- PAPER
- RESEARCH
- READ ONLY
- no private key
- no funded execution
- no live-money authorization

Execution automation is not required to prove signal value. Execution realism is still required before any execution claim.

## Authority model

### Systems / Signal Plane / Research Plane integration

Primary authority:

- branch: `research/rust-signal-plane-live-shadow-v0`
- head at migration freeze: `e0f7bd1e239463e67bd680cc8bab1e15c406d52c`
- migration branch base: the exact branch above

This line contains the accepted Rust Signal Plane evolution, V7 promotion contract, Research Plane capacity hardening, role-normalized opportunity handling, Participant Quality memory/holdout work, and the latest systems-side scientific disposition.

### Post-Transition / later economic research

Primary authority:

- branch: `research/post-transition-pullback-reacceleration-v0`
- head at migration freeze: `730d32c3a0f382a1646976172a4ebd4cd3267252`

This line is later in wall-clock time and contains economic/research work from 2026-09-25 that is **not merged into the systems branch**.

It includes:

- Post-Transition Pullback/Reacceleration V0 scaffolding and prospective lineage work;
- the Post-Transition economic collector;
- transport hardening;
- the burned Fresh Economic Discovery V0;
- future signed Jupiter price-impact magnitude semantics;
- Concentration Decay discovery and fresh confirmation results.

Do not merge/cherry-pick this branch merely to make the migration look linear. Preserve the divergence unless a future task explicitly calls for a scientifically reviewed reconciliation.

## Critical current scientific state

### V48

- prospective `flow60_event_count` holdout: FAIL / CLOSED

### V55 -> V68

- V55 discovery: COMPLETE / CLEAN
- selected feature: `flow60_buy_share_pct`
- favorable LOW / opposite HIGH
- V55 discovery sample is burned for V68 validation
- V68 Flow60 buy-share holdout remains frozen and must not be retuned
- systems-aborted attempts do not constitute an economic verdict
- never rescue V68 using MID, a different horizon, new bins, another feature, or same-sample tuning

### Native Participant Quality Holdout V1

Formal result:

`KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`

Evidence authority:

`docs/native-participant-quality-holdout-v1-result-2026-09-24.md`

Important nuance:

- strong descriptive downside separation was observed;
- the frozen selector still failed its required profit-factor comparison;
- exact selector is CLOSED / KILL;
- no H3;
- no cutoff retune;
- no direction flip;
- no integration into live entry score;
- consumed H1/H2 can only generate a future separately preregistered hypothesis.

### Concentration Decay V0

On the Post-Transition branch:

- discovery: ITERATE, one fresh confirmation authorized;
- unchanged rule: `mf_top_wallet_gross_share_delta_pct_points_late_minus_early <= 0`;
- fresh confirmation: `INCONCLUSIVE_CONCENTRATION_DECAY_CONFIRMATION_SUPPORT`;
- candidate route-usable n=9 vs frozen minimum 10;
- no second ITERATE;
- exact selector is parked with no positive edge claim.

### Post-Transition Fresh Economic Discovery V0

On the Post-Transition branch:

- status: CLOSED / BURNED
- classification: `FAIL_POST_TRANSITION_FRESH_ECONOMIC_DISCOVERY_V0`
- fresh economic provider calls opened: true
- episode_count: 2
- conditional_economic_n: 0
- replacement run authorized: false

The run cannot be rerun as V0.

The two observed Jupiter signed `priceImpact` magnitudes were approximately 2.512pp and 87.611pp. Both exceed the frozen 2pp route-quality maximum.

Future protocol revisions only:

- missing/non-finite price impact => unavailable;
- finite signed impact is valid;
- maximum-impact gating compares `abs(priceImpact)`.

This future semantic correction does not rescue or reinterpret burned V0.

## Systems invariants

Never weaken these to rescue a run:

1. systems PASS != economic edge
2. discovery != validation
3. route-only return != realized P&L
4. no lookahead
5. no causal backfill
6. missingness stays explicit
7. first persisted trigger remains canonical
8. failed prospective hypotheses close rather than retune
9. one physical SQLite writer remains authoritative unless equivalence is proven
10. pool identity must be durable before publication
11. historical data may not receive fake historical `observed_at`
12. every signal is bounded by `decision_as_of`
13. funded BUY, landing/fill, shadow, and live money remain blocked unless explicitly released by future evidence

## Frozen systems gates

The legacy systems-sensitive acquisition gate remains 11/11:

1. no worker/traceback errors
2. drops = 0
3. reference-asset episodes = 0
4. radar coverage >=95%
5. true backlog <=5%
6. Pump p95 <=5s
7. PumpSwap causal pipeline p95 <=5s
8. hydration budget skips = 0
9. wallet/flow bundles nonempty
10. replay/audit valid
11. reservation-superset violations = 0

Never relax the 5s thresholds.

## Rust Signal Plane rule

The accepted Signal Plane hot path is frozen unless new evidence identifies a systems defect.

Do not casually rewrite Rust, detector semantics, trigger identity, ordering, or queue architecture.

If a downstream Research Plane problem occurs, prove that it originates in the Signal Plane before touching the Rust hot path.

## Research Plane capacity incident

Authority:

`docs/role-normalized-research-plane-capacity-incident-2026-09-24.md`

The role-normalization correction increased correct PumpSwap opportunity-token cardinality and exposed a bounded Research Plane queue overflow.

The documented correction was:

- queue capacity 4096 -> 16384
- drain timeout 60s -> 120s
- overflow remains hard FAIL
- dropped records remain unacceptable
- no backpressure added to the Signal Plane hot path

Sequence mismatch after overflow is downstream consequence, not an independent root cause.

## Coding discipline

For every requested code change:

1. inspect existing implementation first;
2. make the smallest change that satisfies the evidence;
3. reuse existing contracts before adding abstractions;
4. do not add dependencies unless necessary;
5. preserve fail-closed behavior;
6. preserve causal clocks and explicit missingness;
7. preserve frozen experiment contracts;
8. add or update the narrowest relevant test;
9. run targeted tests first;
10. expand testing only as needed;
11. summarize what changed, why, what was verified, and what remains unverified.

Do not perform broad cleanup/refactors while fixing a scoped issue.

## Ponytail / anti-overengineering compatibility

If the Ponytail Claude Code plugin is installed, use it as a scope-control tool only.

Ponytail must NEVER simplify away:

- causal validation;
- fail-closed guards;
- sequence/accounting checks;
- persistence durability;
- provider missingness;
- economic preregistration boundaries;
- scientific support/effect gates;
- evidence hashing;
- security or data-loss protections;
- required regression tests.

If minimal code conflicts with scientific auditability, scientific auditability wins.

## ECC compatibility

If ECC is installed, use it to improve planning, verification, review, and test discipline.

Project-specific scientific rules in this file and the migration docs override generic agent workflows.

Do not allow an external agent framework to:

- reinterpret frozen results;
- auto-promote hypotheses;
- generate live-money execution;
- broaden the task without evidence;
- merge divergent research lines for convenience.

## Git rules

- never force-push unless explicitly requested;
- never reset or discard unknown local work;
- never commit secrets or `.env`;
- never rewrite burned scientific history;
- prefer a scoped branch and reviewable commits;
- treat branch divergence as information, not as clutter to erase.

Before editing a file, identify which branch/subsystem is authoritative for it.

## Default testing baseline

Python environment is repository-specific; root runtime dependencies are in `requirements.txt`.

Rust integrated Signal Plane runner currently declares Rust `1.96.1` in:

`benchmarks/integrated_market_signal_plane_v1/rust_runner/Cargo.toml`

Use targeted commands from the directly related benchmark/protocol documentation rather than inventing a new all-purpose test harness.

Example offline Signal Plane baseline:

```powershell
python -m unittest tests.test_integrated_market_signal_plane_v1 -v

python -m benchmarks.integrated_market_signal_plane_v1.suite `
  --events 10000 `
  --seed 68 `
  --out "artifacts\integrated_market_signal_plane_v1\report.json"
```

A test PASS proves only what that test is designed to prove.

## When facts conflict

Use this precedence:

1. frozen result/closure artifact for the exact experiment;
2. exact protocol/preregistration for that experiment;
3. branch-specific implementation/tests;
4. branch-specific `PROJECT_CONTEXT.md`;
5. migration summary;
6. chat/memory recollection.

If two branches conflict because they represent different research lines, preserve both and document the split.

## Before declaring completion

Report explicitly:

- branch and commit used;
- files changed;
- tests actually run;
- tests not run;
- scientific contracts touched or confirmed untouched;
- whether any current state came from another divergent branch;
- anything that could not be validated in the current checkout.
