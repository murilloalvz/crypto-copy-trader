# START HERE — Claude Code Migration Handoff — 2026-09-27

## Purpose

This document is the migration entry point for moving day-to-day development of `murilloalvz/crypto-copy-trader` to Claude Code without flattening the project's scientific history.

The migration deliberately separates:

- **chosen technical base for the migration**
- **global known project state across divergent branches**

Those are not the same thing.

## Migration base

Chosen technical base:

- branch: `research/rust-signal-plane-live-shadow-v0`
- head: `e0f7bd1e239463e67bd680cc8bab1e15c406d52c`
- migration branch: `chore/claude-migration-2026-09-27`

Why this base:

- it contains the latest verified systems-side work available at migration time;
- it includes the V7 Signal Plane promotion contract;
- it includes Research Plane batching/capacity work;
- it includes role-normalized PumpSwap opportunity fixes;
- it includes the closed Native Participant Quality holdout;
- it avoids force-merging the later, divergent economic research line.

This choice is operational only. It is **not** a claim that this branch is the sole or globally latest authority for all research.

## Global-state branch that must also be read

Later economic/research authority:

- branch: `research/post-transition-pullback-reacceleration-v0`
- head: `730d32c3a0f382a1646976172a4ebd4cd3267252`

At migration time, comparing systems -> Post-Transition reports divergent history:

- status: diverged
- Post-Transition ahead of the merge base by 150 commits
- systems branch on a separate line by 375 commits
- merge base: `319351ded652af29288552ef1f436fdb8149e81b`

Do not "solve" this by casual merge/cherry-pick.

## What Claude must understand immediately

### 1. This is not primarily a copy-trading bot anymore

The current direction is:

`market -> radar -> causal episode -> enrichment -> research decision -> forward outcomes -> prospective validation -> execution research -> shadow`

Product framing:

`Opportunity Intelligence / Signal-First / Human-Executed`

The initial value proposition is identifying and evaluating opportunities with causal evidence. Full autonomous execution is later-stage work only.

### 2. Live money is not authorized

Current release state:

- funded executable BUY: blocked / not released
- landing/fill validation: not released
- shadow execution: not released
- live money: not authorized

Do not add private-key handling, signing, transaction submission, or funded execution under the guise of "finishing the migration."

### 3. Systems PASS is not economic edge

The codebase contains highly successful systems results. None of those automatically prove profitable selection edge.

Always distinguish:

- semantic correctness
- systems capacity
- transport health
- causal readiness
- route availability
- economic outcome
- mature edge
- execution realism

## Systems-side state at migration

Authority:
`research/rust-signal-plane-live-shadow-v0 @ e0f7bd1...`

### Accepted historical systems profile

V9 historical accepted systems result:

- 11/11 PASS
- PumpSwap p95: 3.151s
- Pump p95: 1.478s
- coverage: 99.6%
- backlog: 0.408%

This is historical evidence, not permission to assume every future high-load run passes.

### Signal Plane architecture

The project migrated toward a Rust live hot path with Python parity outside live latency.

Important design rule:

- Rust handles the ordered live Signal Plane hot path.
- Python parity/audit remains mandatory where defined.
- Research persistence is downstream/off-hot-path.
- Do not reinsert slow Python work into the hot path without explicit evidence.

### V7

The current systems branch contains the V7 promotion contract and subsequent systems/research work.

Do not confuse this Signal Plane V7 naming with older unrelated historical "v7" files in other latency experiments.

Treat the current Rust Signal Plane contract as frozen unless new systems evidence requires a change.

### Research Plane capacity incident

Authority:

`docs/role-normalized-research-plane-capacity-incident-2026-09-24.md`

Observed incident after correcting PumpSwap opportunity-asset orientation:

- Signal Plane records: 35,714
- trade decision points: 35,639
- Pump adapted trades: 8,220
- PumpSwap adapted trades: 27,419
- selected route-research episodes: 40
- terminal hazard attempts: 40
- terminal entry attempts: 40
- frozen research decisions: 40
- scheduled route outcomes: 120

Root issue:

- bounded Research Plane persistence queue overflowed;
- later sequence mismatches followed queue loss;
- mismatch was consequence, not independent root cause.

Correction:

- Research Plane queue: 4,096 -> 16,384
- drain timeout: 60s -> 120s
- overflow remains hard FAIL
- no dropped record is acceptable
- no backpressure was added to the Signal Plane hot path

Subsequent Native Participant Quality H1/H2 cohorts passed the Signal Plane -> Research Plane -> route-research bridge and forward collector, which is strong evidence that the corrected path was usable for those runs.

### Native Participant Quality holdout

Authority:

`docs/native-participant-quality-holdout-v1-result-2026-09-24.md`

Final classification:

`KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`

Fresh cohorts:

- H1 episodes: 40
- H2 episodes: 40
- aggregate paired feature+900s outcomes: 56

Descriptive separation was substantial:

- aggregate HIGH median: -20.364707%
- aggregate LOW median: -99.510617%
- HIGH catastrophic-loss rate: 15.384615%
- LOW catastrophic-loss rate: 70.588235%

But the preregistered selector required every effect gate to pass.

It failed:

- aggregate HIGH profit factor > LOW profit factor

Observed PF:

- HIGH: 0.443728
- LOW: 0.465290

Therefore the exact selector is CLOSED / KILL.

Do not rescue it.

A future tail-risk/rejection hypothesis may be motivated by this consumed evidence, but that would require a new preregistration and independent fresh data.

## Economic/research state that exists only on the divergent Post-Transition line

Authority:
`research/post-transition-pullback-reacceleration-v0 @ 730d32c...`

### Concentration Decay V0

Frozen rule:

`mf_top_wallet_gross_share_delta_pct_points_late_minus_early <= 0.0`

Interpretation:
top-wallet gross-flow concentration did not increase from early to late half of the frozen first-5s window.

Discovery result:

- formal decision: ITERATE
- relative separation coherent
- absolute profitability gates not met
- exactly one unchanged fresh confirmation authorized

Fresh confirmation result:

`INCONCLUSIVE_CONCENTRATION_DECAY_CONFIRMATION_SUPPORT`

Key support:

- candidate route-usable n=9
- frozen minimum was 10

No second ITERATE is authorized.

Descriptively, most economics were directionally worse in the fresh sample. Those descriptive numbers do not override the formal INCONCLUSIVE status.

The exact selector is parked. No positive edge claim.

### Post-Transition Pullback/Reacceleration V0

Purpose:

Study:

`Pump birth -> PumpSwap transition -> pullback -> recovery/reacceleration`

Key causal rules:

- PumpSwap CreatePool is a transition anchor, not proof of Pump.fun graduation;
- exactly one valid reference side required;
- ambiguous pairs fail closed;
- no future extrema/lookahead;
- immutable transition+30s decision snapshot;
- structural reacceleration is diagnostic only;
- future labels were frozen before opening outcomes;
- lineage must be prospectively known, never backfilled.

### Prospective lineage readiness

The readiness protocol required a causal chain:

`Pump birth observed -> later PumpSwap transition -> post-transition trade -> immutable +30s snapshot`

Birth must satisfy:

`birth_observed_at < transition_observed_at`

Same-second persisted observations fail closed because one-second local storage cannot prove ordering safely.

### Post-Transition economic collector

Frozen route-only research shape included:

- US$25 paper notional
- +2s entry latency
- 20 bps entry fee
- 20 bps exit fee
- 100 bps adverse entry slippage
- 100 bps adverse exit slippage
- max provider impact magnitude intended at 2 percentage points
- Fixed+60 primary
- Fixed+300 exploratory
- TP50 / TP100 / TP200 independent
- dynamic exits not armed
- 300s right-censoring
- no funded wallet required for research

Transport policy was hardened before the burned economic result.

### Burned Fresh Economic Discovery V0

Closure artifact:

`benchmarks/post_transition_reacceleration_v0/fresh_economic_discovery_v0.closed.json`

Final state:

- CLOSED_BURNED
- replacement_run_authorized=false
- classification=`FAIL_POST_TRANSITION_FRESH_ECONOMIC_DISCOVERY_V0`
- fresh_economic_outcomes_opened=true
- episode_count=2
- conditional_economic_n=0

Both entries were rejected by V0 as `PRICE_IMPACT_UNAVAILABLE` because V0 incorrectly treated negative signed Jupiter `priceImpact` as unavailable.

Post-sample semantic audit determined:

- finite signed impact is valid;
- missing/non-finite impact is unavailable;
- a magnitude threshold must compare `abs(priceImpact)`.

But this correction does NOT rescue V0.

Observed magnitudes were approximately:

- 2.512pp
- 87.611pp

Both still exceed the frozen 2pp maximum.

Therefore:

- no V0 P&L/edge verdict exists;
- V0 remains burned;
- no replacement V0 run;
- future work needs a new frozen protocol revision plus more reliable transport or a separately frozen gap-aware coverage design.

## V48 / V55 / V68 lineage

### V48

`flow60_event_count` prospective holdout:

- FAIL
- CLOSED

Do not retune.

### V55

Discovery:

- COMPLETE / CLEAN

Exactly one candidate advanced:

- feature: `flow60_buy_share_pct`
- LOW <= 57.1429
- MID <= 65.7143
- HIGH > 65.7143
- favorable LOW
- opposite HIGH
- primary horizon 900s

The V55 sample is discovery-only and burned for V68 validation.

### V68

Frozen holdout contract must not be changed to rescue outcomes.

Important invariants include:

- same detector
- same bins
- same direction
- same primary horizon
- same support minima
- no MID rescue
- no alternate-horizon rescue
- no feature substitution
- no same-sample threshold search

A systems failure before valid forward economic collection does not classify V68 economically.

## Scientific invariants to preserve

At minimum:

1. discovery != validation
2. systems PASS != economic edge
3. route-only return != realized P&L
4. route availability != assembly != landing != fill
5. first persisted trigger remains canonical
6. no lookahead
7. no retroactive enrollment
8. no causal backfill
9. explicit missingness
10. wallet is post-episode evidence only
11. same-sample rescue is forbidden
12. failed prospective hypotheses close
13. burned samples stay burned
14. signal updates do not rewrite old decisions
15. every signal is bounded by its `decision_as_of`
16. no live money without independent forward + execution + shadow evidence

## What not to do during migration

Do not:

- merge the systems and Post-Transition branches just to simplify onboarding;
- cherry-pick economic code into the systems branch without a scoped future task;
- rewrite `PROJECT_CONTEXT.md` into a fake unified chronology;
- delete old artifacts/protocols because they look stale;
- retune failed hypotheses;
- reclassify INCONCLUSIVE as FAIL/PASS;
- rerun burned V0;
- reopen Native Participant Quality selector;
- alter the Rust hot path without new evidence;
- add private-key or live-order code.

## Recommended Claude workflow

For any task:

1. identify the subsystem;
2. identify its authority branch;
3. inspect only the directly related protocol/result/code;
4. state what is frozen;
5. state what is still open;
6. make the smallest scoped change;
7. run targeted tests;
8. preserve causal semantics;
9. report anything not validated.

If work spans systems and economics, do not assume one branch can safely become the other's base. First write an explicit reconciliation plan.

## Repo setup

Typical local PowerShell bootstrap:

```powershell
git clone https://github.com/murilloalvz/crypto-copy-trader.git
cd crypto-copy-trader
git fetch --all --prune
git switch chore/claude-migration-2026-09-27

py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Do not put API keys in Git.

Use `.env.example` only as a variable-name reference.

## Migration completion criterion

Migration is successful when Claude can answer, from the repo alone:

- what branch is authoritative for systems;
- what branch is authoritative for the later economic line;
- what experiments are CLOSED/KILL/INCONCLUSIVE/NOT_EVALUATED;
- what samples are burned;
- what gates are frozen;
- why V0 cannot be rerun;
- why Participant Quality cannot be retuned;
- why systems PASS is not edge;
- why live money is blocked;
- what it may change for a scoped task and what it must not change.

If Claude cannot answer those correctly, read the authority map and exact result documents before writing code.
