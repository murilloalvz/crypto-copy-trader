# Market Activity Discovery V0 — Operations

Status: **RESEARCH OPERATIONS / NO LIVE DISCOVERY STARTED BY THIS DOCUMENT**

This document records the deterministic offline smoke and the metadata-only CLI for the preregistered six-hour Market Activity Dynamics discovery run.

## Safety/scientific boundary

The CLI does not detect opportunities, call market providers, collect prices, complete forward outcomes, score opportunities, or evaluate economic edge. It only creates/reads/transitions the immutable discovery run registry and reports denominator/outcome accounting already persisted by other research-plane components.

The offline smoke uses a temporary SQLite database and performs zero provider calls.

## Deterministic offline smoke

```powershell
python -m benchmarks.market_activity_discovery_v0.smoke
```

Expected classification:

```text
PASS_MARKET_ACTIVITY_DISCOVERY_V0_OFFLINE_SMOKE
```

The smoke verifies:

- exact six-hour run window;
- one analyzable T0 episode;
- one missing-T0 denominator member;
- exact replay idempotence;
- half-open admission boundary at the deadline;
- normal close at the frozen deadline;
- restart/load preservation;
- default +5m/+15m/+60m outcomes remain `PENDING`;
- zero provider calls;
- no economic evaluation.

## CLI

Open a run using the current Unix epoch second:

```powershell
python -m benchmarks.market_activity_discovery_v0.cli open `
  --run-key "<RUN_KEY>" `
  --cohort-key "<COHORT_KEY>"
```

For deterministic/replay testing, an explicit start may be supplied:

```powershell
python -m benchmarks.market_activity_discovery_v0.cli open `
  --run-key "<RUN_KEY>" `
  --cohort-key "<COHORT_KEY>" `
  --started-at 1234567890
```

Inspect scientific/operational accounting:

```powershell
python -m benchmarks.market_activity_discovery_v0.cli inspect `
  --run-key "<RUN_KEY>"
```

Normal close is accepted only once the frozen six-hour deadline has elapsed:

```powershell
python -m benchmarks.market_activity_discovery_v0.cli close `
  --run-key "<RUN_KEY>"
```

Operational interruption is distinct from normal completion:

```powershell
python -m benchmarks.market_activity_discovery_v0.cli interrupt `
  --run-key "<RUN_KEY>" `
  --reason "<OPERATIONAL_REASON>"
```

## Live promotion rule

Do not start the fresh six-hour discovery run merely because the CLI exists. Promotion still requires:

1. targeted tests for run/admission/cohort/smoke/CLI;
2. full unit suite PASS;
3. deterministic offline smoke PASS;
4. a short live operational smoke with no economic analysis;
5. audit of admissions, immutable dispositions, snapshot hashes, scheduled outcomes, and provider/coverage state;
6. fresh run/cohort keys for the official six-hour discovery.

No outcome-informed change to duration, windows, cohort dispositions, Activity Dynamics features, or admission semantics is allowed after the official run starts.
