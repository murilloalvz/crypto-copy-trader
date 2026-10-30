# Participant Quality Native Memory v0 — M2R1 Failure / M2R2 Technical Replacement Addendum — 2026-09-24

Mode: PAPER / RESEARCH / READ ONLY

## New technical evidence

The first technical replacement cohort `participant-quality-native-memory-20260924-01-M2R1`
failed before any coverage/economic audit with:

- Signal Plane V7: PASS;
- selected: 40;
- hazard terminal: 40;
- entry terminal: 39;
- research decisions frozen: 38;
- research outcomes scheduled: 114;
- research worker errors: 1;
- failed checks: `downstream_no_worker_errors`, `research_terminal_accounting_exact`;
- no queue overflow, drain timeout, schedule violation or executable-route violation.

This reproduces the same class of Research Plane failure seen in the original M2. No economic result,
Participant Quality value, coverage result, threshold or P&L was inspected to authorize another replacement.

## Root-cause hardening authorized by the repeated systems failure

The Jupiter read-only client did not normalize every realistic HTTP/socket transport exception or malformed
optional numeric response field into `JupiterOrderError`. An exception escaping after the provider attempt
had been persisted as `STARTED` can kill a Research Plane worker and leave terminal accounting short.

Before another acquisition, the provider boundary is hardened to:

- normalize additional HTTP/socket/read/decode failures to `JupiterOrderError`;
- normalize provider-payload numeric parsing failures to `JupiterOrderError`;
- preserve fail-closed at-most-once semantics;
- record Research/Hazard worker exception type, message and episode in the bridge snapshot for future diagnosis.

Rust V7 / Signal Plane semantics are unchanged.

## Scientific disposition

Both partial failed slot-2 cohorts are permanently excluded from Participant Quality history, coverage and cutoff:

- `participant-quality-native-memory-20260924-01-M2`
- `participant-quality-native-memory-20260924-01-M2R1`

The experiment still contains exactly four valid scientific slots:

- M1 = existing validated `...-M1`;
- M2 = new replacement `participant-quality-native-memory-20260924-01-M2R2`;
- M3 = `participant-quality-native-memory-20260924-01-M3`;
- M4 = `participant-quality-native-memory-20260924-01-M4`.

M2R2 is a one-for-one technical replacement after a provider-boundary systems fix. It is not a fifth valid
memory cohort and does not alter any economic hypothesis, horizon, direction, threshold or coverage gate.

If M2R2 fails again, stop. Do not authorize M2R3 automatically.
