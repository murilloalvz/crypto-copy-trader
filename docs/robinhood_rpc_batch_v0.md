# Robinhood RPC Batch V0

Status: **implemented read-only transport optimization**.

Direct Quote V0 reads several independent Pons curve views at one pinned block. `BatchRpcClientV0` preserves exactly the same state semantics while sending those `eth_call`s in one JSON-RPC batch request.

## Why

A snipe-enabled direct quote needs seven independent curve views:

- `feeBps()`;
- `creatorTaxBps()`;
- `getReserves()`;
- `sellableTokens()`;
- `readyToGraduate()`;
- `graduated()`;
- `currentSnipeTaxBps(recipient)`.

Sequential HTTP requests add avoidable provider/network latency to a 5-second research surface. Batch V0 reduces those seven view calls to one HTTP round trip. The surrounding block-number, block-header, and bytecode checks remain explicit and unchanged.

## Order safety

JSON-RPC does not require batch responses to preserve request order. Batch V0 therefore never trusts array position.

Every subrequest receives a unique JSON-RPC `id`. Responses are reconstructed strictly by that id. The whole batch fails on:

- duplicate response IDs;
- missing response IDs;
- unexpected response IDs;
- malformed response items;
- response count mismatch;
- any per-item RPC error;
- missing `result` fields.

The client records whether the provider reordered the response.

## Pinned-state semantics

`read_curve_quote_state_v0` still:

1. captures one explicit latest block number;
2. reads its block hash;
3. verifies bytecode exists at the target curve;
4. reads all curve state at that same block tag;
5. re-reads the same block header;
6. rejects the sample if the block hash changed.

The only transport difference is step 4: clients with `batch_call` use `JSON_RPC_BATCH`; other clients retain `SEQUENTIAL_JSON_RPC` fallback.

Both modes decode into the same `PonsCurveQuoteStateV0` contract. The evidence records `transport_mode` and, in batch mode, request count, service time, request IDs, response IDs, and whether the provider reordered the array.

## Scientific guard

Batch V0 changes transport latency only. It must never change:

- block tag;
- feature semantics;
- fee/snipe interpretation;
- graduation guards;
- quote math;
- selector state;
- economic outcome state.

The test suite proves batch/sequential state parity and deliberately feeds reversed batch responses to verify id-based reconstruction.
