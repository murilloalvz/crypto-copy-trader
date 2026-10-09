# Native Participant Quality Holdout V1 — Result — 2026-09-24

Mode: PAPER / RESEARCH / CLOSED FROZEN SELECTOR / NO LIVE MONEY

## Final classification

`KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`

Fresh holdout run keys:

- `participant-quality-native-holdout-20260924-01-H1`
- `participant-quality-native-holdout-20260924-01-H2`

Both cohorts passed the Signal Plane -> Research Plane -> route-research bridge and the 300/900
forward collector with lateness p95 = 1 second.

## Frozen rule tested

Feature:

`native_participant_prior_900_route_quote_return_median_of_wallet_medians_pct`

Frozen outcome-blind cutoff:

`-65.65233776856643`

Frozen favorable direction:

`HIGH`

No cutoff movement, direction flip, subgroup rescue, horizon substitution or H3 extension is
authorized by this result.

## Support

H1:

- episodes = 40
- feature known = 30
- coverage = 75.0%
- paired 900s outcomes = 28
- HIGH = 19
- LOW = 9
- HIGH median = -25.642314%
- LOW median = -99.255575%

H2:

- episodes = 40
- feature known = 32
- coverage = 80.0%
- paired 900s outcomes = 28
- HIGH = 20
- LOW = 8
- HIGH median = -13.929804%
- LOW median = -99.969114%

Aggregate:

- paired = 56
- Spearman(feature, 900s return) = +0.331123
- HIGH n = 39
- LOW n = 17
- HIGH median = -20.364707%
- LOW median = -99.510617%
- HIGH mean without best = -26.101673%
- LOW mean without best = -53.718102%
- HIGH catastrophic-loss rate (<= -80%) = 15.384615%
- LOW catastrophic-loss rate = 70.588235%
- HIGH profit factor = 0.443728
- LOW profit factor = 0.465290

All preregistered support gates passed.

## Effect gates

PASS:

- aggregate Spearman positive;
- aggregate HIGH median > LOW median;
- HIGH median > LOW median in H1;
- HIGH median > LOW median in H2;
- aggregate HIGH mean-without-best > LOW;
- aggregate HIGH catastrophic tail not worse than LOW.

FAIL:

- aggregate HIGH profit factor > LOW profit factor.

Because the protocol required every frozen effect gate to pass once support was sufficient, the
selection-edge candidate is KILL.

## Interpretation

Participant Quality showed strong prospective separation of severe downside risk in this sample:
HIGH had much better medians and a substantially lower catastrophic-loss rate than LOW.

That descriptive result does not rescue the frozen selector. Profit factor did not improve, and both
groups remained below PF = 1 at the 900-second route-only horizon. The preregistered entry-selector
claim is therefore closed.

A future, separately preregistered hypothesis may study Participant Quality specifically as a
tail-risk / rejection dimension rather than an entry-alpha selector. That would be a new hypothesis
generated from consumed data and would require new independent fresh evidence. It is not opened or
promoted by this result.

## Scientific disposition

- exact frozen Participant Quality selector: CLOSED / KILL;
- no automatic H3;
- no cutoff retuning;
- no direction flip;
- no 300s/3600s replacement primary;
- no integration into live entry score;
- no live-money authorization;
- consumed H1/H2 may be used only for diagnostics / future hypothesis generation, never for
  validation of a rule derived from them.

The Market-First search for selection edge continues.
