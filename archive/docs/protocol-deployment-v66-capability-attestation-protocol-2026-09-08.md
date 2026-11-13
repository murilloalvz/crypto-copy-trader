# Protocol Deployment v66 — Capability Attestation Protocol

Date: 2026-09-08
Mode: PAPER / RESEARCH / READ ONLY

## Motivation

A protocol name or source repository is not sufficient identity for chain-specific research. Deployments can rotate, multiple generations can coexist, source can move ahead of deployed bytecode, and third-party tooling can describe capabilities that are not yet verified by this project.

This became concrete during Pons v2 research: the current public factory source references opening snipe-tax configuration/exemptions while the simultaneously inspected bonding-curve source did not expose the corresponding runtime methods. Separate third-party tooling reports those methods on a deployed curve. The project must fail closed rather than choosing whichever description is convenient.

## Deployment identity

Every protocol-specific capability study must freeze:

- protocol key;
- protocol generation;
- canonical chain namespace/reference;
- exact deployment address;
- attestation `observed_at`;
- runtime code hash when independently available;
- source commit SHA when independently pinned;
- per-capability evidence.

The attestation receives a deterministic SHA-256 digest over the canonical payload.

## Capability evidence classes

- `deployed_call_succeeded`: this project observed the deployed contract successfully answer the specific read capability.
- `deployed_event_observed`: this project observed the specific event from the deployment.
- `verified_runtime_source_match`: runtime/source equivalence has been independently verified for the relevant semantics.
- `source_only`: capability exists only in inspected source.
- `third_party_claim`: another project/tool reports the capability.
- `conflicting`: available evidence conflicts or cannot be reconciled.

## Authority rules

For a runtime READ feature, accepted authority is only:

- `deployed_call_succeeded`; or
- `verified_runtime_source_match`.

For an EVENT parser, accepted authority is only:

- `deployed_event_observed`; or
- `verified_runtime_source_match`.

`source_only`, `third_party_claim`, and `conflicting` are never enough to turn a protocol-specific field into causal economic evidence.

## Current Pons example

Current source-repository documentation identifies a Robinhood Chain Pons v2 factory at:

`0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e`

This address is a research target, not yet a v66 runtime-attested deployment in this project.

Opening-tax semantics are especially restricted: source and third-party observations are useful discovery evidence, but the field may enter a future collector only after this project independently observes the relevant deployed capability or verifies runtime/source equivalence.

## Temporal rule

Each capability evidence item carries `observed_at` and cannot postdate the attestation cutoff.

A later attestation can supersede an earlier one for future data, but must never rewrite old research rows. Persist the attestation digest with any future protocol-specific acquisition so historic rows remain interpretable under the exact capability set known then.

## What v66 prevents

- hardcoding one mutable protocol address forever;
- treating GitHub `main` as deployed runtime truth;
- silently borrowing a third-party ABI as authoritative evidence;
- mixing V1/V2 or old/new factory events under one semantic label;
- changing parser semantics after seeing economic outcomes.

## Code

- `src/protocol_deployment_attestation_v66.py`
- `tests/test_protocol_deployment_attestation_v66.py`

## What PASS means

A green v66 implementation proves deterministic deployment/capability identity and fail-closed authority rules.

It does NOT verify the current Pons deployment itself, establish any economic edge, authorize a collector, or prove a third-party runtime claim. A separate read-only deployment audit is required after the active Solana v55 experiment is closed or when such audit can be performed without competing with it.
