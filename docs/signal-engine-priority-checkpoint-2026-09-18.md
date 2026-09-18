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
