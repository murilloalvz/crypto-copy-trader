# Robinhood RPC Batch V0

Status: design note only. Implementation is developed on a separate feature branch before entering the research track.

Robinhood Chain is EVM-compatible and accepts JSON-RPC. Direct Quote V0 currently reads several curve views individually. The next infrastructure optimization is to preserve the same pinned block semantics while sending those independent `eth_call`s in one JSON-RPC batch request.

The client must never rely on response order. Each request receives a unique JSON-RPC `id`; responses are reassembled by `id` and missing, duplicate, or per-item error responses fail the batch.

A batch optimization must preserve exactly the same state/evidence semantics as the sequential reader. It is a transport optimization only, not a feature or economic change.
