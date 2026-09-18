# Deployer Prior Quality V0

Status: **PREREGISTERED PROSPECTIVE DISCOVERY**

This experiment tests one new Market-First evidence family without changing the existing selector:

`mf_deployer_created_count_snapshot_ex_current`

Definition:

```text
GMGN token info
-> creator_address
-> GMGN portfolio created-tokens
-> total_created_snapshot = inner_count + open_count
-> feature = max(total_created_snapshot - 1, 0)
```

The `-1` excludes the current token from the deployer's total observed creation count.

## Causal rule

The sidecar starts when a Pump create anchor becomes available to the Research Plane.

Both GMGN calls must complete no later than the token's existing 5-second decision cutoff.

If either response is late, missing, rate-limited or invalid:

```text
feature = MISSING
```

Late data is retained only for audit diagnostics and is never backfilled into the frozen feature snapshot.

## Isolation

The GMGN sidecar:

- is launched asynchronously from the Research Plane;
- never participates in the frozen route selector;
- never changes SNIPER;
- never changes the Route-Paper contract;
- never changes Participant Quality;
- uses `GMGN_API_KEY` only;
- removes `GMGN_PRIVATE_KEY` from the subprocess environment;
- makes at most one attempt per command;
- signs/submits no transaction;
- uses no capital.

## Primary endpoint

`ROUTE_CLOSED gross Fixed+60 standardized outcome`

Secondary:

`ROUTE_CLOSED net Fixed+60`

Copyability reference:

`route-usable Fixed+60 including unroutable exit = -100`

Incremental analysis controls:

1. retained Participant Quality feature;
2. BUY event-rate acceleration;
3. signed flow over event reserve.

## Discovery rule

Minimum primary route-closed feature/outcome pairs for a directional read:

`30`

This sample can only produce:

- `DISCOVERY_COMPLETE_NO_PROMOTION`; or
- `INSUFFICIENT_SAMPLE_NO_EXTENSION`.

It cannot create a production threshold, selector or validated signal.

## Local targeted tests

```powershell
python -m unittest tests.test_deployer_prior_quality_v0 -v
```

## Prospective capture

Run only on a stable unrestricted network with `GMGN_API_KEY`, Helius, Jupiter and Solana RPC already present in the local environment.

```powershell
$root = "artifacts\launch_burst_control_taker_sim_v4_sniper_v1"

$before = @(
    Get-ChildItem $root -Directory |
    ForEach-Object { $_.FullName }
)

python -m benchmarks.launch_burst_control_taker_sim_v0.run_v4_sniper_v1 `
  --duration-seconds 900

$fresh = Get-ChildItem $root -Directory |
    Where-Object { $_.FullName -notin $before } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName

$fresh
```

Do not repeat/extend the capture based on observed outcomes.

## Discovery evaluator

Use the exact four frozen Participant Quality history runs:

```powershell
python -m benchmarks.deployer_prior_quality_v0.run `
  --history-run-dir $h0 `
  --history-run-dir $h1 `
  --history-run-dir $h2 `
  --history-run-dir $h3 `
  --fresh-run-dir $fresh
```

The evaluator writes:

`deployer-prior-quality-v0.json`

inside the fresh run directory.
