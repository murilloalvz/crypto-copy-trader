# GMGN External Intelligence Audit V0

Status: research-only, read-only, no selector changes, no private keys, no capital.

## Scope

This audit treats GMGN as external evidence / enrichment / benchmark / hypothesis source.
Raw chain and our causal capture remain primary scientific evidence.

Safe-use rule:

```text
GMGN dynamic field
-> query request_before
-> API response
-> response_after / local_observed_at
-> only then eligible as prospective evidence
```

Never backfill current GMGN aggregates into an earlier signal and call them causal.

## Current scientific gate

The current preregistered gate is NOT GMGN.

Branch:

`research/early-buyer-prior-quality-replication-v0`

The fresh 900s Participant Quality confirmation must be completed first on the scientific branch.
This audit branch stays isolated so external tooling cannot contaminate that capture or protocol.

## Highest-value capabilities

### 1. Deployer prior history — APPLY_NOW_SAFE acquisition candidate

Command:

```powershell
gmgn-cli portfolio created-tokens --chain sol --wallet <deployer> --order-by token_ath_mc --direction desc --raw
```

Raw useful components include prior launch count, graduation count/rate, token creation timestamps,
ATH market caps, prior launch status and launchpad. These must be snapshotted prospectively before
the current launch decision. Current ATH/open state is not safe to retroactively assign to an older T0.

### 2. Smart Money — TEST_AS_HYPOTHESIS

```powershell
gmgn-cli track smartmoney --chain sol --limit 100 --raw
```

Useful raw fields include transaction hash, maker wallet, side, token, amount, price and event timestamp.
The Smart Money label is GMGN-defined and may change over time, so the label itself is external/opaque
evidence. Any signal test must preserve both event_at and our local observed_at.

### 3. KOL — TEST_AS_HYPOTHESIS

```powershell
gmgn-cli track kol --chain sol --limit 100 --raw
```

Treat as a participant lead, never as BUY => BUY. Same timestamp/freshness requirement as Smart Money.

### 4. Trenches new_creation — BENCHMARK

```powershell
gmgn-cli market trenches --chain sol --type new_creation --launchpad-platform Pump.fun --limit 80 --raw
```

Use first for:

- GMGN creation-time vs chain T0;
- GMGN availability vs our observed_at;
- coverage overlap;
- missing launch analysis.

Dynamic structural fields are safe only as the snapshot observed at that request time.

### 5. Structural / token security — TEST_AS_HYPOTHESIS

```powershell
gmgn-cli token security --chain sol --address <token> --raw
```

Candidate dimensions include holder concentration, creator/dev exposure, bundler/insider/sniper-related
fields where the endpoint provides them. Do not activate vetoes without incremental testing.

## Explicitly not trusted as ground truth

- GMGN wallet-score;
- Smart Money / KOL labels;
- rug score;
- current ATH queried after the target signal;
- current PnL/winrate queried after the target signal;
- trending rank as historical alpha;
- completed-only launch samples.

Use raw components when possible.

## Safe API-key-only setup

For this audit, do NOT run `gmgn-cli config --apply`: the current CLI configuration flow writes a GMGN request-signing private key. We do not need that for the read-only endpoints selected here.

Use only an API key, for example in the current PowerShell session:

```powershell
$env:GMGN_API_KEY = "<set locally; do not paste or commit>"
gmgn-cli config --check
```

The selected sampler does not call holdings, swap, order submission, or follow-wallet. If any sampled capability asks for `GMGN_PRIVATE_KEY`, stop that capability.

## Timing sample

After the current fresh scientific capture has finished, run:

```powershell
powershell -ExecutionPolicy Bypass -File research\external_intelligence\gmgn_capability_audit\timing_sample.ps1
```

The script is read-only. It:

- checks GMGN CLI configuration;
- captures request-before and response-after timestamps;
- queries new Pump.fun launches, Smart Money, KOL and 5m trending;
- never logs an API key;
- never signs or submits a transaction.

Optional environment variables enable targeted wallet/deployer/token samples:

```powershell
$env:GMGN_SAMPLE_WALLET = "<public_wallet>"
$env:GMGN_SAMPLE_DEPLOYER = "<public_deployer>"
$env:GMGN_SAMPLE_TOKEN = "<public_token>"
```

If any command requires GMGN_PRIVATE_KEY, stop that capability and do not configure one.

`portfolio holdings` is explicitly excluded from this phase because current GMGN CLI documentation marks it as critical-auth/private-key gated.

## Scientific integration rule

Every future test is incremental:

```text
baseline signal
vs
baseline signal + one new external evidence family
```

No mega-score and no combined selector until individual/incremental value is established.
