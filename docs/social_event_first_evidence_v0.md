# Social/Event-First Evidence V0

Status: independent research foundation. No trading rule, sentiment score, influencer score or convergence rule is defined here.

## Purpose

Build a causal Social/Event-First evidence stream that can later be researched independently from Market-First.

The research track remains:

`external event -> local observation -> token attribution -> deduped evidence snapshot -> future hypothesis -> prospective validation`

It does **not** become:

`someone mentioned token -> buy`

## Causal clock rule

`observed_at` is the local evidence-availability clock.

A provider's `created_at`, `published_at` or equivalent timestamp is metadata. It may describe when an item claims to have been created, but it does not prove the project had access to that evidence at that time.

Therefore:

- `source_created_at <= decision_as_of` does not make an event causal by itself;
- `observed_at > decision_as_of` always excludes the event from that decision;
- historical items discovered later cannot be backdated into an earlier signal.

## Token attribution

V0 recognizes four attribution classes:

- `MINT_DIRECT` — the evidence directly names or embeds the exact token mint;
- `LINK_RESOLVED` — a link/entity was deterministically resolved to the exact mint;
- `MANUAL_VERIFIED` — a pre-outcome manual verification tied the event to the mint;
- `SYMBOL_ONLY_AMBIGUOUS` — only a symbol/name-level match exists.

Only the first three count as strongly attributed token evidence in the V0 snapshot.

`SYMBOL_ONLY_AMBIGUOUS` is preserved for audit but is not silently promoted into token-specific evidence.

## Deduplication

The same provider event is identified by `(source, source_event_id)`.

If the same event is observed repeatedly, the earliest locally observed causal copy is the event-count observation. Later observations must not inflate event count.

Future engagement snapshots may be modeled separately because likes/reposts/replies can change over time and have their own observation clocks.

## V0 snapshot

`src/social_event_evidence_v0.py` currently exposes:

- deduped event count;
- strongly attributed event count;
- ambiguous attribution count;
- unique author count when author identity is available;
- counts by source;
- counts by event type;
- counts by attribution method;
- first/latest local observation times;
- provenance keys;
- explicit missingness/quality flags.

## Explicit non-goals

V0 does not compute:

- sentiment;
- virality;
- influencer reputation;
- engagement quality;
- bot probability;
- narrative strength;
- opportunity score;
- confidence percentage;
- TAKE/SKIP recommendation;
- Market-First + Social/Event-First convergence.

Those require their own evidence definitions and prospective validation.

## Next research increments

1. Source adapters that preserve raw provider IDs and local observation clocks.
2. Author/account evidence contract separate from event evidence.
3. Engagement-update observations with explicit local observation timestamps.
4. Narrative/entity clustering only after token-attribution precision is measured.
5. Social/event feature discovery on frozen evidence snapshots.
6. Prospective Social/Event-First holdout independent of Market-First.
7. Only after both tracks have independent evidence: test convergence as a new pre-registered hypothesis.
