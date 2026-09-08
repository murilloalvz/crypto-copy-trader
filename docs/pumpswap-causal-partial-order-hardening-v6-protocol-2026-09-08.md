# PumpSwap Causal Partial-Order Hardening V6

Mode: **PAPER / RESEARCH / READ ONLY**

## Root cause

V5 corrected duplicate pool-identity normalization, but reservation admission still waited for a
contiguous PumpSwap ingress prefix. One slow normalization at sequence `i` therefore withheld every
reservation after `i`, including notifications whose normalized assets were disjoint. The blocked
reservations accumulated in the stateful/demoted ready path; small finalizer service and healthy
RPC clocks show that this was HOL amplification, not a finalizer or RPC ceiling failure.

## Structural correction

V6 admits a reservation as soon as its causal normalization hint is available. The existing
`ReadyAssetScheduler` remains authoritative for tickets, skips, completion, and demotion:

- each asset has one ticket chain;
- an admission waits only for the previous admitted reservation touching that asset;
- disjoint assets have no dependency edge and can become ready independently;
- multi-asset reservations wait for every predecessor chain;
- proven demoted work still enters the existing demoted queue and stateful-ready priority is unchanged;
- the SQLite writer is still asynchronous, single-physical-writer, and guarded by the canonical
  result's reservation-superset check.

The deliberate contract is causal-admission order per asset. V6 does not claim ingress FIFO when
the earlier notification has not yet completed causal normalization. The graph records every edge,
rejects duplicate sequence admission, and proves acyclicity because every edge points to an earlier
reservation identity.

## Frozen constraints

Detector, V68 definitions, economics, provider pacing, RPC concurrency ceiling, official 5-second
gate, SQLite writer count, replay/as-of rules and persistence semantics are unchanged.

## Acceptance

Run CI first, then exactly one fresh 120-second systems-only run with
`route_research_systems_stability_tailfix_v6.py`. A systems result is not promotable if the frozen
11/11 gate fails, V5 latency/writer headroom warns, or V6 graph evidence is missing.
