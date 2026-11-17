# V68 Signal Plane Migration V0 — 2026-09-22

Status: **migration in progress; V68 fresh acquisition is blocked by release readiness**.

## Goal

Replace only the old market-acquisition / Radar hot path while preserving the frozen economic
contract above the episode-admission boundary.

Target architecture:

```text
Solana Pump + PumpSwap
        |
        v
Carbon canonical decode
        |
        v
Rust Signal Plane V5
        |
        +---------------------------> live trigger
        |
        +--> ordered async Research Plane
                  |
                  +--> durable trade/lifecycle observations
                  |
                  +--> frozen episode identity
                  |
                  +--> opportunity admission
                              |
                              v
                      hazard / Jupiter entry
                              |
                              v
                      frozen route outcomes
                              |
                              v
                          V68 evaluator
```

## Already implemented

### 1. Rust V5 hot path

- ordered `signal_batch` transport;
- Rust mutates one frozen indexed state sequentially in exact record order;
- Python parity moved out of the live hot path;
- post-run Python replay still requires exact 100% trigger parity.

### 2. Frozen episode-identity bridge

`src/signal_plane_episode_bridge_v0.py`

Preserves the historical trigger identity used by the existing durable bridges:

- Pump:
  `market-radar:pump:{transaction_signature}:{token_mint}`
  with durable venue `pump_bonding_curve`;
- PumpSwap:
  `market-radar:pumpswap-v3:{transaction_signature}:{token_mint}`
  with durable venue `pump_swap`.

The bridge fails closed on token mismatch, as-of mismatch, missing transaction identity, unexpected
Radar version, or unsupported venue.

### 3. Admission sink

`src/signal_plane_episode_admission_v0.py`

Converts a Rust trigger snapshot back to the frozen `MarketMovementTrigger`, assigns the durable
episode using the bridge above, and calls the same `admit_opportunity_episode` contract used by
the historical research path.

The admission callback is injectable so the future V68 runner can attach hazard/research queues
without changing episode semantics.

### 4. Ordered Research Plane persistence

`src/signal_plane_research_persistence_v0.py`

For every Signal Plane record, the Research Plane:

1. persists the canonical trade/lifecycle observation;
2. only then persists/admit a trigger episode from that observation.

The Research Plane is structurally decoupled from benchmark types through a Protocol contract.

### 5. V5 live bridge modes

The V5 shadow supports systems-only bridge validation:

- `--episode-bridge-run-key`: episode/admission durability only;
- `--research-plane-run-key`: ordered full observation durability + trigger episode admission.

The two modes are mutually exclusive and must never use a V68 fresh key.

Both run outside the live Rust Signal Plane hot path through bounded async queues.

### 6. Offline bridge audit

`python -m benchmarks.v68_signal_plane_bridge_v0.run`

The audit generates the frozen deterministic trace, runs Rust, requires Rust/Python trigger parity,
reconstructs Rust triggers, and verifies that every triggered Pump/PumpSwap trade maps to the
historical episode identity contract.

This audit is systems-only and cannot authorize V68 by itself.

### 7. V68 fail-closed release

`route_research_v68_release.py` now:

- validates the Signal Plane episode bridge contract offline;
- contains an explicit `V68_SIGNAL_PLANE_PROMOTION_AUTHORIZED = False` blocker;
- aligns provider-health probes with the stable server-heartbeat WSS policy;
- probes Pump and PumpSwap concurrently.

A fresh V68 acquisition cannot start until promotion is explicitly authorized after the remaining
systems evidence.

## Remaining promotion evidence

Before the blocker may be removed:

1. offline bridge audit PASS;
2. V5 120s live smoke PASS on unrestricted internet;
3. V5 sustained soak PASS with:
   - zero ingress drops;
   - bounded queue;
   - full reader duration;
   - exact Rust batch accounting;
   - complete post-run Python audit;
   - 100% trigger parity;
4. V5 Research Plane bridge smoke PASS with:
   - zero research queue overflow/errors;
   - every live Signal Plane record durably accounted;
   - at least one new episode admission;
5. verify that the persisted Research Plane reconstructs the frozen V55/V68 causal features without
   feature-clock violations;
6. attach the existing hazard/Jupiter/forward-outcome workers to the injected admission callback;
7. run a systems-only end-to-end bridge with a **non-V68** run key;
8. only then authorize a new fresh V68 key.

## Scientific guardrails

Do not:

- reuse V68 -01/-02 keys;
- run V68 -03 through the historical v46/v44/v43/v42 hot path;
- change V68 Flow60 bins, support minima, horizon or route economics;
- backfill current context into old T0;
- promote a systems PASS into economic edge;
- use school-network failures as economic evidence.
