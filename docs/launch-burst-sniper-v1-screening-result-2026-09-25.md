# Launch Burst Sniper V1 — Screening Result — 2026-09-25

Status: VALID DIRECTIONAL SCREENING / REPLICATION NOT ARMED / NO LIVE MONEY

## Capture

- transport-amended standard WSS preflight PASS;
- selected transport: Solana public mainnet WSS fallback;
- frozen duration: 900 seconds;
- frozen policy: SNIPER-HIGH-PRECISION-V1;
- primary benchmark: fixed +60 second route-shadow;
- exact source parity PASS.

## Sample

- baseline selected: 70;
- primary Sniper selected: 26;
- primary selection rate: 37.142857%;
- baseline usable route results: 48;
- primary usable route results: 16;
- screening status: DIRECTIONAL_READ_AVAILABLE_REPLICATION_NOT_ARMED.

The preregistered replication threshold is 30 usable primary route results. It was not met.

## Primary fixed +60s economics

Baseline:
- mean return: -23.050369%;
- median return: -24.351926%;
- positive-trade share: 18.75%;
- profit factor: 0.299390;
- ROI on deployed capital: -23.050369%.

Primary Sniper:
- mean return: -26.462329%;
- median return: -17.108874%;
- positive-trade share: 25.0%;
- profit factor: 0.210495;
- ROI on deployed capital: -26.462329%.

Primary minus baseline:
- mean return: -3.411960 percentage points;
- median return: +7.243052 percentage points;
- positive-trade share: +6.25 percentage points;
- ROI on deployed capital: -3.411960 percentage points.

## Interpretation

The Sniper subset improved median and hit rate, and skipping rejected trades reduced gross loss dollars.
However, it worsened the frozen primary mean-return endpoint, deployed-capital ROI and profit factor.
The selected subset also lost the baseline's largest positive tail winner.

Because only 16 usable primary results were observed, this is a directional read rather than a formal
economic confirmation. The preregistered independent replication is not armed.

No threshold retuning, duration extension in-place, subgroup rescue or replication is authorized from
this screening.

## Disposition

- Sniper V1 replication: NOT ARMED;
- threshold retuning: forbidden;
- same-sample rescue: forbidden;
- this capture remains available for separately preregistered discovery hypotheses that predate the
  capture;
- next selected candidate should require separate fresh confirmation before any edge claim.
