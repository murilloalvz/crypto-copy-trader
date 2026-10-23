# Wallet Cohort v65 — Pre-Registered Manifest Protocol

Date: 2026-09-08
Mode: PAPER / RESEARCH / READ ONLY

## Purpose

Make future v60 smart-wallet convergence studies resistant to retroactive cohort selection.

A cohort is not merely a Python list supplied to a feature function. Before the first eligible episode of a prospective study, the exact membership and supporting evidence metadata must be frozen into a deterministic manifest and committed to the repository.

## Manifest contents

Each member carries:

- chain namespace/reference;
- exact wallet address;
- project-owned strategy signature;
- evidence-version identifier;
- `evidence_as_of` cutoff used to characterize the wallet.

The manifest carries:

- `cohort_key`;
- `registered_at`;
- canonical sorted membership;
- deterministic SHA-256 over the complete payload.

Member evidence must be strictly older than manifest registration.

## Temporal gate

For an episode to use a manifest:

`manifest.registered_at < episode.as_of`

In addition, prospective audit must verify repository history shows the exact manifest hash was committed before the first eligible episode/entry. The timestamp field and hash alone are not treated as proof of wall-clock chronology because a caller could fabricate a backdated value locally.

## Chain identity

EVM addresses are normalized lowercase and tied to an EIP-155 chain reference. Solana addresses remain case-sensitive opaque identifiers. The same textual address on different chains is a different identity.

v60 currently reads the Solana market-observation store, so v65 bridges one explicit chain slice at a time. Cross-chain members are never silently mixed into a v60 call.

## What the hash protects

Changing any of the following changes the manifest digest:

- wallet membership;
- strategy signature;
- evidence version;
- evidence cutoff;
- chain identity;
- cohort key;
- registration time.

This makes the exact prospective cohort auditable after the fact.

## What v65 does not prove

A pre-registered cohort is not necessarily profitable, independent, copyable or high quality. Separate research must establish those properties.

Distinct wallet addresses are not proof of distinct beneficial owners. Funding/deployer graph work remains separate.

## Code

- `src/wallet_cohort_manifest_v65.py`
- `tests/test_wallet_cohort_manifest_v65.py`

## Future use

No current wallet screen is being promoted into a v65 prospective cohort yet. The 2026-09-08 wallet archetype screen is retrospective discovery only.

Before a live v60 economic study:

1. reconstruct project-owned behavior fingerprints from clean pre-period on-chain data;
2. define eligibility without looking at future episode outcomes;
3. build v65 manifest;
4. commit manifest;
5. only then begin fresh episode collection.
