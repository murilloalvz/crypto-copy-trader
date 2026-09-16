# Opportunity Intelligence — Edge Registry V0

Date: 2026-09-16

## Purpose

This registry converts practical market study, existing Launch Burst research, and mechanisms commonly surfaced by serious memecoin tooling into an auditable research backlog.

It is **not a trading score** and **does not change any frozen selector policy**.

The governing order is:

1. hard safety/manipulation evidence;
2. evidence completeness;
3. causal opportunity feature vector;
4. separately frozen hypothesis selector;
5. execution admission/copyability;
6. route-shadow or funded economic evaluation.

Market-First and Social/Event-First remain independent research tracks. Any convergence rule requires a separate preregistration.

## What we already know from our own work

The frozen Launch Burst baseline proves that `signed_flow_over_event_reserve` can identify early movement under a causal 5-second window. The first route-shadow economic sample, however, was strongly unfavorable. Therefore movement detection alone is not treated as economic edge.

Sniper V1 adds causal participation-quality controls: event count, directional-flow efficiency, wallet/transaction coverage, BUY-wallet breadth and conservative concentration. Those features are preregistered screening inputs, not proven profitable filters.

The practical lesson is that the next useful layer is not another arbitrary momentum threshold. It is better evidence about manipulation, participant independence, entity quality and copyability.

## What strong bot/tool workflows suggest studying

External trading tools commonly expose mechanisms such as top-holder concentration, developer holdings/history, sniper/insider/bundle indicators, early buyers, funding links, smart-money identities, liquidity, transaction counts and buy/sell flow.

Those mechanisms are useful as **discovery hypotheses only**. Their presence in a commercial tool is not evidence that the feature produces standalone prospective edge.

The registry therefore separates each idea into one of four implementation states:

- `AVAILABLE`: already produced causally by the current pipeline;
- `DERIVABLE`: source evidence exists or the quantity can be deterministically derived, but the feature is not yet frozen/promoted;
- `NEEDS_COLLECTION`: we lack the point-in-time evidence required for a defensible feature;
- `FORBIDDEN_AS_SELECTOR`: execution/outcome information that must remain outside opportunity selection.

## Evidence levels

- `L0_EXTERNAL_HEURISTIC`: useful externally observed mechanism; no internal causal validation yet.
- `L1_CAUSALLY_MEASURABLE`: our pipeline can measure it without future leakage.
- `L2_RETROSPECTIVE_ASSOCIATION`: outcome association only; discovery evidence, not promotion.
- `L3_PREREGISTERED_PROSPECTIVE_SCREENING`: frozen before fresh outcomes.
- `L4_INDEPENDENT_PROSPECTIVE_REPLICATION`: fresh independent replication of the frozen hypothesis.
- `L5_LANDED_EXECUTION_ECONOMICS`: funded landed execution economics, not route-shadow approximation.

An evidence level is not a profitability rating.

## Research priority

### P0 — preserve causal integrity

Keep the existing feature snapshot frozen before provider quotes. Keep route/provider data out of Market-First and Social/Event-First selection. Keep future returns/PnL as outcome labels only. Social `published_at` remains metadata; causal availability is based on actual observation/mapping time.

### P1 — manipulation and fake-breadth defenses

Implement point-in-time measurements for:

- deployer/dev history and current control;
- top-holder concentration with pool/program account classification;
- early-buyer concentration;
- bundle/insider linkage with confidence;
- mint/freeze authority state;
- common-funder/coordinated-wallet clusters.

Do not choose economic thresholds while implementing the collector. First freeze deterministic definitions and measure coverage/failure modes.

### P2 — past-only entity quality

Build point-in-time wallet/source histories. A wallet or social source may only be scored using information that was already knowable at the decision cutoff. Current all-time PnL or later-discovered rug labels must never be joined backward into an old opportunity.

This is essential before testing “smart money”, influencer quality, prior-rug association or developer reputation.

### P3 — independent Social/Event-First signal

Use `social_event_evidence_v0` as the causal primitive. Candidate features include source diversity, mapped event count, novelty and past-only source reputation. Freeze and evaluate a Social/Event-First hypothesis independently from Market-First.

Only after both tracks have independent evidence should a convergence hypothesis be preregistered.

### P4 — execution admission

Route availability, provider price impact, quote stability and assembly success belong to execution/copyability. They can reject an otherwise interesting opportunity when known before signing, but they are not evidence that created the opportunity.

Fixed +60 remains the primary route-paper benchmark and SMART-LADDER-25 remains exploratory unless separately promoted.

## Promotion protocol for any new feature

1. Define semantics and causal availability before seeing fresh economic outcomes.
2. Implement deterministic extraction and coverage reporting.
3. Validate no provider/outcome leakage.
4. Run retrospective discovery only to formulate a hypothesis, not to claim edge.
5. Freeze a small selector policy with a new version/hash.
6. Acquire a fresh prospective screening sample.
7. Do not retune from that screening sample.
8. Run an independent fresh replication if screening supports the hypothesis.
9. Keep route-shadow economics distinct from funded landed execution.

## First recommended engineering slice

The first new collector should target manipulation/fake breadth rather than more price momentum:

- mint/freeze authority state;
- top-holder concentration with explicit exclusions;
- deployer/dev identity and past-only launch history;
- common-funder / related-wallet evidence where confidence is defensible.

Why this first: our current early-flow features already detect movement, while the weak point exposed by the negative route-shadow sample is whether that movement represents broadly copyable demand or a structure in which we are late liquidity.

No threshold is selected in this document. The collector and feature definitions must be frozen before a new economic hypothesis is tested.
