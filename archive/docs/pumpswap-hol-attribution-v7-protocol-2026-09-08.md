# PumpSwap remaining-HOL attribution V7

V7 is an observation-only systems run on the V6 partial-order scheduler. It does not change
detector, V68/economics, the 5s gate, RPC ceiling, same-pool single-flight, SQLite writer count,
causal/as-of/replay semantics, same-asset serialization, worker counts, or the V6 dependency graph.

The new clocks separate:

- predecessor-incomplete wait: submit until `dependency_ready`;
- shared ready-capacity wait: `dependency_ready` until finalizer dequeue;
- finalizer occupancy, including post-finalize handling;
- authoritative writer-result wait and its sample correlation with the two waits;
- dependency p95 by asset, top-five hot-asset share versus cold assets;
- submitted stateful jobs versus proven pending demotions.

The second clock cannot contain an incomplete predecessor by construction. A structural V7 fix is
not authorized by this run alone; any later change must preserve the V6 invariants and add a new
fail-closed targeted test before live execution.
