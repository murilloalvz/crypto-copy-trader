# Opportunity Social Evidence v57 — Market-First Causal Evidence Contract

Date: 2026-09-07

Mode: **PAPER / RESEARCH / READ ONLY**

## Purpose

Prepare a causal social-evidence envelope for an opportunity that was already identified by the market-first pipeline.

v57 does not discover tokens, open market episodes, assign a score, recommend a BUY, alter the frozen detector, or participate in the running v55 experiment.

The intended future flow is:

`market episode -> research decision as_of -> optional social evidence known as_of -> descriptive research`

not:

`social post -> automatic token enrollment -> BUY`.

## Existing causal core retained

The repository already retains social snapshots with both `created_at` and `observed_at` and preserves repeated observations of the same post for engagement evolution.

Window membership is based on the collector's first `observed_at`, not on post creation time and not on a later engagement refresh. The latest snapshot already observed by `as_of` may provide engagement counters.

These semantics remain authoritative in v57.

## Identity rule

v57 requires an exact `token_mint`.

Symbol-only joins are forbidden in the market-first evidence envelope because ticker collisions, aliases and renames can attach unrelated social events to an on-chain opportunity.

The older generic social tools may still support symbol-oriented manual research, but they are not the authority for v57 market-first linkage.

## Frozen descriptive windows

- current social window: 300 seconds
- baseline social window: 3600 seconds

The baseline comparison uses the inherited non-overlapping prior portion of the 3600-second window.

No economic label was used to choose these windows for v57. They are an engineering evidence contract, not a validated trading hypothesis.

## Descriptive fields

When causal social events exist, v57 may expose:

- causal post count;
- current-window event count;
- current unique author count;
- prior baseline event count;
- event-rate acceleration ratio;
- current author diversity percentage;
- current original-post share;
- current total engagement known as-of;
- current engagement per event known as-of.

No weighted social score is created.

## Explicit missingness

If no matching post had been observed by `as_of`:

`status=NO_CAUSAL_EVENTS`

This means only that the current social source/store contains no causal evidence for that token at that clock. It must not be interpreted as bearish evidence.

If the prior baseline contains zero events, the acceleration ratio remains `None`. A zero baseline must not be converted to infinite acceleration or a bullish signal.

## Engagement refresh rule

Multiple persisted snapshots of one post do not create multiple posts.

At a given `as_of`:

- first observed time controls discovery/window membership;
- latest snapshot already observed by `as_of` controls engagement counters;
- engagement recorded after `as_of` is invisible.

This prevents future popularity from leaking into an earlier decision.

## Acquisition status

The repository currently contains causal persistence and manual/JSONL ingest utilities, but v57 does not define or approve a live X/social provider.

A future social acquisition protocol must separately specify:

1. source/provider;
2. polling/stream semantics;
3. authoritative `observed_at` assignment;
4. token-mint resolution provenance;
5. rate-limit/missingness behavior;
6. replay/deduplication semantics;
7. source coverage measurement.

No provider should be selected because it makes past returns look better.

## Relationship to v55

The live v55 Causal Early-Opportunity Discovery experiment was pre-registered without social features.

Therefore v57 social evidence is **not** injected into v55, its feature set, its candidate shortlist, or its economics.

After v55 is complete, v57 may inform a future independent discovery protocol only if that protocol is registered before examining its own outcome labels.

## What CI success proves

Only that the market-first social evidence bridge preserves the intended causal semantics in unit tests:

- posts discovered later are not visible earlier;
- future engagement refreshes do not leak backward;
- repeated snapshots do not duplicate posts;
- exact token-mint identity is preserved;
- zero baseline remains explicit missingness.

It does not prove:

- social attention predicts returns;
- any source has adequate live coverage;
- author diversity is organic demand;
- engagement is economically useful;
- executable/fill/shadow/live readiness.

## Forbidden

- symbol-only market-first joins;
- created-at-as-availability shortcuts;
- using future engagement at historical decisions;
- treating no social data as negative evidence;
- treating zero baseline as infinite acceleration;
- opening a token solely because a social event exists;
- adding v57 to the currently running v55 experiment;
- mining social thresholds from v48/v55 and presenting them as validation;
- live-money execution.

## Scaffold acceptance

The v57 scaffold is accepted when:

1. exact token-mint join is enforced;
2. `observed_at` causality tests pass;
3. repeated engagement snapshots remain one post;
4. future refreshes are excluded from earlier `as_of`;
5. zero-baseline acceleration is explicit `None`;
6. full repository CI is green.

Classification after scaffold acceptance:

`READY_V57_CAUSAL_SOCIAL_EVIDENCE_SCAFFOLD`

This is an engineering/causal-semantics readiness statement only, not an economic result.
