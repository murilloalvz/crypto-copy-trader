# PumpSwap Opportunity-Asset Orientation Incident / Participant Quality Memory V1 — 2026-09-24

Mode: PAPER / RESEARCH / READ ONLY

## Root cause

The M2R2 Research Plane worker error was captured as:

`ValueError: input_mint and output_mint must differ`

The failed episode token was the canonical USDC mint. The Research entry route therefore attempted
USDC -> USDC and correctly refused to call Jupiter.

The upstream cause was a semantic mismatch between two PumpSwap paths:

- the historical normalized PumpSwap persistence path already resolves the opportunity asset as the
  single non-reference side (WSOL/USDC are reference assets) and inverts BUY/SELL when the
  opportunity asset is the pool quote side;
- the Carbon -> Signal Plane market-trade adapter was still forwarding the pool base mint and raw
  base-relative side directly.

Thus reversed pools such as `base=USDC, quote=MEMECOIN` could enter the Signal Plane as USDC.

## Fix

The protocol-level matched-unit observation remains unchanged: raw quote amount/reserve facts retain
their native pool quote units.

Only opportunity semantics are normalized:

1. Carbon PumpSwap MarketTrade observations resolve `base/quote` through the existing
   `classify_pumpswap_opportunity_asset` policy.
2. The non-reference asset becomes the Signal Plane `token_mint`.
3. BUY/SELL is inverted when that opportunity asset is the quote side.
4. PumpSwap lifecycle observations use the same opportunity-asset policy.
5. The durable Signal Plane episode bridge rejects WSOL/USDC as PumpSwap opportunity targets as
   defense in depth.
6. ambiguous two-reference or two-unknown pairs remain filtered rather than guessed.

Rust detector logic and thresholds are unchanged.

## Scientific disposition of old memory epoch

Because this correction changes token identity before Signal Plane detection, all Participant Quality
memory cohorts acquired before the fix are ineligible for the post-fix memory experiment, including
the technically successful old M1.

This is not an economic rejection. No P&L, cutoff or Participant Quality outcome was used.

The old artifacts remain preserved for incident audit only.

## New clean memory epoch

A new Participant Quality Memory V1 must start from a fresh base key and collect exactly four valid
cohorts under corrected PumpSwap opportunity semantics.

History used by the V1 feature is restricted to prior valid cohorts inside this same clean epoch:

- M1: no prior clean-epoch history;
- M2: M1 only;
- M3: M1 + M2 only;
- M4: M1 + M2 + M3 only.

Pre-fix route-research history is excluded from the V1 feature even when otherwise causal, because its
PumpSwap opportunity identity may have been oriented differently.

All original coverage gates remain:

- M4 feature availability >= 50%;
- aggregate available M2+M3+M4 >= 30;
- cutoff is the outcome-blind median of M2+M3+M4 feature values only;
- favorable direction remains HIGH;
- no economic edge verdict is authorized by memory readiness.

## Next step

Run the new clean four-cohort memory epoch. If READY, preregister a separate prospective economic
holdout before collecting validation outcomes.
