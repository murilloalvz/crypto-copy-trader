# Helius Standard WSS — boundary-safe finalized signature recall

Date: 2026-09-10

## Decision

**KEEP Helius Free Standard WSS** as the current Solana acquisition baseline for Pump and PumpSwap at the **program-mention signature layer**.

This is not a claim of chain-complete semantic event coverage, economic edge, or provider equivalence to Yellowstone/LaserStream gRPC.

## Source shadow

- Source: `artifacts/helius_standard_wss_shadow_v0/cache-shadow-60s.jsonl`
- Collector commitment: `processed`
- Run stopped at the 10,000 notification cap after ~19.755 s rather than at a clean slot boundary.
- Full observed slot range: 445762584–445762610 inclusive.

## Independent finalized reference

The finalized reconciler fetched all 27 finalized slots in the observed slot range with zero request errors.

Full-window raw comparison initially reported:

- Pump: 3925 / 4194 = 93.5861% finalized signature recall, 269 missed.
- PumpSwap: 6075 / 6473 = 93.8514% finalized signature recall, 398 missed.
- WSS processed signatures absent from finalized truth: 0 for Pump and 0 for PumpSwap.

Because collection may start and end mid-slot, the first and last observed slots were not valid completeness boundaries.

## Boundary-safe audit

Excluded slots:

- 445762584
- 445762610

Interior window:

- 445762585–445762609
- 25 complete interior slots

Result:

### Pump

- finalized truth signatures: 3655
- WSS intersection: 3655
- missed: 0
- finalized signature recall: **100.0%**
- finalized successful truth signatures: 419
- successful seen by WSS: 419
- finalized successful signature recall: **100.0%**
- WSS processed absent from finalized truth: 0

### PumpSwap

- finalized truth signatures: 5983
- WSS intersection: 5983
- missed: 0
- finalized signature recall: **100.0%**
- finalized successful truth signatures: 3902
- successful seen by WSS: 3902
- finalized successful signature recall: **100.0%**
- WSS processed absent from finalized truth: 0

All 269 Pump and all 398 PumpSwap full-window misses disappeared after removing the two partial boundary slots. No interior slot had a miss.

Classification:

`PASS_BOUNDARY_SAFE_FINALIZED_SIGNATURE_RECALL_REFERENCE`

## Scientific boundary

This result establishes strong evidence that Helius Free Standard WSS did not miss Pump/PumpSwap **program-mention signatures** in this 25-slot interior sample.

It does **not** establish:

- chain-complete coverage across arbitrary time periods;
- target instruction/event semantic recall;
- semantic decoder parity with a different provider;
- provider-latency equivalence to gRPC streaming;
- continuous zero-intensity coverage;
- economic edge.

Do not infer target event recall directly from program-account mention recall.

## Architecture consequence

Do not replace Helius Free Standard WSS or pay for a different datasource solely because of the earlier ~93–94% raw full-window number. That deficit was entirely explained by partial slot boundaries in this sample.

Keep the existing datasource and move the next infrastructure experiment to measured PumpSwap pool-identity lookup latency using the already available Helius RPC + Carbon account decoder path.
