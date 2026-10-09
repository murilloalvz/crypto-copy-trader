# PumpSwap Tailfix V9 — early causal acknowledgement and audit isolation

## Problem proved by V8

V8 moved authoritative persistence into causal SQLite admission, but its live still showed a
large post-submit tail. The active V34/V42/V51 scheduler already proved many pending payloads to be
continuation-only, consumed their asset tickets, and then placed those payloads back into the shared
stateful ready queue solely to run the continuation audit/finalizer acknowledgement.

That left proven no-op work occupying the causal ready path. V8 reported 913 proven demotions,
471 demoted acknowledgements pending at close, and a demoted-ready p95 of about 33s. Finalizer
service itself remained sub-millisecond.

## V9 correction

V9 adds an opt-in handler to `DemotingReadyAssetSchedulerV34`:

1. the existing proof remains unchanged;
2. the proven payload is submitted to a bounded audit-only queue;
3. the per-asset ticket is consumed immediately, including contiguous skipped tickets;
4. the payload is not inserted into the stateful ready queue;
5. the existing PumpSwap finalizer task/executor multiplexes the bounded audit queue, with causal
   ready work preferred and a bounded fairness turn for audit; no worker or executor capacity is
   added;
6. audit queue overflow, worker failure, or deadline backlog remains visible/fail-closed.

The handler is installed only by the V9 systems wrapper. Without it, V34/V51 retain their prior
ready-queue behavior.

## Safety argument

The handler is called only after `should_remain_stateful(payload)` returns false. The V27 proof
requires every trigger-bearing token to already have an immutable run-local canonical episode at
its causal `token_as_of`; therefore the finalizer can only append continuation audit rows and return
the existing canonical hit. No episode opener, first-trigger replacement, replay conflict, or
stateful mutation is moved to the audit lane.

Same-asset state-changing work still waits on the same completed ticket cursor. Disjoint assets
remain independent. Multi-asset work is released only after every asset ticket is causally consumed.
Audit durability remains mandatory and no audit item is dropped on queue pressure.

The audit queue is bounded by the existing PumpSwap queue limit. A full queue is rejected before
the causal ticket is consumed, so admission fails closed. At deadline, queued or in-service audit
work is reported as an error/missingness condition rather than silently discarded.
