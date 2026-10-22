# Participant Quality Native Memory v0 — M2 Technical Replacement Addendum — 2026-09-24

Mode: PAPER / RESEARCH / READ ONLY

## Incident

The original M1 completed successfully:

- run key: `participant-quality-native-memory-20260924-01-M1`
- Signal Plane -> Research Plane bridge: PASS
- research decisions: 40
- scheduled outcomes: 120
- 300s/900s maturity collector: PASS

The original M2 failed the bridge before any economic/coverage review:

- run key: `participant-quality-native-memory-20260924-01-M2`
- selected: 40
- hazard terminal: 40
- research decisions frozen: 39
- scheduled outcomes: 117
- research worker errors: 1
- failed bridge checks:
  - `downstream_no_worker_errors`
  - `research_terminal_accounting_exact`

The single unresolved episode had:

- hazard status: AVAILABLE
- entry provider attempt: PRESENT
- entry status: STARTED
- completed_at: null
- route-research decision: absent

The provider attempt was persisted before provider I/O under the project's at-most-once contract.
Repeating the provider call for this attempt is forbidden.

No economic result, Participant Quality value, coverage result, threshold, or P&L was used to decide
this replacement.

## Scientific disposition

The original M2 is technically invalid as a cohort even though it contains 39 frozen decisions.
Those 39 partial-cohort decisions MUST NOT contribute to:

- memory coverage;
- Participant Quality values;
- future cutoff calculation;
- prior-history associations for later memory slots;
- economic validation.

The invalid run key is permanently excluded:

`participant-quality-native-memory-20260924-01-M2`

## Authorized replacement

The experiment remains exactly four valid scientific slots.

- M1 = existing validated `...-M1`
- M2 = replacement `participant-quality-native-memory-20260924-01-M2R1`
- M3 = `participant-quality-native-memory-20260924-01-M3`
- M4 = `participant-quality-native-memory-20260924-01-M4`

This is a one-for-one technical replacement of a failed acquisition slot, not a fifth cohort and not
a post-hoc extension based on research results.

All original frozen acquisition parameters, memory horizon, coverage gates and outcome-blind cutoff
rules remain unchanged.

## Resume requirements

Before new acquisition:

1. M1 must still validate as bridge PASS with its existing exact schedule and terminal 300s/900s outcomes.
2. M2R1, M3 and M4 keys must be strictly fresh across all SQLite tables.
3. the route-research history loader must explicitly exclude the invalid original M2 key.

If any replacement/new slot fails, fail closed again. Do not silently add another cohort.

## Forbidden

- replaying the original M2 STARTED provider attempt;
- treating 39/40 original M2 as a valid cohort;
- allowing original M2 history into later Participant Quality features;
- rerunning M1;
- using economic results to justify the replacement;
- adding a fifth valid memory slot;
- live-money execution.
