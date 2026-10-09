# Pons Launch Quality Evidence v67 — Protocol — 2026-09-08

## Mode

**PAPER / RESEARCH / READ ONLY**

v67 is a causal raw-evidence envelope for future Robinhood Chain / Pons research. It is not a score, signal, ranking model, or trade filter.

## Purpose

Represent launch characteristics that may later be tested economically without importing heuristic weights from third-party snipers or launch scanners.

The evidence families are deliberately raw:
- launch/deployer identity;
- dev buy size/share when observable;
- creator tax and fee recipient;
- declared opening-tax exemptions/bundle count when authoritative;
- social-presence fields;
- deployer prior-launch/graduation history;
- prior launch-fingerprint matches;
- early market activity and wallet breadth;
- exact bonding-curve progress from v64;
- recipient-specific opening tax only when a v66 deployment capability is authoritative.

## Deployment authority

v67 accepts only a v66 attestation for:
- protocol `pons`;
- generation `v2`;
- chain `eip155:4663`.

Protocol name alone is not sufficient. Factory/deployment identity and capability provenance must be frozen.

Capability evidence may come from the v66 authority model. Source-only or third-party claims cannot populate a capability-dependent causal feature.

## Causal clocks

Separate clocks are mandatory:
- `launch_chain_time`: on-chain launch time;
- `launch_observed_at`: when the collector first knew the launch existed;
- `evidence_observed_at`: when the static launch bundle itself became known.

Static evidence known after the target `as_of` cannot be used.

Historical deployer evidence must:
- be observed by `as_of`;
- be marked complete for its declared scope;
- stop strictly before the launch block.

Prior fingerprint evidence must:
- use only launches strictly before the target launch chain time;
- carry its own knowledge-time `history_observed_at`;
- remain missing if discovered after `as_of`.

Early-activity evidence may be joined only if its own `as_of` is no later than the target cutoff.

## Wallet identity semantics

Unique-buyer, unique-seller and repeated-wallet fields are published only when early-market wallet identity coverage is complete. Partial identity coverage does not become a biased numeric estimate; dependent fields remain missing and the quality flag records the limitation.

## Opening tax

Opening tax is recipient-specific. Therefore an accepted tax observation must preserve:
- token;
- recipient address;
- BPS value;
- chain time;
- observed_at;
- capability name;
- evidence reference.

A value without recipient identity must never be interpreted as the tax a future research wallet would have paid.

## No score

v67 intentionally contains no:
- weighted score;
- FIRE/WATCH/SKIP verdict;
- return-optimized threshold;
- economic PASS classification;
- automatic buy decision.

Third-party heuristics may motivate which raw variables are worth measuring, but their weights do not become project evidence.

## Missingness

Unavailable or non-authoritative evidence remains `None` and is accompanied by data-quality flags where appropriate. Missing evidence is never silently converted to zero/false.

## Evidence hash

The v67 evidence hash covers the output and causal provenance inputs needed to identify the snapshot. Equal final numeric values with different clocks/source references must not be assumed to be the same evidence object.

## What v67 proves

Only that the project can represent these launch characteristics with explicit causal provenance and deployment authority.

It does not prove that any characteristic predicts graduation, return, copyability, or net P&L.

## Future economic use

Before an economic study:
1. freeze the Pons deployment/capabilities with v66;
2. pre-register the launch universe and observation cutoffs;
3. pre-register candidate evidence fields and support requirements;
4. preserve missingness and exact knowledge-time lineage;
5. perform discovery separately from prospective validation;
6. never reuse a discovery sample as its own holdout.
