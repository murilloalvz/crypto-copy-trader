# PumpSwap authoritative-writer Tailfix V8

V8 keeps the V6 per-asset partial order and all frozen systems/economic semantics. The correction
has two structural parts:

1. The authoritative PumpSwap observation batch now enters the existing shared SQLite admission
   gate as `CAUSAL`. Resolver mapping writes remain `RESOLUTION`, with the existing bounded fairness
   rule. The physical PumpSwap writer remains one dedicated thread and only one SQLite write stage
   can be active through the shared gate.
2. For batches with distinct transaction keys, canonical affected-token readback is performed by
   one indexed `IN` query instead of one query per item. Duplicate transaction keys retain the
   legacy per-item readback so replay results cannot observe a later duplicate prematurely.

The active PumpSwap authoritative queue does not contain continuation/audit rows; those use a
separate continuation writer. Therefore no unsafe priority reordering of authoritative results is
introduced. Durable-before-publication, canonical replay conflict rules, as-of timestamps,
reservation superset fail-closed behavior and same-asset scheduling remain unchanged.
