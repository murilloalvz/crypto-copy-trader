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

## Deployer Prior Quality V0 — valid replacement discovery result

Valid replacement run:

`launch_burst_prospective_route_live_v4-1789946453-0367216d26`

Systems:

- wrapper: `PASS_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_SNIPER_V1`;
- duration: 900s / `duration_elapsed`;
- deployer records: 417;
- `CAUSAL_AVAILABLE = 337`;
- invalid systems statuses: zero;
- external acquisition systems-valid.

Scientific decision:

`INSUFFICIENT_SAMPLE_NO_EXTENSION`

Primary ROUTE_CLOSED feature/outcome pairs:

- observed: 29;
- preregistered minimum: 30.

Descriptive result only, not a formal KILL decision:

- primary Spearman: +0.0393;
- without best trade: -0.0701;
- higher created-count half median: -20.18%;
- lower/equal half median: -20.17%;
- partial Spearman controlling retained Participant Quality + BUY acceleration + signed flow: -0.0424 on 24 complete pairs;
- copyability-sensitive Spearman: -0.1313.

The sample MUST NOT be extended or repeated to obtain the missing 30th pair. The created-count feature is not promoted, retuned or rescued from this sample. Participant Quality remains retained independently.

## Holder Ownership Structure V0 — preregistered next family

Branch:

`research/holder-ownership-structure-v0`

Experiment:

`MF-HOLDER-OWNERSHIP-STRUCTURE-V0`

Protocol hash:

`1b64a88415ec7815cda87c240234daf9ca21b4a413b6585e87377d67b9ef1dff`

Primary feature:

`mf_holder_top100_regular_wallet_supply_hhi`

Frozen definition:

`sum(amount_percentage^2)` over GMGN Top100 holder rows with `addr_type=0`.

Address semantics are explicit:

- `addr_type=0`: regular wallet — included;
- `addr_type=1`: burn/dead — excluded;
- `addr_type=2`: exchange / DEX / liquidity pool — excluded;
- missing or unknown address type: feature is MISSING.

`amount_percentage` remains a share of TOTAL SUPPLY. It is never rebased to tradeable float. This deliberately avoids launchpad float-denominator degeneration and the previously observed pool-as-100%-holder trap.

Preregistered direction:

higher regular-wallet concentration -> worse future ROUTE_CLOSED gross Fixed+60 outcome.

Acquisition:

- one read-only `gmgn-cli token holders` request per observed token;
- Top100 sorted by `amount_percentage`;
- response must complete no later than T0+5s;
- no retry rescue;
- late/error/429/ambiguous schema stays MISSING;
- one bounded external slot, consistent with GMGN's current default 1 request/second guidance;
- Research Plane only; Signal Plane does not wait for GMGN.

Incremental controls remain:

- retained Participant Quality;
- BUY event-rate acceleration;
- signed flow over event reserve.

Minimum primary route-closed pairs: 30.

This discovery sample cannot promote a selector. Sufficient discovery can only advance to mechanism/robustness review and a separately frozen independent fresh confirmation.

## Holder Ownership Structure V0 — systems-invalid first acquisition 2026-09-20

Run:

`launch_burst_prospective_route_live_v4-1789951070-83905705bc`

The market/route capture completed for the requested 900s and the first Holder wrapper classified itself PASS, but the external Holder acquisition is now declared **SYSTEMS-INVALID BEFORE OUTCOME EVALUATION**.

Observed Holder sidecar statuses:

- `record_count = 455`;
- `CAUSAL_AVAILABLE = 4`;
- `RATE_LIMITED_HOLDERS = 419`;
- `LATE_WAITING_FOR_SLOT = 21`;
- `LATE_BEFORE_SLOT = 8`;
- `LATE_BEFORE_HOLDERS = 2`;
- `NO_REGULAR_WALLETS = 1`.

No Holder/outcome evaluator was run.

Root cause:

- GMGN `token holders` has route weight 5;
- the Free plan leaky bucket is 5/5, implying approximately one Holder request per second and burst capacity one;
- a semaphore of one serialized requests but did not pace their start times, so fast completions immediately launched the next call and repeatedly hit 429;
- current gmgn-cli may also auto-retry once after a short cooldown unless explicitly disabled.

Systems-only fixes:

1. enforce at least 1.05 seconds between Holder request starts;
2. keep the single provider slot;
3. if causal cutoff cannot survive the rate-slot wait, fail closed as `LATE_WAITING_FOR_RATE_SLOT`;
4. set `GMGN_RATE_LIMIT_AUTO_RETRY_MAX_WAIT_MS=0` so the CLI cannot silently perform a second attempt;
5. treat any `RATE_LIMITED_HOLDERS` in a prospective acquisition as systems-invalid before Holder outcome evaluation;
6. evaluator independently rejects a rate-limited acquisition.

The frozen Holder feature, expected direction, T0+5s cutoff, outcome definitions, incremental controls and selector guardrails are unchanged. A replacement acquisition is permitted solely because the first Holder acquisition was invalidated on acquisition-capacity grounds before Holder/outcome evaluation.

## Holder Ownership Structure V0 — second systems-invalid acquisition and provider pivot

Second GMGN-backed replacement run:

`launch_burst_prospective_route_live_v4-1789952423-3cd1e18599`

Observed statuses:

- `record_count = 325`;
- `CAUSAL_AVAILABLE = 1`;
- `RATE_LIMITED_HOLDERS = 320`;
- `LATE_WAITING_FOR_RATE_SLOT = 1`;
- `LATE_WAITING_FOR_SLOT = 3`.

Classification:

`INVALID_EXTERNAL_EVIDENCE_ACQUISITION_SYSTEMS`

No Holder/outcome evaluator was run. The preregistered holder-direction hypothesis was therefore not evaluated.

The second systems failure showed that the Free GMGN `token holders` route is not a reliable prospective acquisition dependency for this experiment. The project will not continue issuing 900s GMGN Holder replacements.

Provider decision:

**ABANDON GMGN HOLDER ACQUISITION; PRESERVE THE HOLDER-CONCENTRATION MECHANISM AS A NEW NATIVE VERSION.**

## Holder Ownership Structure Native V1 — preregistered

Branch:

`research/holder-ownership-native-v1`

Experiment:

`MF-HOLDER-OWNERSHIP-STRUCTURE-NATIVE-V1`

Protocol hash:

`90132a6656738dceb4662b4701091f5290c2f7c85c9c3896c7326c0fec75a565`

Primary feature:

`mf_holder_pump_pregrad_non_curve_owner_supply_hhi_native`

Frozen acquisition/derivation:

1. anchor on decoded Pump create and retain its exact `bonding_curve`;
2. do not request the external holder snapshot before T0+3s;
3. all evidence must complete no later than T0+5s;
4. obtain exact raw total supply with Helius `getTokenSupply`;
5. obtain mint-filtered token accounts with Helius `getTokenAccounts`, up to 1000 rows/page and bounded pagination;
6. aggregate multiple token accounts belonging to the same owner;
7. exclude the exact decoded Pump bonding-curve owner;
8. divide each remaining owner balance by total raw supply and sum squared shares (HHI);
9. never rebase the denominator to tradeable/non-curve float;
10. if PumpSwap graduation is causally observed before the snapshot request, mark the feature MISSING instead of guessing pool-vault ownership;
11. incomplete pagination, late evidence, schema errors and provider errors remain MISSING;
12. no retry rescue.

Preregistered direction remains mechanistic and outcome-blind:

higher non-curve owner concentration -> worse future ROUTE_CLOSED gross Fixed+60 outcome.

Incremental controls remain frozen Participant Quality + BUY acceleration + signed flow.

Minimum primary route-closed pairs remains 30. This discovery cannot promote a selector.

## Holder Ownership Structure Native V1 — Helius WSS usage-cap invalidation

Run attempt:

`launch_burst_prospective_route_live_v4-1789954092-eb60e7880e`

The Helius Holder HTTP/DAS preflight passed, including `getTokenSupply` and `getTokenAccounts`. The 900s prospective market capture did not begin successfully because the existing Helius Standard WSS ingest closed with:

`ConnectionClosedOK: received 1001 (going away) usage cap exceeded`

No Native V1 wrapper report was produced and no Holder/outcome evaluator was run.

Classification:

`INVALID_MARKET_INGEST_SYSTEMS_BEFORE_SCIENTIFIC_EVALUATION`

This is not a Holder hypothesis failure and does not authorize feature retuning.

Systems-only provider split for the replacement:

- market Pump/PumpSwap logs: Solana public Standard WSS `wss://api.mainnet.solana.com/`;
- market methods: the same two program-filtered `logsSubscribe` subscriptions plus `slotSubscribe`;
- no per-transaction HTTP hydration;
- Holder snapshot evidence: Helius HTTP/RPC `getTokenSupply` + mint-filtered `getTokenAccounts`;
- Jupiter/RPC route-paper evidence unchanged;
- feature, direction, T0+3 snapshot-not-before time, T0+5 cutoff, outcomes, controls, route contract and selector remain unchanged.

The public WSS is a research-only fallback with no production SLA. A dedicated preflight must observe all subscription acknowledgements and at least one slot notification before the replacement is allowed to start.

The wrapper records `market_ingest_provider=solana_public_standard_wss`, and the evaluator independently rejects a run with a different market-ingest attestation.

A replacement acquisition is permitted because this run was invalidated by market-ingest quota before any Native V1 scientific outcome evaluation.

## Holder Ownership Native V1 — Helius HTTP quota invalidation

After the Helius WSS usage-cap invalidation, the Native V1 replacement preflight was rerun with public Solana Standard WSS for market ingest.

Local tests and environment gates passed, but the Helius holder HTTP preflight failed before live capture:

`RuntimeError:getTokenSupply capability probe failed: HTTP_429`

No 900s capture began, no wrapper report was produced, and no Holder/outcome evaluator was run.

Classification:

`INVALID_EXTERNAL_EVIDENCE_PROVIDER_QUOTA_BEFORE_SCIENTIFIC_EVALUATION`

This establishes that the active Helius quota is currently unsuitable not only for Standard WSS but also for the HTTP/RPC holder snapshot path. Native V1 is therefore closed without scientific evaluation. No feature direction or outcome was inspected.

## Holder Ownership RPC V2 — preregistered no-Helius replacement

Branch:

`research/holder-ownership-rpc-v2`

Experiment:

`MF-HOLDER-OWNERSHIP-RPC-V2`

Protocol hash:

`9e54b4033ef218f958c2c6386efbcb375077b5e78755c1cd40419c73bc7616b4`

Primary feature:

`mf_holder_pump_pregrad_top20_non_curve_owner_supply_hhi_rpc`

This is explicitly a NEW feature/version, not a relabeling of Native V1.

Frozen acquisition:

1. market ingest uses Solana public Standard WSS only, with Pump/PumpSwap `logsSubscribe` plus `slotSubscribe`;
2. no per-transaction HTTP hydration is used for market ingest;
3. before capture, select one non-Helius standard JSON-RPC endpoint from configured `SOLANA_RPC_URL` / fallbacks, otherwise `api.mainnet.solana.com`;
4. the selected holder/route RPC endpoint is fixed for the run;
5. do not request Holder evidence before T0+3s;
6. all Holder evidence must complete no later than T0+5s;
7. call `getTokenSupply(processed)`;
8. call `getTokenLargestAccounts(processed)`;
9. resolve the returned token-account owners with one `getMultipleAccounts(jsonParsed, processed)`;
10. aggregate duplicate owners among the returned Top20 token accounts;
11. exclude the exact decoded Pump `bonding_curve` owner;
12. compute HHI from those Top20 non-curve owner balances divided by exact total raw supply;
13. do NOT claim full-holder HHI: accounts outside the Top20 are intentionally unobserved;
14. snapshot starts are paced by at least 0.5s;
15. if a snapshot cannot fit inside T0+5s, it is MISSING;
16. any HTTP/RPC 429 invalidates the acquisition at systems level;
17. no retry rescue or provider switch after capture start;
18. if PumpSwap graduation is observed before snapshot request, feature is MISSING.

The route contract, standardized Fixed+60 outcome, Participant Quality control and existing flow controls remain unchanged.

Preregistered direction:

higher Top20 non-curve owner concentration -> worse future ROUTE_CLOSED gross Fixed+60 outcome.

Minimum primary route-closed feature/outcome pairs remains 30.

This discovery sample cannot promote a selector or automatic entry rule.

## Holder Ownership RPC V2 — public RPC preflight invalidation

Branch attempt:

`research/holder-ownership-rpc-v2`

The preregistered no-Helius Holder RPC V2 passed targeted unit tests, but the read-only capability preflight failed before any 900s live acquisition:

`RuntimeError:getTokenLargestAccounts capability probe failed on api.mainnet-beta.solana.com: HTTP_429`

No prospective capture started and no Holder/outcome evaluator ran.

Classification:

`INVALID_STANDARD_RPC_PROVIDER_RATE_LIMIT_BEFORE_SCIENTIFIC_EVALUATION`

This is not scientific evidence for or against holder concentration. RPC V2 is closed without rerolling another provider endpoint solely to rescue the experiment.

## Early Balance Concentration V0 — preregistered retrospective discovery

Branch:

`research/early-balance-concentration-v0`

Experiment:

`MF-EARLY-BALANCE-CONCENTRATION-V0`

Protocol hash:

`fb31f536d816d47a2974271d44d8584022dc5acf57e7ed6bad6b7bf9487ac2ec`

Primary feature:

`mf_early_net_acquired_token_hhi_t0_5s`

Frozen definition:

- use only decoded Pump trades already captured in each episode's causal T0..T0+5s window;
- require both local arrival time and decoded chain timestamp to fall inside the frozen evidence window;
- per wallet, add `token_amount_raw` on buys and subtract it on sells;
- keep only positive ending observed net balances;
- normalize each positive wallet balance by the sum of positive observed net balances;
- feature = sum of squared normalized wallet shares (HHI);
- one positive wallet is a valid maximum-concentration value of 1.0;
- no positive observed net balance -> MISSING.

This feature measures concentration of **observed early net token acquisition**, not true full-wallet inventory or a full on-chain holder snapshot.

Preregistered direction:

higher early net-acquired token concentration -> worse future ROUTE_CLOSED gross Fixed+60 outcome.

Discovery source set is frozen before evaluation to exactly these already-captured runs:

1. `launch_burst_prospective_route_live_v4-1789605670-3592832863`
2. `launch_burst_prospective_route_live_v4-1789687945-0315e2560c`
3. `launch_burst_prospective_route_live_v4-1789692405-6daeedeb29`
4. `launch_burst_prospective_route_live_v4-1789698815-b277ffea77`
5. `launch_burst_prospective_route_live_v4-1789946453-0367216d26`

No new live acquisition and no new outcome collection are required.

Incremental controls remain:

- retained Participant Quality;
- BUY event-rate acceleration;
- signed flow over event reserve.

Minimum primary route-closed feature/outcome pairs: 30.

This is explicitly RETROSPECTIVE DISCOVERY. Even a strong result cannot promote a selector from the same sample; it can only justify mechanism/robustness review followed by a separately frozen prospective confirmation.

## Early Balance Concentration V0 — negative discovery result

Evaluator:

`PASS_EARLY_BALANCE_CONCENTRATION_V0`

Decision:

`DISCOVERY_COMPLETE_NO_PROMOTION`

Coverage/integrity:

- five frozen runs;
- 409 baseline/default-SOL episodes;
- 409/409 causal feature availability;
- 196 ROUTE_CLOSED primary feature/outcome pairs;
- exact reconstruction parity on every run;
- no external holder provider;
- no new live acquisition;
- no new outcome collection.

Preregistered direction was negative: higher concentration should predict worse Fixed+60 outcomes.

Observed primary result:

- Spearman: +0.11879;
- without best trade: +0.12620;
- leave-one-out sign consistency: 1.0, consistently in the opposite direction;
- higher-HHI half median gross: -10.37%;
- lower/equal-HHI half median gross: -19.91%.

Incremental result controlling retained Participant Quality + BUY acceleration + signed flow:

- usable complete pairs: 142;
- partial Spearman: +0.06529.

Copyability-sensitive reference:

- usable pairs: 236;
- Spearman: +0.01446.

Conclusion:

**CLOSE EARLY BALANCE CONCENTRATION V0.**

The preregistered negative direction did not replicate; incremental association was also positive. Do not retune HHI, search thresholds, redefine the denominator, extend the sample, or invert the feature into a selector. This family is closed as a negative discovery result.

## Early Buyer Churn V0 — preregistered next event-native family

Branch:

`research/early-buyer-churn-v0`

Experiment:

`MF-EARLY-BUYER-CHURN-V0`

Protocol hash:

`5c9389bfd1954cddd0528916d933d6d4495906826d45689c424282a402996d3e`

Primary feature:

`mf_early_buyer_roundtrip_sellback_fraction_t0_5s`

Mechanism:

- reconstruct only decoded Pump trades causally observed inside T0..T0+5s;
- maintain observed acquired token inventory per wallet;
- BUY adds `token_amount_raw`;
- SELL matches only up to that wallet's currently observed acquired inventory;
- sells before an observed buy and oversell beyond observed acquired inventory remain unmatched and do not count as churn;
- numerator = matched same-wallet sellback raw token amount;
- denominator = total observed buy raw token amount;
- feature range = 0..1;
- no observed BUY -> MISSING.

Interpretation:

fraction of early observed bought inventory that the same buyers already sold back inside the launch window. This measures immediate buyer churn/round-trip behavior, not total sell flow and not true wallet inventory.

Preregistered direction:

higher early buyer churn -> worse future ROUTE_CLOSED gross Fixed+60 outcome.

To reduce sequential retrospective overfitting, the existing data are frozen into a temporal split BEFORE evaluating this feature:

Discovery:

1. `launch_burst_prospective_route_live_v4-1789605670-3592832863`
2. `launch_burst_prospective_route_live_v4-1789687945-0315e2560c`
3. `launch_burst_prospective_route_live_v4-1789692405-6daeedeb29`
4. `launch_burst_prospective_route_live_v4-1789698815-b277ffea77`

Temporal holdout:

`launch_burst_prospective_route_live_v4-1789946453-0367216d26`

Frozen decision rule:

- discovery primary pairs >=80;
- holdout primary pairs >=20;
- discovery primary Spearman <0;
- discovery Spearman without best trade <0;
- discovery leave-one-out sign consistency >=0.8;
- discovery partial Spearman controlling Participant Quality + BUY acceleration + signed flow <0;
- holdout primary Spearman <0;
- holdout partial Spearman with the same controls <0.

If all pass:

`RETROSPECTIVE_TEMPORAL_REPLICATION_NO_PROMOTION`

If sample is sufficient but any replication condition fails:

`NO_REPLICATION_CLOSE_FAMILY`

If either sample minimum is not met:

`INSUFFICIENT_SAMPLE_NO_EXTENSION`

The temporal holdout is stronger than pooled retrospective discovery but is NOT a prospective confirmation because all five runs already belong to the existing research corpus. No selector can be promoted from this result.

## Early Buyer Churn V0 — retrospective temporal replication result

Evaluator:

`PASS_EARLY_BUYER_CHURN_V0`

Decision:

`RETROSPECTIVE_TEMPORAL_REPLICATION_NO_PROMOTION`

All frozen decision checks passed.

Discovery block (first four frozen runs):

- primary ROUTE_CLOSED pairs: 161;
- primary Spearman: -0.11619;
- without best trade: -0.13247;
- leave-one-out sign consistency: 1.0;
- partial Spearman controlling retained Participant Quality + BUY acceleration + signed flow: -0.06787 on 114 complete pairs.

Temporal holdout (fifth frozen run):

- primary ROUTE_CLOSED pairs: 35;
- primary Spearman: -0.04635;
- without best trade: -0.11410;
- leave-one-out sign consistency: 1.0;
- partial Spearman with the same controls: -0.02831 on 28 complete pairs.

Structure:

- 409/409 baseline episodes had the event-native feature available;
- pooled median churn fraction: 0.13967;
- zero-churn fraction: 31.30%;
- median flipper-wallet share: 23.08%.

Interpretation:

The exact preregistered churn feature showed the expected negative direction in discovery and repeated both direction and incremental sign in the frozen temporal holdout. Effect size is modest, especially in the holdout. This is stronger than pooled retrospective discovery but remains retrospective evidence and MUST NOT be called prospective confirmation or promoted directly into a selector.

Next step is post-discovery mechanism/robustness audit of the exact feature followed, only if still credible, by prospective instrumentation and a separately frozen fresh confirmation.

## Early Buyer Churn Robustness V0 — post-discovery audit

Branch:

`research/early-buyer-churn-robustness-v0`

Purpose:

Check whether the exact frozen churn association is distributed across acquisition periods or is driven by a single run.

This audit is explicitly designed AFTER seeing the churn result. Therefore it adds robustness context only and carries **no new confirmatory evidence weight**.

Frozen audit operations:

- reuse the exact `mf_early_buyer_roundtrip_sellback_fraction_t0_5s` definition;
- evaluate primary Spearman per each of the five runs;
- evaluate partial Spearman per run when complete controls permit;
- recompute pooled association after dropping each whole run one at a time;
- recompute pooled partial association after dropping each whole run one at a time;
- report the structural zero-churn versus positive-churn split only as a mechanism diagnostic;
- no threshold search;
- no feature redefinition;
- no selector or score construction;
- no new live acquisition or outcome collection.

A favorable audit can justify engineering the exact feature for future prospective capture. It cannot promote the feature or replace a fresh confirmation.

## Early Buyer Churn Robustness V0 — result

Evaluator:

`PASS_EARLY_BUYER_CHURN_ROBUSTNESS_V0`

Evidence level:

`POST_DISCOVERY_ROBUSTNESS_AUDIT_NO_NEW_CONFIRMATION_WEIGHT`

Pooled exact-feature result across the five frozen runs:

- primary ROUTE_CLOSED pairs: 196;
- primary Spearman: -0.10292;
- without best trade: -0.11608;
- leave-one-out sign consistency: 1.0;
- partial Spearman controlling Participant Quality + BUY acceleration + signed flow: -0.04422 on 142 complete pairs.

Run-level sign diagnostics:

- primary Spearman negative in 4/5 runs (80%);
- partial Spearman negative in 3/5 runs (60%);
- one run had positive primary association (+0.11763);
- two runs had non-negative partial association (+0.09283 and +0.00333).

Whole-run removal robustness:

- primary Spearman remained negative after dropping each of the five runs: 5/5;
- partial Spearman remained negative after dropping each of the five runs: 5/5.

Mechanism diagnostics:

- churn feature vs flipper-wallet share Spearman: +0.81295;
- median unique buy wallets: 8;
- median flipper wallets: 2.

Interpretation:

The effect is not perfectly regime-invariant at the individual-run level, but no single acquisition period carries the pooled negative primary or incremental association. This supports investing in prospective instrumentation of the exact feature. It does NOT add new confirmatory evidence because the audit was designed after observing the churn result.

## Early Buyer Churn Prospective V1 — frozen confirmation protocol

Branch:

`research/early-buyer-churn-prospective-v1`

Experiment:

`MF-EARLY-BUYER-CHURN-PROSPECTIVE-V1`

Protocol hash:

`0aaf83c2644a6d5eab63034cb09bd403edf87791a0de47a597361a698eba9827`

Exact feature retained without redefinition:

`mf_early_buyer_roundtrip_sellback_fraction_t0_5s`

Prospective instrumentation contract:

- use the same decoded Pump trade semantics and exact T0..T0+5s causal window;
- compute only after causal coverage through T0+5 is complete;
- enrich the feature snapshot before provider quote/outcome collection;
- no external provider is needed to compute churn;
- no Signal Plane external-I/O blocking is introduced;
- right-censored windows remain MISSING;
- no threshold, score or selector is added.

Before any fresh confirmation, an offline parity gate must replay the exact prospective instrumentation over the five prior frozen runs and match the retrospective reconstruction with zero status/value mismatches.

Fresh confirmation is frozen to:

- exactly one new prospective run;
- requested duration: 900 seconds;
- the fresh run identity must differ from every prior discovery/parity run;
- primary: ROUTE_CLOSED gross Fixed+60;
- controls: retained Participant Quality + BUY acceleration + signed flow;
- minimum primary feature/outcome pairs: 30.

KEEP requires all of:

- primary Spearman < 0;
- Spearman without best trade < 0;
- leave-one-out sign consistency >= 0.8;
- partial Spearman controlling the frozen controls < 0;
- higher-churn half median gross return < lower/equal-churn half median gross return.

If fewer than 30 primary pairs:

`INSUFFICIENT_SAMPLE_NO_EXTENSION`

If sample is sufficient but any KEEP criterion fails:

`NO_CONFIRMATION_CLOSE_OR_REVIEW`

No threshold search, feature redefinition, sample extension based on outcomes or selector promotion is allowed.

## Early Buyer Churn Prospective V1 — parity PASS and fresh-confirmation tooling ready

Offline parity gate result:

`PASS_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PARITY`

Parity summary:

- compared complete episodes: 2056;
- mismatch count: 0;
- exact parity: true;
- exact status parity: true in all five frozen runs;
- exact feature-value parity: true in all five frozen runs;
- all parity guardrails valid;
- no provider quotes used;
- no external provider used;
- no outcome-driven feature modification;
- no threshold search or selector change.

Per-run complete/available/missing counts:

1. 422 complete / 402 causal / 20 missing;
2. 465 complete / 356 causal / 109 missing;
3. 357 complete / 306 causal / 51 missing;
4. 395 complete / 380 causal / 15 missing;
5. 417 complete / 389 causal / 28 missing.

Interpretation:

The prospective instrumentation is now engineering-equivalent to the exact retrospective feature implementation that produced the churn discovery/temporal-holdout evidence. This parity result validates implementation fidelity only; it adds no economic confirmation weight.

Fresh-confirmation tooling added:

- `benchmarks/early_buyer_churn_prospective_v1/run_live.py`
  - requires the exact PASS parity report before capture;
  - refuses a changed 900-second duration;
  - enriches churn before provider quotes;
  - emits a dedicated wrapper attestation;
  - fails closed if complete snapshots lack exact churn evidence or guardrails;
  - redacts secrets on errors.

- `benchmarks/early_buyer_churn_prospective_v1/run.py`
  - accepts exactly the five frozen prior runs for identity exclusion;
  - uses exactly the four preregistered Participant Quality history runs;
  - rejects a fresh run whose name/path/route-input identity matches any prior run;
  - requires the fresh run to be strictly later than every frozen prior capture;
  - evaluates the churn value stored in the prospective snapshot, not a post-hoc recomputation;
  - revalidates parity, snapshot ordering and route reconstruction;
  - applies the frozen minimum-sample and KEEP rules exactly once.

No fresh live acquisition is authorized merely by this tooling change. External market-ingest/route-provider health must be re-established before spending the single preregistered 900-second fresh confirmation.

## Early Buyer Churn Prospective V1 — provider-health gate before fresh capture

Local tooling verification on the prior prospective head passed 26/26 targeted tests.

A new outcome-blind provider-health gate is now required before the single preregistered 900-second fresh confirmation.

Provider preflight:

`benchmarks/early_buyer_churn_prospective_v1/provider_preflight.py`

It validates, without opening an economic outcome:

- the exact PASS parity artifact;
- Solana public Standard WSS subscriptions + slot notification;
- no per-transaction HTTP hydration on market ingest;
- a non-Helius RPC candidate for control-balance reads;
- the frozen public control identity and minimum USDC/SOL floors;
- Jupiter read-only candidate transaction assembly for the known-liquid control and representative burst fixture;
- no signing, submission, private key, provider execute, or fresh-confirmation consumption.

RPC candidate policy for this gate:

1. configured `SOLANA_RPC_URL`, only if non-Helius;
2. configured `SOLANA_RPC_FALLBACK_URLS`, excluding Helius;
3. public `api.mainnet-beta.solana.com` fallback.

The first candidate that passes the frozen funded-control/Jupiter assembly preflight is selected. Only the safe host and candidate index are persisted; raw credential-bearing RPC URLs are not written to the preflight artifact.

Fresh wrapper changes:

- requires a PASS provider-health artifact before capture;
- re-runs the same provider-health checks immediately before the fresh acquisition;
- requires the same selected RPC host as the approved preflight artifact;
- fixes that RPC endpoint for the full fresh run (no in-run provider switch);
- uses Solana public Standard WSS for market ingest;
- reuses the exact frozen public control through `EXACT_PREFLIGHT_REUSE`;
- disables Helius market-ingest and Helius control-discovery paths for this confirmation;
- keeps the exact churn feature, route contract and Fixed+60 primary endpoint unchanged.

The fresh evaluator independently re-opens the provider preflight artifact and checks the same non-Helius/public-WSS/control-reuse guardrails before accepting the capture as valid evidence.

A provider-health FAIL does NOT consume the fresh confirmation and must not trigger a 900-second live run.

## Early Buyer Churn Prospective V1 — provider preflight follow-up after frozen taker depletion

Outcome-blind provider preflight result:

`FAIL_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PROVIDER_PREFLIGHT`

Valid gates:

- exact parity: PASS, 2056/2056;
- public Solana Standard WSS: PASS;
- 3 subscription acknowledgements;
- slot notification observed;
- no market-ingest HTTP hydration;
- economic outcomes remained closed;
- fresh confirmation not consumed;
- Helius dependency inactive.

Failure cause:

- the frozen `JUPITER_TAKER_PUBLIC_KEY` had 0 USDC and 0 SOL;
- minimum input and SOL balance gates failed;
- Jupiter assembly probes were not run by the funded-taker preflight.

Follow-up read-only diagnostic confirmed:

- the zero-balance frozen taker can still receive Jupiter quote fields but cannot receive assembled transactions;
- known-liquid control returned `Missing associated token account`;
- representative burst returned `Insufficient funds`;
- public funded-control discovery through the Solana public RPC failed with HTTP 429.

Because the frozen route contract explicitly requires an assembled entry transaction, quote-only evidence cannot replace this gate without changing the outcome contract. The route contract therefore remains unchanged.

Provider-health architecture is updated, systems-only:

1. never use the depleted frozen taker as the fresh simulation control;
2. for each non-Helius RPC candidate, discover a public USDC owner meeting the frozen USDC and SOL floors;
3. require Jupiter to assemble both the known-liquid control and representative burst candidate transactions for that exact public owner;
4. persist only the owner SHA-256 + balances + safe RPC host, never the raw public control address;
5. return the raw public address only in-process for immediate `EXACT_PREFLIGHT_REUSE`;
6. fresh live re-runs provider health immediately before capture and reuses the exact discovered control;
7. if the approved RPC host changes or discovery/assembly fails, abort before consuming the 900-second fresh.

RPC candidate order:

- configured non-Helius `SOLANA_RPC_URL`;
- configured non-Helius `SOLANA_RPC_FALLBACK_URLS`;
- public dRPC Solana endpoint `https://solana.drpc.org/`;
- Solana public mainnet RPC.

The dRPC fallback is systems infrastructure only. It does not change churn, Participant Quality, the route contract, Fixed+60 outcomes, thresholds or selector semantics.

