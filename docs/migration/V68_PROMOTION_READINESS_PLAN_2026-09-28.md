# V68 Promotion Readiness Plan — 2026-09-28

## Purpose

`route_research_v68_release.py` currently sets:

```python
V68_SIGNAL_PLANE_PROMOTION_AUTHORIZED = False
```

This document lists exactly what remains, per `docs/v68-signal-plane-migration-v0-2026-09-22.md`, before that blocker can be lifted and a fresh V68 acquisition key authorized. It exists so an operator can decide on infra/cost/timing without an agent guessing or starting live network activity unattended.

This plan proposes no code change and authorizes nothing by itself.

## Status snapshot

| # | Step | Status | Needs live network? |
|---|---|---|---|
| 1 | Offline Rust -> episode-identity bridge audit | **DONE** — `PASS_V68_SIGNAL_PLANE_BRIDGE_V0`, 2026-09-28, see `RESEARCH_STATE_LEDGER_2026-09-27.md` | No |
| 2 | V5 120s live smoke on unrestricted internet | Not started | Yes |
| 3 | V5 sustained soak (zero drops, bounded queue, 100% trigger parity) | Not started | Yes, long-running |
| 4 | V5 Research Plane bridge smoke (zero overflow, >=1 new episode admission) | Not started | Yes |
| 5 | Verify Research Plane reconstructs frozen V55/V68 features without clock violations | Not started | Depends on step 4 data |
| 6 | Attach hazard/Jupiter/forward-outcome workers to the injected admission callback | Not started | No (wiring), yes to validate |
| 7 | Systems-only end-to-end run with a non-V68 run key | Not started | Yes |
| 8 | Authorize a fresh V68 key | Blocked on 2-7 | N/A |

Step 1 does not de-risk or shorten steps 2-8. Each remains an independent gate.

## Why steps 2-8 were not started tonight

- They require sustained outbound connections to Pump/PumpSwap/Solana RPC/WSS and, later, Jupiter — this remote cloud container's network policy and session lifetime are not something to assume are adequate for an unattended multi-hour live capture.
- A prior handoff reference to a "V7 final-head 1800s soak PASS" could not be independently located as an artifact during migration (see `RESEARCH_STATE_LEDGER_2026-09-27.md`), so no duration assumption should be carried forward without re-confirming it.
- Live steps may hit rate-limited/paid providers. Starting them without the operator present risks cost or quota consumption nobody is watching.
- `CLAUDE.md` gates any Rust hot-path or acquisition-semantics change behind new systems evidence, and steps 2-7 are exactly that evidence-gathering — not something to shortcut.

## What the operator needs to decide before steps 2-7 run

1. **Where** they run: this container, or a machine/VPS with stable, sustained Solana RPC/WSS access.
2. **Duration** for step 3 (sustained soak) — confirm or replace the referenced-but-unconfirmed 1800s figure.
3. **Provider budget** — Pump/PumpSwap/Jupiter/RPC call volume expected for a multi-hour soak plus the eventual V68 acquisition window (A>=30, B>=30 causal rows).
4. **Monitoring** — who watches the run for the zero-drop / zero-overflow / 100%-parity gates while it's live, since a systems failure mid-run produces no economic verdict and cannot be patched after the fact per the frozen protocol.

## Recommended next action

Do steps 2-7 only as an explicit, attended session once the above is decided — not as unattended background work. Until then, V68 economic status remains `NOT_EVALUATED`, unchanged from before tonight.
