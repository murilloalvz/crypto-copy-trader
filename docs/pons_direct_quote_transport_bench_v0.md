# Pons Direct Quote Transport Bench V0

Status: **systems-only infrastructure benchmark**.

This benchmark compares two ways of reading the exact same Pons V2 curve state:

- sequential JSON-RPC `eth_call`s;
- one strict JSON-RPC batch request.

It does not test profitability, execution, provider routing, or trade outcomes.

## Paired design

Every iteration:

1. samples one explicit block number;
2. pins both readers to that same block;
3. alternates execution order between sequential-first and batch-first;
4. requires both readers to observe the same block hash;
5. removes only local observation/provenance metadata and requires exact decoded state parity;
6. admits the pair to latency statistics only after parity passes.

A state mismatch is a benchmark failure, not a latency sample.

## Metrics

For valid pairs only:

- sequential total state-read p50/p95/p99/max/mean;
- batch total state-read p50/p95/p99/max/mean;
- batch HTTP service p50/p95/p99/max/mean;
- sequential-minus-batch latency;
- sequential/batch speedup ratio.

Execution order alternates to reduce simple first-reader/cache bias. This does not make the benchmark immune to provider-side caching; results remain provider/network specific.

## Scientific guards

The report freezes:

- `economic_outcomes_opened = false`;
- `provider_route_outcomes_opened = false`;
- `trade_returns_computed = false`;
- `selector_modified = false`.

A PASS requires every requested pair to complete with exact same-block state parity and zero errors.

## Operational command

Run only on a stable network and a real known Pons curve/recipient:

```powershell
& 'C:\Users\LocalUser\Projetos\crypto-copy-trader\.venv\Scripts\python.exe' `
  -m benchmarks.robinhood_launch_burst_v0.direct_quote_transport_bench `
  --curve '<CURVE_ADDRESS>' `
  --recipient '<PUBLIC_RECIPIENT_ADDRESS>' `
  --iterations 20
```

Use `--rpc-url` or set `ROBINHOOD_RPC_URL` in the process environment when testing a production provider. No private key is used or required.
