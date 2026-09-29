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
| 2 | V5 120s live smoke on unrestricted internet | **DONE** — `PASS_RUST_SIGNAL_PLANE_LIVE_SHADOW_V7_RUST_HOTPATH`, 2026-09-28, see `RESEARCH_STATE_LEDGER_2026-09-27.md` | No (already run) |
| 3 | V5 sustained soak (zero drops, bounded queue, 100% trigger parity) | **2 attempts, both FAIL** — public RPC capacity insufficient (WSS drop, then RPC batch errors); see `RESEARCH_STATE_LEDGER_2026-09-27.md`. Needs a dedicated RPC (e.g. Helius). | Yes, long-running |
| 4 | V5 Research Plane bridge smoke (zero overflow, >=1 new episode admission) | Not started; **also blocked on `JUPITER_API_KEY`** — discovered 2026-09-28 while running the Participant Quality memory build, which reuses this same bridge (`signal_plane_route_research_coordinator_v0`): with no Jupiter key, every entry attempt returns `config_missing` and zero research decisions ever freeze (`FAIL_SIGNAL_PLANE_ROUTE_RESEARCH_BRIDGE_V0`). Read-only route quotes, no funded execution. | Yes |
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

## Step 2 exact execution plan (V5 120s live smoke)

Traced from the actual code, not guessed. `live_shadow.py`'s `DEFAULT_DURATION_SECONDS = 120.0` is exactly the "V5 120s live smoke" the migration doc refers to.

### Precondition: `live_shadow.py` requires a PumpSwap identity bootstrap report

`run_live_shadow_v0` calls `load_bootstrap_evidence_v0(bootstrap_report)` (`benchmarks/market_first_live_discovery_v0/contracts.py`), which requires a report with `classification == PASS_PUMPSWAP_IDENTITY_BOOTSTRAP_V0`, `valid_bootstrap == true`, `chain_complete_coverage_claimed == false`, and at least one decoded PumpSwap pool identity. That report is produced by a separate, smaller live step: `benchmarks/pumpswap_identity_bootstrap_v0/bootstrap.py` (`WARMUP_SECONDS = 60`, i.e. a ~60s live warmup against Pump/PumpSwap WSS logs before the 120s smoke can even start).

### Command sequence

```bash
# 0. one-time per fresh container: this repo's Rust crates pin rust-version = 1.96.1
rustup toolchain install 1.96.1
rustup default 1.96.1

# 1. PumpSwap identity bootstrap (~60s live warmup, writes its own report)
export SOLANA_RPC_URL="<real RPC URL with stable WSS logsSubscribe>"
python3 -m benchmarks.pumpswap_identity_bootstrap_v0.bootstrap --cargo cargo
# -> writes artifacts/pumpswap_identity_bootstrap_v0/<bootstrap_version>-<ts>-<uuid12>/report.json
# PASS condition: report["valid_bootstrap"] == true

# 2. V5 120s live smoke, fed the bootstrap report from step 1
python3 -m benchmarks.integrated_market_signal_plane_v1.live_shadow \
  --bootstrap-report artifacts/pumpswap_identity_bootstrap_v0/<run_id_from_step_1>/report.json \
  --duration-seconds 120 \
  --cargo cargo \
  --out artifacts/rust_signal_plane_live_shadow_v7/report.json
```

Do not pass `--episode-bridge-run-key` / `--research-plane-run-key` for this smoke — those are optional systems-only bridge-validation modes (step 4, not step 2) and must never use a V68 fresh key per `docs/v68-signal-plane-migration-v0-2026-09-22.md`.

### What to check in the output report for a real PASS

- `classification` == the module's `PASS_CLASSIFICATION` (not a FAIL string)
- `trigger_parity.parity_pct == 100.0` and `trigger_parity.mismatches == 0`
- `errors` empty
- `gates` all `true`
- `scientific_thresholds_modified: false`, `economic_hypothesis_modified: false` (should always read false; if not, something touched a frozen contract and the run should not be trusted)

### Environment needed

- `SOLANA_RPC_URL` — the `.env.example` default (`https://api.mainnet.solana.com`) is a public endpoint; the identity-bootstrap benchmark is built around Helius-style standard WSS (`SOURCE_SCOPE = "helius_standard_wss_pump_pumpswap_logs"` in `contracts.py`), so a public/free RPC may not hold a stable `logsSubscribe` connection for the full window. A paid/dedicated RPC with reliable WSS is the realistic requirement — this is exactly the "provider budget" decision from the table above.
- `JUPITER_API_KEY` is not needed for this specific smoke (it only subscribes to Pump/PumpSwap logs, no Jupiter calls) — but it is required starting at step 4 (not step 6 as originally guessed here): the Research Plane bridge (`signal_plane_route_research_coordinator_v0`) attempts a Jupiter entry quote for every admitted episode, and an empty key makes every attempt return `config_missing`, so zero research decisions ever freeze. Confirmed 2026-09-28 via a real live attempt (see `RESEARCH_STATE_LEDGER_2026-09-27.md`).
- Rust toolchain 1.96.1 active (`rustup default 1.96.1`) — both `benchmarks/integrated_market_signal_plane_v1/rust_runner` and `benchmarks/pumpswap_identity_bootstrap_v0/rust_runner` pin this version. This does not persist across a fresh container; re-run the toolchain install/default if starting from a clean environment.

### Not run tonight

Nothing above was executed. It requires a real, stable `SOLANA_RPC_URL` the operator provides and an attended window to watch the live gates — both are the operator's call, not something to start unattended.

## What the operator needs to decide before steps 2-7 run

1. **Where** they run: this container, or a machine/VPS with stable, sustained Solana RPC/WSS access.
2. **Duration** for step 3 (sustained soak) — confirm or replace the referenced-but-unconfirmed 1800s figure.
3. **Provider budget** — Pump/PumpSwap/Jupiter/RPC call volume expected for a multi-hour soak plus the eventual V68 acquisition window (A>=30, B>=30 causal rows).
4. **Monitoring** — who watches the run for the zero-drop / zero-overflow / 100%-parity gates while it's live, since a systems failure mid-run produces no economic verdict and cannot be patched after the fact per the frozen protocol.

## Recommended next action

Do steps 2-7 only as an explicit, attended session once the above is decided — not as unattended background work. Until then, V68 economic status remains `NOT_EVALUATED`, unchanged from before tonight.
