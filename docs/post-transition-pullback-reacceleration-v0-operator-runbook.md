# Post-Transition Pullback / Reacceleration V0 — Operator Runbook

Status: OFFLINE + SYSTEMS ONLY

This runbook does not authorize economic outcomes or live money.

## Gate 1 — offline causal validation

From the dedicated worktree, with the existing project virtual environment activated:

```powershell
python -m unittest `
    tests.test_post_transition_reacceleration_v0 `
    tests.test_post_transition_reacceleration_systems_probe_v0 `
    tests.test_pumpswap_asset_role `
    tests.test_pumpswap_stream `
    tests.test_pump_lifecycle_capture `
    tests.test_unified_lifecycle_semantics `
    -q

python -m benchmarks.post_transition_reacceleration_v0.offline_replay `
    --fixture benchmarks/post_transition_reacceleration_v0/fixture.synthetic.json `
    --output artifacts/post_transition_reacceleration_v0/offline-replay.json
```

Required:

- targeted tests PASS;
- `PASS_POST_TRANSITION_REACCELERATION_OFFLINE_REPLAY_V0`;
- `economic_outcomes_opened=false`;
- `provider_calls_used=false`;
- Pump origin confirmed in the synthetic fixture;
- pullback observed;
- structural reacceleration candidate observed;
- provider/future outcome/future extrema flags all false.

Do not proceed to an economic discovery from this gate alone.

## Gate 2 — systems-only live availability

Run only after Gate 1 and full repository CI are green.

```powershell
python -m benchmarks.post_transition_reacceleration_v0.systems_probe `
    --duration-seconds 120 `
    --env-file "<MAIN_REPO>\.env" `
    --output artifacts/post_transition_reacceleration_v0/systems-probe-120s.json
```

The probe:

- resolves one WSS endpoint that accepts PumpSwap logsSubscribe;
- consumes only PumpSwap CreatePool/Buy/Sell stream data;
- creates causal in-memory states only from directly observed CreatePool transitions;
- does not call Jupiter;
- does not open economic outcomes;
- does not require Pump-origin lineage for this plumbing-only gate;
- reports whether direct transition states and anchored post-transition trades were observed.

Interpretation:

### PASS_POST_TRANSITION_REACCELERATION_SYSTEMS_PROBE_V0

At least one role-valid direct transition state was observed. Review counters and transport integrity before designing fresh discovery.

PASS is systems evidence only.

### INCONCLUSIVE_POST_TRANSITION_REACCELERATION_SYSTEMS_PROBE_NO_TRANSITION

Transport worked but no role-valid direct CreatePool transition appeared in the window.

This is not a scientific KILL and not an edge verdict. Do not change market thresholds to force an event.

### FAIL_POST_TRANSITION_REACCELERATION_SYSTEMS_PROBE_V0

Transport/subscription/decode path failed. Fix systems only. Do not touch the research feature contract to rescue transport.

## Before fresh economic discovery

A later implementation must still wire:

1. causally confirmed Pump-origin lineage into eligible transition states;
2. immutable research snapshot persistence;
3. separate +60s primary route-shadow outcome collection;
4. separate +300s exploratory route-shadow outcome collection;
5. exact feature/outcome lineage and missingness accounting.

Only after those contracts are implemented, tested and preregistered may a fresh economic discovery cohort be opened.
