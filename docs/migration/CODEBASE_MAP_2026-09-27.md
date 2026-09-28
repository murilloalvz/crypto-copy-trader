# Codebase Map — Claude Migration — 2026-09-27

This is a navigation aid, not a substitute for reading task-specific code.

## High-level structure

### Root scripts

Historical and current experiment runners live at repository root. Important current families include:

- `route_research_*.py`
- `signal_plane_*.py`
- `participant_quality_*.py`
- `unified_market_*.py`

Do not choose a runner by version number alone. Read the exact protocol/result docs first.

### `src/`

Reusable project implementation.

### `tests/`

Unit/regression tests. Prefer the narrowest directly related test module first.

### `benchmarks/`

Deterministic/offline and live-shadow research harnesses. Benchmark PASS proves only the exact benchmark contract.

### `docs/`

Protocols, preregistrations, decisions, incidents and results.

### `artifacts/`

Runtime evidence may be local/untracked/ignored depending on the run. Do not assume every historical artifact exists on the GitHub remote.

## Signal Plane / systems navigation

### Integrated Signal Plane benchmark

Directory:

`benchmarks/integrated_market_signal_plane_v1/`

Key files:

- `README.md`
- `suite.py`
- `v5_batch_suite.py`
- `rust_suite.py`
- `live_shadow.py`
- `rust_runner/Cargo.toml`
- `rust_runner/src/bin/stream.rs`

Rust package currently pins:

`rust-version = 1.96.1`

Relevant tests:

- `tests/test_integrated_market_signal_plane_v1.py`
- `tests/test_rust_indexed_signal_plane_v0.py`
- `tests/test_rust_signal_plane_live_shadow_v0.py`
- `tests/test_rust_signal_plane_live_shadow_v2.py`

### Signal -> episode bridge

Implementation:

- `src/signal_plane_episode_bridge_v0.py`
- `src/signal_plane_episode_admission_v0.py`

Tests:

- `tests/test_signal_plane_episode_bridge_v0.py`
- `tests/test_signal_plane_episode_admission_v0.py`

Offline V68 bridge audit:

- `benchmarks/v68_signal_plane_bridge_v0/run.py`

### Research Plane durability

Implementation:

- `src/signal_plane_research_persistence_v0.py`
- `src/market_observation_store.py`
- `src/market_observation_batch_v0.py`

Tests:

- `tests/test_signal_plane_research_persistence_v0.py`
- `tests/test_market_observation_store.py`
- `tests/test_market_observation_batch_v0.py`
- `tests/test_market_observation_transaction_identity.py`

Capacity incident authority:

`docs/role-normalized-research-plane-capacity-incident-2026-09-24.md`

### Signal -> route research coordinator

Implementation:

- `src/signal_plane_route_research_coordinator_v0.py`
- `route_research_signal_plane_bridge_v0.py`

Tests:

- `tests/test_signal_plane_route_research_coordinator_v0.py`

## V55 / V68 navigation

### V55 discovery / selection

Root:

- `route_research_early_opportunity_discovery_v55.py`
- `route_research_v55_candidate_selection.py`

Implementation:

- `src/route_research_early_opportunity_v55.py`
- `src/route_research_v55_candidate_selection.py`

Tests:

- `tests/test_route_research_early_opportunity_discovery_v55.py`
- `tests/test_route_research_early_opportunity_v55.py`
- `tests/test_route_research_v55_candidate_selection.py`

Protocol/result docs:

- `docs/route-research-v55-causal-early-opportunity-discovery-protocol-2026-09-07.md`
- `docs/route-research-v55-causal-early-opportunity-discovery-result-2026-09-08.md`
- `docs/route-research-v55-candidate-selection-to-holdout-protocol-2026-09-07.md`

### V68 frozen prospective holdout

Root:

- `route_research_prospective_flow60_buy_share_holdout_v68.py`
- `route_research_prospective_flow60_buy_share_holdout_v68_signal_plane_v0.py`
- `route_research_v68_release.py`
- `signal_plane_v68_promotion_v0.py`

Implementation:

- `src/route_research_prospective_flow60_buy_share_v68.py`
- `src/signal_plane_forward_cohort_v0.py`

Tests:

- `tests/test_route_research_prospective_flow60_buy_share_v68.py`
- `tests/test_route_research_v68_signal_plane_v0.py`
- `tests/test_route_research_v68_release.py`
- `tests/test_signal_plane_forward_cohort_v0.py`
- `tests/test_signal_plane_v68_promotion_v0.py`

Protocol:

`docs/route-research-v68-prospective-flow60-buy-share-holdout-protocol-2026-09-08.md`

Migration-specific systems doc:

`docs/v68-signal-plane-migration-v0-2026-09-22.md`

Do not run a fresh V68 experiment merely because these entrypoints exist.

## Participant Quality navigation

Root:

- `participant_quality_native_memory_v0.py`
- `participant_quality_native_memory_v1.py`
- `participant_quality_native_memory_resume_v0.py`
- `participant_quality_native_holdout_v1.py`

Tests:

- `tests/test_participant_quality_native_memory_v0.py`
- `tests/test_participant_quality_native_memory_v1.py`
- `tests/test_participant_quality_native_memory_resume_v0.py`
- `tests/test_participant_quality_native_holdout_v1.py`

Authority docs:

- `docs/native-participant-quality-holdout-v1-preregistration-2026-09-24.md`
- `docs/native-participant-quality-holdout-v1-result-2026-09-24.md`

Exact holdout selector is KILL.

## Pump / PumpSwap streaming

Implementation:

- `src/pump_bonding_stream.py`
- `src/pumpswap_stream.py`

Tests:

- `tests/test_pump_bonding_stream.py`
- `tests/test_pumpswap_stream.py`

Changing these files can affect causal acquisition. Do not treat stream edits as routine refactors.

## Hazard / route research

Hazard:

- `src/opportunity_onchain_hazard.py`
- `src/opportunity_token_hazard.py`
- `hazard_provider_attempt_diagnostic.py`

Route-research storage/evaluation:

- `src/opportunity_route_research_store.py`
- `src/route_research_evaluation.py`
- forward-collection modules under `src/route_research_forward_collection_*.py`

Provider pacing and route-only economics may be frozen by a specific protocol. Check before editing.

## Post-Transition branch

The following paths belong to the later divergent Post-Transition line and are not necessarily present on the migration base:

- `src/post_transition_reacceleration_v0.py`
- `src/post_transition_snapshot_journal_v0.py`
- `benchmarks/post_transition_reacceleration_v0/`
- `docs/post-transition-*.md`

To edit that line, switch or worktree from:

`research/post-transition-pullback-reacceleration-v0`

Do not recreate missing files on the systems branch from memory.

## Test strategy for Claude

For a scoped change:

1. identify exact module;
2. run its direct unit test;
3. run directly coupled bridge/regression tests;
4. only then expand to broader suites if the change crosses a boundary;
5. do not run fresh live/economic experiments unless the task explicitly authorizes them.

Examples:

### Signal Plane offline

```powershell
python -m unittest tests.test_integrated_market_signal_plane_v1 -v
```

### Research persistence

```powershell
python -m unittest tests.test_signal_plane_research_persistence_v0 -v
```

### Episode bridge

```powershell
python -m unittest tests.test_signal_plane_episode_bridge_v0 -v
```

### Participant Quality holdout logic

```powershell
python -m unittest tests.test_participant_quality_native_holdout_v1 -v
```

A green unit test does not authorize a live run.

## Practical rule

Never start from:

"Which file looks like the newest version?"

Start from:

"Which protocol/result is authoritative for the task, and which implementation/test pair implements that contract?"
