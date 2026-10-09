# Route Research V68 — Prospective Flow60 Buy-Share Holdout Result

Date: 2026-10-05
Mode: **PAPER / RESEARCH / READ ONLY**

## Final classification

`FAIL_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS`

This is a valid prospective economic rejection, not a systems or collection
failure — the frozen primary gate was actually evaluated, for the first time
in this lineage, after six consecutive systems-stage failures (`v68-04`
through `v68-09`).

## Provenance of this record

Recovered from `v68-10.log`, a full stdout capture the operator uploaded to
this session before an earlier context compaction. The file is UTF-16LE
(`\xff\xfe` BOM) — decoded directly from the raw bytes before extracting the
lines below; no field was retyped from memory. The per-bin descriptive
numbers (median/PF per LOW/HIGH per subcohort, the kind recorded for V48 in
`docs/route-research-v48-prospective-flow60-result-2026-09-07.md`) are **not**
present in this stdout capture — this script's print statements are terser
than V48's and only emit the aggregate gate booleans below. If a fuller
descriptive breakdown is wanted later, it requires the run's own JSON report
artifact from the operator's machine, not reproduced here. The gate booleans
below are sufficient on their own to apply the frozen decision tree.

## Validity gates (systems side, all clean)

- run keys: `v68-10-A`, `v68-10-B` (fresh, confirmed by the run's own
  pre-check)
- `V68 Release Readiness V1`: `PASS_V68_RELEASE_READINESS_V1` (10/10 checks)
- `V68 Solana PubSub Provider Health`: `PASS_V68_SOLANA_PUBSUB_HEALTH`
  (Pump + PumpSwap `logsSubscribe` both acked, `solana-mainnet.streaming.alchemy.com`)
- Signal Plane V7 promotion: authorized, `git_head=a2f1c34f...`,
  `evidence_count=5`
- forward-outcome collection (`[v43-forward]`): both subcohorts reached the
  full `SUBCOHORT_CAP=40` decisions (`scheduled=120` each = 40 x 3 horizons);
  overwhelmingly `AVAILABLE` outcomes across 300s/900s/3600s, with only a
  handful of isolated `PROVIDER_ERROR` rows per horizon (well within the
  frozen per-horizon floor) — no stall, no 429 burst, no lateness breach this
  time; the stall-guard and 429-backoff fixes merged ahead of this run
  (`e4e95e8`, `5ead9ee`/`f865745`) held

Therefore the Flow60 buy-share hypothesis was actually evaluated
prospectively, for the first time in this lineage.

## Frozen primary test

Feature: `flow60_buy_share_pct`

Contract (unchanged, same as every prior attempt):
`('flow60_buy_share_pct', 57.1429, 65.7143, 'LOW', 'HIGH', 900, 5)`
— LOW <= 57.1429, HIGH > 65.7143, favorable = LOW, primary horizon 900s,
minimum support 5 per bin per subcohort.

## Result

```
classification=FAIL_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS
rows_total=80 rows_A=40 rows_B=40
feature_coverage=80/80 (100.0%)
support_ok=True
same_direction_ok=True
favorable_positive_median_both=False
favorable_pf_gt_one_both=False
aggregate_favorable_pf_gt_one=False
aggregate_favorable_mean_without_best_positive=False
```

Unlike V48 (`same_direction_ok=False` — A and B disagreed on direction), V68's
`v68-10` failed with `same_direction_ok=True`: the favorable (LOW) group's
direction was consistent across both subcohorts. The rejection is purely
economic — LOW's median return and profit factor simply did not clear the
PASS bar in either subcohort, nor in aggregate, nor with the best winner
excluded. This is a cleaner, more informative failure than V48's: the signal
is directionally stable, it just does not make money net of nothing (this is
still a no-capital route-only read, before any real execution cost).

## Scientific interpretation

Six systems-stage failures (`v68-04` through `v68-09`) consumed the entire
infra budget before a single economic number existed for this feature. The
tenth and final authorized cycle (`v68-10`) finally reached the gate and
rejected the hypothesis outright, with a clean, consistent-direction failure
— not an ambiguous or contested one.

Per `docs/v68-09-preregistered-decision-tree-2026-10-04.md` (written and
committed before this result existed, branch `research/v68-09-fase-a-prereg`),
branch 3 applies:

> `FAIL_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS` ... V68 fechado
> de vez, pela disciplina de falha do protocolo: sem MID, sem outro horizonte
> (300s/3600s), sem outra feature v55, sem combinar features, sem olhar só uma
> subcohort, sem reusar a amostra.

**V68 is closed permanently.** Do not rescue this sample by:

- promoting MID or any other v55 closed-set feature from this same burned
  sample;
- switching the primary horizon to 300s or 3600s;
- combining `flow60_buy_share_pct` with another feature into a composite
  score;
- looking at only one subcohort;
- reopening or reinterpreting this classification.

Per the same decision tree, the next path toward an edge is explicitly named:
**v60 (Opportunity Wallet Convergence)** and **Bundle Bot Detection V0**
(paired-by-activity placebo), both already drafted in Fase A6:

- `docs/v60-wallet-convergence-discovery-v0-preregistration-DRAFT-2026-10-04.md`
- `docs/bundle-bot-detection-v0-preregistration-DRAFT-2026-10-04.md`
  (noted elsewhere in the registry as blocked on slot/creator observability)

Both remain `RASCUNHO`, awaiting the operator's sign-off — neither is
authorized to run by this record.

## What this FAIL does not prove

Only that the frozen `flow60_buy_share_pct` LOW/HIGH route-only contract, on
this one prospective A/B sample, does not clear its own PASS bar. It does not
prove the feature has no information at any other horizon or cutpoint (that
would require a new, separately preregistered hypothesis on a fresh sample —
not this one), and it says nothing about any other feature in the V55 closed
set.
