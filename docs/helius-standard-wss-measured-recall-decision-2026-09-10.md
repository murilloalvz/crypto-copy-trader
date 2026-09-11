# Helius Free Standard WSS — measured recall decision (2026-09-10)

## Decision

**KEEP AS LOW-LATENCY OPERATIONAL FEED; REJECT AS SOLE COMPLETENESS / COHORT-DENOMINATOR REFERENCE.**

This is a systems/coverage decision only. No economic edge was evaluated.

## Valid measured window

Source shadow: `cache-shadow-60s.jsonl` (collection stopped at the 10,000-notification cap).

Independent finalized reference:

- method: `getBlocks + getBlock(transactionDetails=accounts)`;
- commitment: `finalized`;
- slots: 445762584..445762610 inclusive;
- finalized slots requested/fetched: 27/27;
- request errors: 0;
- complete truth enumeration: true;
- WSS unique signatures: 9,991.

### Pump

- finalized program-mention signatures: 4,194;
- WSS intersection: 3,925;
- missed finalized signatures: 269;
- finalized signature recall: 93.5861%;
- finalized-success truth signatures: 482;
- finalized-success seen by WSS: 436;
- finalized-success signature recall: 90.4564%;
- WSS processed signatures absent from finalized truth: 0.

### PumpSwap

- finalized program-mention signatures: 6,473;
- WSS intersection: 6,075;
- missed finalized signatures: 398;
- finalized signature recall: 93.8514%;
- finalized-success truth signatures: 4,220;
- finalized-success seen by WSS: 3,949;
- finalized-success signature recall: 93.5782%;
- WSS processed signatures absent from finalized truth: 0.

Classification: `MEASURED_WSS_FINALIZED_SIGNATURE_GAPS`.

## What this proves

In this bounded window, Standard WSS did not observe every finalized transaction whose account keys mentioned Pump or PumpSwap. The gap is therefore no longer an authentication artifact or an incomplete-reference artifact.

The absence of WSS-only processed signatures in this window means this sample does not provide evidence of processed notifications later disappearing from finalized truth. It does **not** prove that such rollbacks can never occur.

## What this does NOT prove

This is program-account-mention signature recall, not semantic target-event recall. A missed program-mention signature may or may not contain a target Pump/PumpSwap instruction/event used by the bot. Conversely, semantic completeness cannot be inferred from a program mention alone.

This short window also does not establish a stable long-run provider recall percentage.

## Required follow-up before provider replacement

1. Run the existing boundary-safe audit, excluding the first/last observed slots.
2. Diagnose whether interior misses are distributed or concentrated in specific slots/patterns.
3. Build/execute semantic target-event recall for the exact events needed by Market-First and Launch Burst, especially Pump `Create/CreateV2`.
4. Repeat over independent live windows.
5. Compare an alternative acquisition source only against the same semantic truth definition before paying for or rewriting the provider boundary.

## Architecture consequence now

Standard WSS may remain the real-time trigger/feed path because its operational behavior was healthy and the Carbon live payload path already decoded successfully. But any scientific statement that requires a complete denominator — for example “all covered launches” — must use an independent completeness/reference layer or a source that proves the required semantic recall.
