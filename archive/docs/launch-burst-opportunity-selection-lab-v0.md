# Launch Burst Opportunity Selection Lab V0

Status: **offline hypothesis-generation laboratory**.

This branch is intentionally isolated from the frozen Momentum V0 screening branch. It does not mutate the frozen selector, route contract, Smart Ladder contract, or any official economic verdict.

## Purpose

Use already-captured causal Launch Burst route-shadow artifacts to answer three separate research questions:

1. **Profitability separation** — which frozen pre-provider causal features tend to be higher/lower in positive fixed-60s outcomes than in non-positive outcomes?
2. **Frozen Sniper V1 gate diagnostics** — did each threshold that was preregistered before the screening outcomes separate the sample in the intended direction?
3. **Copyability separation** — which frozen pre-provider causal features distinguish `ROUTE_CLOSED` from `UNROUTABLE_EXIT` outcomes?

The lab deliberately does **not** optimize thresholds, fit a model, mutate a policy, or turn same-sample discovery into a validation claim.

## Scientific rules

- Features come only from each episode's frozen 5-second `feature_snapshot`.
- Route outcomes are labels only and are not fed back into the feature snapshot.
- Existing Sniper V1 thresholds may be evaluated because they were preregistered before the screening outcomes.
- No new threshold is emitted from these samples (`threshold_recommendation = null`).
- Continuous feature separation is descriptive and uses AUC, medians, Spearman correlation, and leave-one-positive-out direction stability.
- A feature gets stronger priority only when sample/coverage minimums are met.
- Cross-run priority requires the same feature direction in multiple compatible runs and leave-one-positive-out stability in every run.
- Profitability and copyability are analyzed separately.
- All conclusions remain route-shadow research, not landed-fill or realized-PnL claims.

## Offline commands

### 1. Run unit tests

```powershell
python -m unittest tests.test_launch_burst_opportunity_selection_lab_v0 tests.test_launch_burst_copyability_diagnostics_v0 -v
```

### 2. Discover compatible local runs only

```powershell
python -m benchmarks.launch_burst_opportunity_lab_v0.discover --artifacts-root artifacts --discover-only
```

### 3. Auto-analyze up to four most recent compatible runs

```powershell
python -m benchmarks.launch_burst_opportunity_lab_v0.discover --artifacts-root artifacts --limit 4
```

Output defaults to:

```text
artifacts/opportunity-selection-lab-v0.json
```

### 4. Analyze explicit runs

Repeat `--run-dir` for each independent artifact set:

```powershell
python -m benchmarks.launch_burst_opportunity_lab_v0.analyze `
  --run-dir "C:\path\to\run-a" `
  --run-dir "C:\path\to\run-b" `
  --output "artifacts\opportunity-selection-lab-v0.json"
```

### 5. Copyability diagnostics for one run

```powershell
python -m benchmarks.launch_burst_opportunity_lab_v0.copyability `
  --run-dir "C:\path\to\run" `
  --output "artifacts\copyability-diagnostics-v0.json"
```

## How to read the output

### `RESEARCH_PRIORITY`

Within one run, the continuous feature has adequate coverage/sample, material winner-vs-nonwinner AUC separation, and leave-one-positive-out direction stability. This makes it a **candidate for a future preregistered hypothesis**, not a validated selector.

### `REPLICATED_DIRECTION_PRIORITY`

Across multiple compatible runs, the feature points in the same direction with minimum separation and robustness in every run. This is stronger hypothesis-generation evidence but still requires a new frozen prospective test.

### `COPYABILITY_RESEARCH_PRIORITY`

The feature descriptively separates route-closed episodes from unroutable exits. Treat it as a candidate copyability/risk feature, not as a profitability signal.

## Next research use

The next selector should not simply take the strongest same-sample feature and choose the best-looking cutoff. Instead:

1. inspect replicated feature directions;
2. choose a small causal feature set based on market meaning and independent-run consistency;
3. define thresholds without optimizing against these outcomes (domain-fixed, externally motivated, or preregistered before fresh data);
4. run a fresh prospective validation;
5. keep Social/Event-First as an independent track until causal, timestamped social/event evidence is available for a proper convergence test.
