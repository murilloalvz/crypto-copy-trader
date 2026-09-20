# Signal Engine Priority Checkpoint — 2026-09-18

## Current product priority

The project is now developed first as an **Opportunity / Signal Engine** for human decision-making.

Primary operational flow:

```text
market
-> detection
-> causal analysis
-> quality / risk
-> signal
-> human entry decision
-> human-managed exit
```

Automated execution and automated exit/risk management remain later research/product stages.

## Separate evidence lanes

### 1. Signal / Selection Edge — highest priority

Question:

> Does information available before the outcome help identify opportunities that subsequently perform better?

Signal research should use standardized outcomes for scientific comparison without requiring one automatic exit policy to already form a profitable autonomous strategy.

### 2. Copyability / Risk — context and protection

Question:

> If a human chooses to enter, do the observed market conditions suggest reasonable practical entry/exit conditions or material tail risk?

This lane must remain separate from alpha/selection evidence.

### 3. Exit Edge — postponed as a blocker

Fixed+60, Smart Ladder and other exits remain standardized research benchmarks.

They do not define the user's manual exit behavior and do not block Signal Engine progress.

No new sophisticated trailing, sizing or automated exit work is prioritized unless signal evidence later justifies it.

## BUY event-rate acceleration result

Feature:

`mf_buy_event_rate_acceleration_per_s2`

Status:

**Do not continue as an autonomous alpha hypothesis. Preserve as Copyability / Tail-Risk evidence.**

Fresh replication showed a stable negative association between BUY acceleration and Fixed+60 outcome, but the favorable half remained loss-making under the standardized route-shadow benchmark.

Mechanism decomposition showed:

- more-negative/front-loaded BUY acceleration exit-failure rate: ~3.57%;
- less-negative/positive acceleration exit-failure rate: ~23.08%;
- overall mean return separation: ~24.91 percentage points;
- route-closed-only mean separation: ~9.91 percentage points.

The large reduction after conditioning on ROUTE_CLOSED indicates that much of the apparent advantage is explained by copyability / catastrophic-exit avoidance rather than robust pure price alpha.

No threshold retuning is authorized to rescue this feature as alpha.

## Active signal-quality research

Experiment:

`MF-EARLY-BUYER-PRIOR-QUALITY-V0`

Branch:

`research/early-buyer-prior-quality-v0`

Protocol hash:

`c22e2f9ca327e95616ac8093bd2c8fffc6063d9c9b53744f554e3dea7d1946ff`

Primary feature:

`mf_early_buyer_prior_route_closed_gross_median_of_wallet_medians_pct`

Question:

> Do BUY wallets observed causally inside the first 5 seconds carry strictly pre-T0 evidence from prior successful/unsuccessful market opportunities that improves current signal quality beyond existing flow evidence?

Important semantics:

- prior opportunity outcomes are **market-opportunity association labels**, never wallet realized PnL;
- only prior ROUTE_CLOSED gross +60s labels are used for the primary participant-quality history;
- prior exit evidence must be known strictly before current T0;
- same-second evidence is excluded;
- same-token prior history is excluded;
- missing history stays missing;
- primary current signal endpoint is ROUTE_CLOSED gross +60s return;
- all-route-usable net return including -100 exit failures is reference-only for Copyability sensitivity;
- no threshold search;
- no single 0-100 score;
- KEEP means only “worth fresh confirmation”, not “economic alpha proven”.

## Next implementation rule

Continue using:

```text
minimum implementation
-> test
-> evidence
-> KEEP / KILL / ITERATE
-> next highest-information step
```

Before expanding Entity / Funding / Deployer infrastructure, this minimal early-buyer prior-quality experiment must determine whether participant history has enough signal value to justify richer participant intelligence.

## Signal output direction

Future operational signals should keep dimensions separate:

- WHY NOW
- MARKET QUALITY
- PARTICIPANT QUALITY
- COPYABILITY
- LIQUIDITY
- TAIL RISK
- EVIDENCE
- IMPORTANT RISKS

No arbitrary combined score is authorized until evidence supports how the dimensions should be combined.


## Early-Buyer Prior Quality V0 — first discovery result

Classification:

`PASS_EARLY_BUYER_PRIOR_QUALITY_V0`

Decision:

`ITERATE`

Primary pooled signal-quality association on ROUTE_CLOSED gross +60s:

- usable pairs: 114;
- Spearman: +0.1995;
- Spearman without best trade: +0.2273;
- leave-one-out sign consistency: 1.0.

Incremental association after rank-residualizing BUY acceleration and signed flow:

- usable pairs: 114;
- partial Spearman: +0.1925.

Copyability-sensitive reference including unroutable exits:

- usable pairs: 131;
- Spearman: +0.2583;
- Spearman without best trade: +0.2800;
- leave-one-out sign consistency: 1.0.

Cross-run primary Spearman:

- discovery: approximately -0.0035;
- fresh1: approximately -0.0651;
- fresh2: approximately +0.3695;
- fresh4: approximately +0.5015.

The preregistered KEEP rule failed only because positive-direction run fraction was 2/4 rather than at least two-thirds. This is not a license to relax the rule.

Interpretation:

- the pooled signal is positive, robust to removal of the best trade and not obviously redundant with BUY acceleration or signed flow;
- temporal/cross-run stability is not yet established;
- the two latest captures are materially positive while the two earlier captures are near-zero/slightly negative;
- current status remains ITERATE;
- do not threshold-mine participant-history support or promote a selector.

Active diagnostic:

`early-buyer-prior-quality-maturity-v0`

Question:

> Is the mixed cross-run direction plausibly explained by historical-memory maturity/coverage rather than by a non-stationary or spurious participant-quality signal?

This diagnostic is posthoc only. It does not change the ITERATE decision or define a minimum-history threshold.


## Early-Buyer Prior Quality — fresh replication result

Experiment:

`MF-EARLY-BUYER-PRIOR-QUALITY-REPLICATION-V0`

Protocol hash:

`655f6cd2c0ba1bad14bc6caa21e7f45fb644edc803f099dc4ce00c210088f796`

Fresh run:

`launch_burst_prospective_route_live_v4-1789764120-3007bac012`

Classification:

`PASS_EARLY_BUYER_PRIOR_QUALITY_REPLICATION_V0`

Decision:

`KEEP`

Fresh population:

- baseline default-SOL episodes: 120;
- feature available episodes: 100 (83.33%);
- primary ROUTE_CLOSED feature/outcome pairs: 42;
- preregistered minimum: 30.

Primary Signal Quality endpoint (ROUTE_CLOSED gross +60s):

- Spearman: +0.5715;
- Spearman without best trade: +0.5411;
- leave-one-out sign consistency: 1.0;
- higher Participant Quality half mean: +9.26%;
- higher Participant Quality half median: -4.09%;
- lower/equal half mean: -30.81%;
- lower/equal half median: -36.36%.

Incremental evidence versus existing flow:

- partial Spearman controlling BUY event-rate acceleration and signed flow: +0.5339;
- feature vs BUY acceleration Spearman: +0.0771;
- feature vs signed flow Spearman: -0.2405.

Copyability-sensitive reference:

- route-usable Fixed+60 Spearman: +0.3999;
- without best trade: +0.3673;
- higher-half mean: -11.45%;
- lower/equal-half mean: -49.76%.

All preregistered KEEP checks passed.

Source integrity:

- fresh route-input identity differed from all four frozen history runs;
- fresh capture was strictly after the frozen history;
- requested duration 900s, duration-elapsed completion;
- exact causal reconstruction parity passed;
- feature snapshots were frozen before provider quotes;
- strict pre-T0 history only;
- same-second and same-token history excluded;
- no numeric support threshold;
- no threshold search;
- no wallet realized-PnL claim.

Scientific interpretation:

**Participant Quality is now retained as an evidence-backed Signal Engine dimension.**

This is not an autonomous trading-alpha claim. No production entry threshold, single score, landed-fill claim, manual-exit prescription or automatic selector has been established.

The fresh confirmation materially strengthened the original retrospective signal and retained a large positive partial association after controlling existing flow evidence. The next highest-information research step is a genuinely new information family rather than further tuning of this feature.

Next candidate family:

**Deployer Prior Quality / external participant intelligence**, with GMGN audited only as a prospective read-only evidence source. Any GMGN-derived feature must preserve local observed-at provenance and pass its own discovery -> freeze -> fresh confirmation flow.


## Deployer Prior Quality V0 — implementation checkpoint

Branch:

`research/deployer-prior-quality-v0`

Status:

**PREREGISTERED PROSPECTIVE DISCOVERY / IMPLEMENTED / LIVE NOT YET EXECUTED**

Primary feature:

`mf_deployer_created_count_snapshot_ex_current`

Definition:

`max((inner_count + open_count) - 1, 0)`

The feature is eligible only when one read-only GMGN `token info` creator lookup followed by one
`portfolio created-tokens` response both complete no later than the existing T0+5s decision cutoff.

Causal behavior:

- acquisition starts asynchronously when the Research Plane observes the Pump create anchor;
- provider/selector dispatch does not await GMGN;
- a queued request that cannot start before cutoff is skipped;
- a token-info response after cutoff stops the chain and remains missing;
- a created-tokens response after cutoff remains missing;
- errors and 429 rate limits remain missing;
- there is no retry to rescue one episode;
- late evidence is retained only in the raw audit artifact and is never backfilled into the frozen snapshot.

Security / product guardrails:

- `GMGN_API_KEY` only;
- `GMGN_PRIVATE_KEY` is removed from subprocess environment;
- no holdings, signing, swap or order execution;
- no capital;
- no selector change;
- no Sniper change;
- no Participant Quality change;
- no Route-Paper contract change.

Discovery endpoint:

- primary: ROUTE_CLOSED gross Fixed+60;
- secondary: ROUTE_CLOSED net Fixed+60;
- reference: route-usable Fixed+60 including unroutable=-100.

Incremental controls:

- retained Participant Quality;
- BUY event-rate acceleration;
- signed flow over event reserve.

Minimum primary route-closed feature/outcome pairs for a directional read: **30**.

This discovery sample cannot promote a selector. Even with a strong association it can only advance to
mechanism/robustness review and a separately frozen fresh-confirmation hypothesis.

Targeted Deployer V0 tests and the implementation/evaluator commits passed CI before live execution.


## Deployer Prior Quality V0 — systems-invalid acquisition 2026-09-20

Run:

`launch_burst_prospective_route_live_v4-1789920107-6b85a813f6`

The 900s market/route capture itself completed and the legacy wrapper produced a PASS, but the newly
introduced external-intelligence instrument was systems-invalid and MUST NOT be used for Deployer
Prior Quality scientific evaluation.

Observed deployer sidecar statuses:

- `CAUSAL_AVAILABLE = 4`
- `LATE_CREATED_TOKENS = 1`
- `TASK_CANCELLED_AFTER_CAPTURE = 334`

The process also emitted a Windows subprocess reader `UnicodeDecodeError` under cp1252 and the
event-loop executor shutdown warned that worker threads did not join within 300 seconds. Core route
artifacts were written around 13:18 local time while deployer evidence/wrapper artifacts were only
written around 15:23, proving a post-capture sidecar shutdown stall.

Classification:

`INVALID_EXTERNAL_EVIDENCE_ACQUISITION_SYSTEMS`

This is NOT:

- a Deployer hypothesis FAIL;
- an insufficient scientific sample;
- evidence of low GMGN coverage;
- permission to inspect/tune deployer thresholds from this run.

Economic/Sniper outcomes printed by the wrapper are excluded from Deployer V0 hypothesis decisions.

Root causes fixed before any replacement acquisition:

1. GMGN subprocess output is now captured as bytes and decoded explicitly with UTF-8
   `errors=replace`, avoiding Windows cp1252 reader-thread failure.
2. External acquisitions use two bounded concurrent slots instead of a single serialized global slot.
3. Waiting for a slot is bounded by each token's existing T0+5s cutoff.
4. Each CLI command timeout is bounded by the remaining causal cutoff.
5. Pending sidecar tasks are explicitly finalized before the live event loop closes.
6. Future wrapper PASS requires zero `TASK_CANCELLED_AFTER_CAPTURE`,
   `TASK_UNRESOLVED_AFTER_CAPTURE`, and `INTERNAL_ERROR`.
7. The Deployer evaluator independently rejects any run containing those systems-invalid statuses.

A replacement prospective capture is permitted only because this acquisition was declared systems-invalid
before Deployer feature/outcome evaluation. The replacement must use a new acquisition key and the same
frozen scientific feature/protocol. No economic outcome from this invalid run may guide the fix or next
hypothesis.
