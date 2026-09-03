# Causal Opportunity Acquisition v1 — SUPERSEDED BEFORE RUN

Date: 2026-09-03

Mode: **RESEARCH / READ ONLY / HISTORICAL PROTOCOL**

Status: **SUPERSEDED BEFORE ANY ACQUISITION RUN STARTED**.

This protocol proposed using the 27-wallet research universe as the mandatory source of opportunity triggers. No 12h run was started under that design.

The Wallet Forward v2 closeout showed that waiting for a small set of wallet actions is itself an acquisition bottleneck. Before collecting new evidence, the trigger architecture was therefore changed from:

`wallet BUY -> opportunity episode`

to:

`market activity changes state -> opportunity episode -> wallet context as a feature`

The active preregistered protocol is:

`docs/market-opportunity-radar-v1-protocol-2026-09-03.md`

The complete original wallet-triggered protocol remains available in Git history prior to this supersession commit.

## Methodological reason for supersession

This is not parameter tuning based on new P&L. The wallet-triggered acquisition run never began. The change is an explicit redesign of the **sampling mechanism** after the prior Wallet Forward v2 experiment ended with `OUTCOME D — TOO LITTLE ECONOMIC SAMPLE`.

Wallet intelligence remains in the research system, but tracked-wallet participation is no longer required for a token-market movement to enter the acquisition sample.

## Do not run

Do **not** launch the 12h acquisition procedure described in the historical version of this file. Implement and smoke-test Market Opportunity Radar v1 first.