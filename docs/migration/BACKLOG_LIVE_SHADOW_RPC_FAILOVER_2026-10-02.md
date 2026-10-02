# Backlog — `live_shadow.py` has no RPC failover — 2026-10-02

Status: **tracked, not fixed**. Text/documentation only. No code changed by this entry.

## Finding

`benchmarks/integrated_market_signal_plane_v1/live_shadow.py:186-190` constructs its
`SolanaClient` with `fallback_urls=()` hardcoded empty:

```python
self.client = SolanaClient(
    rpc_url=rpc_url,
    timeout=timeout_seconds,
    fallback_urls=(),
)
```

This means the identity-resolution client in `live_shadow.py` has zero automatic RPC
endpoint failover, even though `.env.example:2` defines `SOLANA_RPC_FALLBACK_URLS` and
`src/config.py:21` already reads it (`getenv("SOLANA_RPC_FALLBACK_URLS", "https://solana-rpc.publicnode.com")`).
Every other live benchmark script in this repo already wires this env var through to its
own RPC client construction, e.g.:

- `benchmarks/launch_burst_prospective_route_live_v4/live.py:161`
- `benchmarks/launch_burst_prospective_route_live_v3/live.py:679`
- `benchmarks/launch_burst_prospective_route_paper_v2/live.py:567`
- `benchmarks/holder_ownership_rpc_v2/rpc_endpoint.py:34`
- `benchmarks/holder_ownership_native_v1/run_live.py:82`
- `benchmarks/holder_ownership_structure_v0/run_live.py:79`
- `benchmarks/early_buyer_churn_prospective_v1/run_live.py:281`
- `benchmarks/early_buyer_churn_prospective_v1/provider_preflight.py:406`
- `benchmarks/launch_burst_control_taker_sim_v0/run.py:259` (and sibling scripts in that dir)

`live_shadow.py` is the outlier.

## Why this matters

This is the confirmed real cause of the first local 1800s soak's FAIL
(`signal_plane_v7_promotion_authorized=FAIL`, `identity_plane_no_rpc_batch_failure=false`,
logged 2026-09-29 in `docs/migration/RESEARCH_STATE_LEDGER_2026-09-27.md`): a single-endpoint
transient RPC batch failure with no fallback to absorb it. The retry on the second soak
attempt passed because the underlying endpoint happened to hold, not because failover
exists — the gap is still open.

## Scope of a future fix (not authorized here)

Would be the same small, existing pattern reused from the scripts listed above:
`fallback_urls=tuple(x.strip() for x in os.environ.get("SOLANA_RPC_FALLBACK_URLS", "").split(",") if x.strip())`
passed into the existing `SolanaClient(...)` call at `live_shadow.py:186-190`. No new
dependency, no new abstraction — reuse of an already-present repo convention.

Per `CLAUDE.md` coding discipline, this is **not fixed now**. It is logged here so it is not
lost, to be picked up as its own scoped change with its own targeted test when explicitly
requested.
