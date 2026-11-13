# Social/Event-First Causal Contract V0

Status: **research plumbing / no selector**.

This branch creates the causal evidence layer for an independent Social/Event-First research track. It does not alter the frozen Market-First selector, Momentum V0, the route-paper contract, Smart Ladder, or any official economic verdict.

## Why this exists

Social/event evidence is extremely easy to contaminate with future information. A post may have been published before a market move while our system only discovered it later. A generic post may also be observed early while its relationship to a token is learned after the move.

V0 therefore uses an explicit causal availability clock:

```text
causal_available_wall_ns = max(
    observed_wall_ns,
    token_mapping_observed_wall_ns
)
```

`published_at_ns` is metadata only. It never replaces the system observation clock.

If a source is token-specific at ingestion time, the token mapping clock is the ingestion observation clock. If token/entity mapping is learned later, that later timestamp delays causal availability and prevents retrospective backdating.

## Normalized evidence schema

`src/social_event_evidence_v0.py` defines the normalized evidence record.

Core fields:

- `source_kind`: extensible source family, for example `social_post`, `news`, `channel_message`, `onchain_label_event`.
- `source_key`: stable source identity.
- `source_event_id`: source-native event identity.
- `event_kind`: normalized event family.
- `observed_wall_ns`: when our collector first had the source event.
- `token_mapping_observed_wall_ns`: when the token relationship became known.
- `published_at_ns`: optional source-provided publication timestamp; metadata only.
- `actor_key`: optional normalized author/actor identity.
- `token_mint`: optional token mapping.
- `content_fingerprint_sha256`: optional content integrity fingerprint.
- `entity_keys`: optional normalized entities.

Evidence identity is deterministic from source kind/key/event ID. Conflicting duplicates are rejected.

## Social/Event snapshot

`benchmarks/social_event_first_v0/snapshot.py` builds a token-specific snapshot over a causal lookback window and decision cutoff.

V0 intentionally exposes only simple evidence structure:

- observed event count;
- unique source count;
- unique actor count;
- pre-anchor versus post-anchor event count;
- source-kind counts;
- event-kind counts;
- actor/publication/mapping coverage;
- source and actor concentration;
- first/last causal availability relative to the market anchor.

V0 deliberately does **not** implement:

- sentiment scores;
- influencer weights;
- source reputation weights;
- narrative scores;
- token ranking;
- trade recommendations;
- a Social/Event selector.

Those should only be added after the raw causal evidence stream exists and can be studied without leakage.

## Neutral convergence contract

`benchmarks/convergence_v0/join.py` can join a Market-First snapshot and a Social/Event-First snapshot only when all of these match exactly:

- token mint;
- market anchor wall clock;
- decision cutoff wall clock.

The join recursively rejects outcome-bearing keys such as PnL, route-paper PnL, fixed/smart return, future return, outcome, label, or target.

The output status is:

```text
EVIDENCE_JOIN_ONLY_NO_SELECTOR
```

Convergence does not mean the two tracks have edge together. It only creates an outcome-blind evidence object that can later support a separately preregistered convergence hypothesis.

## Exporting the existing Market-First causal snapshot

`benchmarks/convergence_v0/market_export.py` reads an existing `route-input-v2.json` and exports exactly one episode as `market_signal_snapshot_v0`.

It uses the real Launch Burst causal clocks already recorded in the feature snapshot:

- `observed_t0_wall_ns` -> market anchor;
- `decision_cutoff_wall_ns` -> frozen decision cutoff.

It copies the frozen pre-provider features and deliberately does not copy route quotes, provider collection state, PnL, or any outcome.

## Offline test command

```powershell
python -m unittest `
  tests.test_social_event_evidence_v0 `
  tests.test_social_event_snapshot_v0 `
  tests.test_convergence_market_export_v0 `
  tests.test_convergence_join_v0 -v
```

## Example local Social/Event evidence JSONL

```json
{"source_kind":"social_post","source_key":"x:actor-123","source_event_id":"post-456","event_kind":"mention","observed_wall_ns":1780000000000000000,"published_at_ns":1779999999000000000,"actor_key":"actor-123","token_mint":"TOKEN_MINT","token_mapping_observed_wall_ns":1780000000000000000}
```

The example is schematic only. Production collectors must stamp `observed_wall_ns` at ingestion and must not reconstruct it later from publication timestamps.

## Build a local Social/Event snapshot

```powershell
python -m benchmarks.social_event_first_v0.snapshot `
  --input "artifacts\social-evidence.jsonl" `
  --token-mint "TOKEN_MINT" `
  --lookback-start-wall-ns 1780000000000000000 `
  --market-anchor-wall-ns 1780000010000000000 `
  --decision-cutoff-wall-ns 1780000015000000000 `
  --output "artifacts\social-snapshot-v0.json"
```

## Export a matching Market-First snapshot

Prefer `episode_key` because a token can theoretically appear in more than one episode:

```powershell
python -m benchmarks.convergence_v0.market_export `
  --route-input "C:\path\to\run\route-input-v2.json" `
  --episode-key "EPISODE_KEY" `
  --output "artifacts\market-snapshot-v0.json"
```

## Join both tracks without outcomes

```powershell
python -m benchmarks.convergence_v0.join `
  --market "artifacts\market-snapshot-v0.json" `
  --social "artifacts\social-snapshot-v0.json" `
  --output "artifacts\convergence-evidence-v0.json"
```

## Research boundary

The correct sequence is still:

```text
Market-First research ---------\
                                > future preregistered convergence hypothesis
Social/Event-First research ---/
```

Do not make Social/Event a hidden confirmation gate for the frozen Market-First experiments. Each track must earn evidence independently first.
