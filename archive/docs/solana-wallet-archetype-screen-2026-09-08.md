# Solana Profitable Wallet Archetype Screen — 2026-09-08

Mode: RETROSPECTIVE DISCOVERY / SCREENING ONLY

## Purpose

Freeze a timestamped screening universe of currently notable Solana memecoin wallets for future v56/v60/v63 research.

This is **not a copy-trading whitelist**. Third-party PnL/win-rate values are volatile analytics snapshots and are not authoritative project accounting. Exact addresses are retained only so later research can reconstruct behavior directly on-chain.

Primary screen source: KOL Explorer public wallet profiles, observed 2026-09-08.

## Current profitable archetype candidates

| Label | Wallet address | Approx 30d PnL | 7d WR | 7d trades | Avg trade | Why it matters for research |
|---|---|---:|---:|---:|---:|---|
| Cented | `CyaE1VxvBrahnPWkqm5VsdCvyS2QmNht2UFrKJHga54o` | +$814.6k | 55.3% | 52,067 | $356 | ultra-high-frequency profitable archetype; wide token breadth |
| Theo | `Bi4rd5FH5bYEN8scZ7wevxNZyNmKHdaBcvewdPFxYdLt` | +$336.6k | 49.9% | 15,952 | $254 | very high-frequency early/nano-cap archetype |
| Cupsey | `2fg5QD1eD7rzNNCsvnhmXFm5hqNgwTTG8p7kQ6f3rx6f` | +$312.3k | 50.3% | 3,047 | source snapshot varies | active nano-cap archetype with materially lower frequency than Cented/Theo |
| Kev | `BTf4A2exGK9BCVDNzy65b9dUzXgMqB4weVkvTMFQsadd` | +$224.5k | 43.4% | 1,193 | source snapshot varies | profitable lower-WR active archetype |
| Cottage | `4UwK5AE6Djdf3MfwtPGE8pFYD47MhU9fiStDVmSHJVMB` | +$96.4k | 46.5% | 4,789 | $406 | speed/flipper archetype with very broad activity |
| Pain | `J6TDXvarvpBdPXTaTU8eJbtso1PUCYKGkVtMKUUY8iEa` | +$75.3k | 36.9% | 1,750 | $1,877 | lower-win-rate / larger-ticket convexity candidate |
| Casino | `8rvAsDKeAcEjEkiZMug9k8v1y8mW6gQQiMobd89Uy7qR` | ~+$72k | ~20–22% | ~1.1k–3.0k depending current view | ~$1.2k in comparison view | extreme winner-dependence candidate; useful counterexample to WR-first ranking |

Source URLs captured for reproducibility:

- https://kolexplorer.com/kol/cented
- https://kolexplorer.com/kol/theo
- https://kolexplorer.com/kol/cupsey
- https://kolexplorer.com/kol/kev
- https://kolexplorer.com/kol/cottage
- https://kolexplorer.com/kol/pain
- https://kolexplorer.com/token/kol/casino
- https://kolexplorer.com/compare/casino-vs-no

## Scientific implications frozen before any local outcome study

### 1. Win rate is not a sufficient wallet objective

The current screen contains profitable wallets around 20–40% win rate and profitable wallets above 50%. Therefore research must not rank wallet archetypes primarily by win rate.

### 2. Frequency is a major confounder

Cented/Theo activity is orders of magnitude different from Pain/Casino-like behavior. Raw PnL comparison across these wallets mixes execution frequency, token breadth, ticket size, holding style and risk tolerance.

Use the project's own `wallet_strategy_lab.py` fingerprints and pre-period diagnostics before cross-wallet comparison.

### 3. External labels are discovery descriptions only

Terms such as nano-cap hunter, speed trader or high-alpha are third-party descriptions. They are not accepted as v60 `strategy_signature` values. Strategy signatures must be frozen from the project's own on-chain behavior fingerprint.

### 4. First causal question is within-wallet, not between-wallet

The preferred v63 question is:

> For the same wallet, what differed before its later exceptional winners versus otherwise comparable entries from that wallet?

Only patterns that later repeat across multiple independent wallet archetypes should be considered candidates for general opportunity intelligence.

### 5. Historical reconstruction remains retrospective discovery

A historical trade downloaded now cannot receive an invented historical `observed_at`. v56 pre-entry reconstruction must distinguish historical chain time from what the project actually knew at the time. Prospective proof requires future monitored entries.

## Candidate research sequence

1. acquire clean local on-chain behavior for each candidate;
2. derive project-owned strategy fingerprints;
3. require adequate sequence/roundtrip coverage;
4. freeze an outcome definition before joining outcomes;
5. build v56 pre-entry snapshots before labels are attached;
6. use v63 exact same-wallet controls;
7. search only for simple pre-entry differences with explicit coverage;
8. check whether the same difference recurs across independent archetypes;
9. any surviving feature remains discovery-only until a fresh prospective holdout.

No address in this document authorizes copying, trading, or live capital.
