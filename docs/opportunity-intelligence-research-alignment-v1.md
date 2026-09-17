# Opportunity Intelligence Research Alignment V1

Status: research architecture only. This document does not change any frozen selector, route contract, exit contract, or economic verdict.

## Why this alignment exists

The recent Solana experiments established three useful negatives: simple early acceleration did not show a convincing return association, simple reserve/curve geometry did not strongly predict routeability, and a material part of entry unavailability is execution/provider infrastructure rather than token quality. At the same time, external research and production tooling consistently separate token quality, participant quality, and the ability to copy/execute a trade.

The project therefore stops treating one score or one selector as the place where every problem must be solved.

## Canonical decision dimensions

1. Manipulation / Risk — coordinated wallets, bundlers, insiders, deployer behavior, wash/churn and concentration.
2. Organic Demand — independent net buyers, persistent participation and demand that survives beyond the first burst.
3. Opportunity / Alpha — among feasible entries, does causal evidence predict a better economic outcome?
4. Copyability / Execution — can our own order be entered/exited under real chain/protocol/provider constraints?
5. Wallet Intelligence — is the trader/deployer historically informative using only evidence available before the current decision?

These dimensions remain separate evidence channels. A future decision engine may combine independently validated outputs, but a single opaque Candidate Score is not the research target.

Market-First and Social/Event-First remain independent. Convergence is a later hypothesis, not an assumption.

## What external work changes

### MELT-style coordination research

The important lesson is methodological, not a model transplant: an address is not assumed to equal an economic entity. The next Solana manipulation/organicity discovery should study entity-adjusted buyer breadth and concentration, early-buyer retention, sell pressure and coordination/wash proxies from causal evidence. No MELT threshold or trained model is inherited.

### GMGN / wallet tooling

Track record and copy-tradeability are different questions. External wallet labels can bootstrap Research Plane analysis, but are not accepted into the Signal Plane unless their causal availability, semantics and stability are independently verified.

### Copy-trading research

Wallet history, token properties and copier timing/cost should be modeled separately. Prior-only wallet history is allowed; future wallet performance or same-trade outcome leakage is not.

### Jupiter / Solana Tracker style labels

Organic/smart-money/insider/bundler labels are useful research labels and benchmarking aids. They are not automatically causal 5-second selector inputs. Longer-window organic-demand research should be a separate detector rather than forcing every signal into the launch window.

## Solana sequence

1. Finish `market_first_routeable_edge_discovery_v2` on the existing frozen capture.
2. Build Coordination / Organicity V0 with entity-adjusted features. Discovery only; no threshold sweep.
3. Build Wallet Intelligence V0 from prior-only history, initially in Research Plane.
4. Build a longer-window Organic Follow-up detector separately from the 5-second launch detector.
5. If one mechanically sensible alpha candidate survives robustness checks, freeze it before a fresh independent route-shadow capture.
6. Only after prospective evidence revisit live execution or new exit optimization.

Current Sniper V1 remains frozen and is not retuned.

## Robinhood Chain sequence

Robinhood is not a Solana clone. Its execution model is chain-native:

- low-latency observation should use the Nitro sequencer feed;
- RPC becomes reconciliation, historical reads and fallback rather than the primary Signal Plane;
- first-come-first-served sequencing means higher gas is not a priority-bid mechanism;
- Pons opening tax / phase / protocol caps and dry-run quoteability belong to Copyability / Execution, not Alpha;
- deployer/entity coordination and wallet history should be adapted to EVM/Pons evidence rather than inheriting Solana wallet thresholds.

Selective reuse plan:

- source `feat/robinhood-sequencer-shadow-v0` at `b99b6cb96a7c9c9db46b706816cdc3379f19ecdf` for raw Nitro feed capture and first-received clocks;
- source `research/robinhood-launch-burst-v0` at `295550e00e167d963d8ce1870f0fa4c502a99963` for factory/launch/curve decoding and existing route research;
- port those components behind the current causal/scientific contracts instead of merging the old branch wholesale;
- do not inherit Solana thresholds, fees, exit policy, provider semantics, five-second window, or priority-fee assumptions.

Robinhood order of work:

1. Sequencer Feed Signal Plane V1.
2. Pons launch adapter on sequencer-observed evidence with RPC reconciliation.
3. Protocol Opening Copyability V0: live snipe tax, quote/slippage, phase/caps and dry-run feasibility.
4. Coordination / Organicity discovery adapted to Pons/EVM.
5. Wallet/deployer intelligence from prior-only history.
6. Routeable-only alpha shadow.
7. Freeze a candidate and acquire a fresh prospective sample.

## What is deliberately not being done

- no cross-chain threshold reuse;
- no threshold search on the current Solana sample to rescue a negative result;
- no ML/autotuning while route-usable labeled samples are tiny;
- no provider/post-decision execution field promoted into a Market-First selector;
- no Social/Event-First merge without independent evidence;
- no new exit optimization before entry alpha has a prospective candidate;
- no paid low-latency infrastructure upgrade merely to execute a negative-expectancy strategy faster.

## Near-term success criteria

Solana succeeds at the next research stage if a causal feature family shows a mechanically plausible and robustness-resistant association with Fixed+60 among route-usable entries, then survives a separately frozen fresh sample.

Robinhood succeeds first at SYSTEMS/SCIENTIFIC level if sequencer-observed launch evidence can be causally decoded, reconciled against canonical chain state, and paired with protocol-native copyability diagnostics without gaps or post-decision leakage. Economic validation comes later.
