# V68 Local 1800s Soak + Promotion Report Runbook — 2026-09-29

Purpose: complete the one remaining piece of V68 step 8 that this remote sandbox cannot run
(a continuous 1800s live process — the sandbox kills all background/detached processes at a
~10-minute ceiling; see `RESEARCH_STATE_LEDGER_2026-09-27.md`, step 8 section, for the full
diagnosis).

Run this on a machine without that ceiling (your own computer, a VPS, a local Claude Code
session — anything that lets one process run uninterrupted for 30+ minutes).

All 5 promotion-report inputs are regenerated locally rather than copied from the sandbox,
because `artifacts/` is gitignored and `signal_plane_v68_promotion_v0.validate_promotion_report`
pins the exact git HEAD the evidence was produced on — regenerating on your own checkout's HEAD
is simpler and correct by construction. Steps 1-4 below are fast (well under 10 minutes combined);
only step 5 (the soak) is long.

## 0. Setup

```bash
git clone https://github.com/murilloalvz/crypto-copy-trader.git
cd crypto-copy-trader
git checkout chore/claude-migration-2026-09-27
git pull

# Rust crates pin rust-version = 1.96.1
rustup toolchain install 1.96.1
rustup default 1.96.1

pip install -r requirements.txt
```

Create `.env` (gitignored, never commit it) with your own keys — do not reuse any key that was
ever pasted into chat or committed anywhere:

```
SOLANA_RPC_URL=https://mainnet.helius-rpc.com/?api-key=<your-helius-key>
SOLANA_RPC_FALLBACK_URLS=https://solana-rpc.publicnode.com
DATABASE_PATH=data/copytrader.db
JUPITER_API_KEY=<your-jupiter-key>
```

(copy the rest of the defaults from `.env.example`)

## 1. Offline capacity check (no live network, seconds)

```bash
python3 -m benchmarks.integrated_market_signal_plane_v1.v5_batch_suite \
  --events 10000 --seed 68 --cargo cargo \
  --out artifacts/rust_signal_batch_offline_capacity_v0/report.json
```

Expect `classification: PASS_RUST_SIGNAL_BATCH_OFFLINE_CAPACITY_V0`.

## 2. Offline bridge audit (no live network, seconds)

```bash
python3 -m benchmarks.v68_signal_plane_bridge_v0.run --events 10000 --seed 68
```

This writes its own report under `artifacts/v68_signal_plane_bridge_v0/`. Expect
`PASS_V68_SIGNAL_PLANE_BRIDGE_V0`.

## 3. PumpSwap identity bootstrap (live, ~60s)

```bash
python3 -m benchmarks.pumpswap_identity_bootstrap_v0.bootstrap --cargo cargo
```

Note the printed run directory, e.g.
`artifacts/pumpswap_identity_bootstrap_v0/pumpswap_identity_bootstrap_v0-<ts>-<id>/report.json`
— call it `$BOOTSTRAP_REPORT` below. Confirm `valid_bootstrap: true`.

## 4. Live smoke (120s) + route/research bridge (120s)

```bash
BOOTSTRAP_REPORT="artifacts/pumpswap_identity_bootstrap_v0/<run-dir-from-step-3>/report.json"

python3 -m benchmarks.integrated_market_signal_plane_v1.live_shadow \
  --bootstrap-report "$BOOTSTRAP_REPORT" \
  --duration-seconds 120 \
  --cargo cargo \
  --out artifacts/rust_signal_plane_live_shadow_v7/live-smoke-report.json

python3 -m route_research_signal_plane_bridge_v0 \
  --run-key v68-promotion-local-route-bridge-$(date +%Y%m%d) \
  --bootstrap-report "$BOOTSTRAP_REPORT" \
  --duration-seconds 120 \
  --cargo cargo \
  --shadow-out artifacts/signal_plane_route_research_bridge_v0/local-shadow.json \
  --out artifacts/signal_plane_route_research_bridge_v0/local-route-bridge-report.json
```

Both must print `classification: PASS_...`. The route-bridge run key must never contain
`v68-flow60-fresh`.

## 5. The soak — 1800s continuous, this is the step the sandbox couldn't do

```bash
python3 -m benchmarks.integrated_market_signal_plane_v1.live_shadow \
  --bootstrap-report "$BOOTSTRAP_REPORT" \
  --duration-seconds 1800 \
  --cargo cargo \
  --out artifacts/rust_signal_plane_live_shadow_v7/soak-1800s-report.json
```

Let it run uninterrupted for the full 30 minutes. Check the result:

```bash
python3 -c "
import json
d = json.load(open('artifacts/rust_signal_plane_live_shadow_v7/soak-1800s-report.json'))
print('classification:', d['classification'])
print('duration_seconds:', d['duration_seconds'])
print('all gates true:', all(d.get('gates', {}).values()))
print('trigger_parity:', d['trigger_parity']['parity_pct'], d['trigger_parity']['mismatches'])
"
```

Want: `classification == PASS_RUST_SIGNAL_PLANE_LIVE_SHADOW_V7_RUST_HOTPATH`, `duration_seconds
>= 1800`, all gates true, `parity_pct == 100.0`, `mismatches == 0`. If it fails on RPC capacity
even on Helius, that's a real result — log it, don't retry blind more than once or twice.

## 6. Build the promotion report

```bash
python3 -m signal_plane_v68_promotion_v0 \
  --offline-capacity artifacts/rust_signal_batch_offline_capacity_v0/report.json \
  --offline-bridge artifacts/v68_signal_plane_bridge_v0/report.json \
  --live-smoke artifacts/rust_signal_plane_live_shadow_v7/live-smoke-report.json \
  --live-soak artifacts/rust_signal_plane_live_shadow_v7/soak-1800s-report.json \
  --route-bridge artifacts/signal_plane_route_research_bridge_v0/local-route-bridge-report.json \
  --out artifacts/v68_signal_plane_promotion_v0/report.json
```

Want `classification: PASS_V68_SIGNAL_PLANE_PROMOTION_V0`. If any `checks` entry is `false`, the
printed report says exactly which evidence file failed which sub-check — fix that piece and
regenerate it (do not hand-edit the report; the validator hashes every evidence file and will
reject a report whose files changed after the fact).

## 7. Preflight only — verify readiness without starting a fresh V68 acquisition

```bash
python3 -m route_research_v68_release \
  --run-key v68-preflight-check-$(date +%Y%m%d) \
  --bootstrap-report "$BOOTSTRAP_REPORT" \
  --signal-plane-promotion-report artifacts/v68_signal_plane_promotion_v0/report.json \
  --preflight-only
```

Exit code `0` and all readiness checks printed `true` means step 8's evidence is genuinely
complete on your machine. **This does not start a fresh V68 acquisition** (`--preflight-only`
stops before that). Opening a real fresh V68 key (dropping `--preflight-only` and using a real,
never-before-used `--run-key`) is the actual step-8 authorization decision — do that
deliberately, not as a side effect of testing readiness.

## After this

Report back (or have Claude read the resulting artifacts and update
`docs/migration/RESEARCH_STATE_LEDGER_2026-09-27.md` and
`docs/migration/V68_PROMOTION_READINESS_PLAN_2026-09-28.md`) with whatever the real outcome was —
PASS or FAIL, either is useful evidence. Do not retune, extend the soak duration, or otherwise
adjust thresholds if it fails; that would violate this repo's frozen-gate discipline
(`CLAUDE.md`).
