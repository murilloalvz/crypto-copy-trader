# Market Regime Detector Decision — 2026-09-09

## Status

**Synthetic behavior verdict:**

- River Page-Hinkley default (`mode="both"`) -> **PROMISING_BASELINE_CANDIDATE**
- River ADWIN default -> **DO_NOT_PROMOTE_DEFAULT; REVIEW TRANSIENT SENSITIVITY**
- custom CUSUM/Page-Hinkley implementation -> **DEFER**
- Hawkes process -> **DEFER**

This is a detector-behavior verdict only. It is not an economic-edge verdict and it does not authorize a signal, ranker, threshold, live execution, V68, or convergence with Social/Event-First.

## Frozen benchmark

Version: `market_regime_detector_v0`

Library used in CI: River 0.26.1.

No detector parameter tuning and no economic outcomes were used.

Frozen scenarios:
- stable low intensity;
- abrupt persistent increase;
- abrupt persistent decrease;
- short 8-observation upward burst;
- gradual persistent increase.

## Results

### Stable low

- Page-Hinkley: 0 detections
- ADWIN: 0 detections

Aggregate stable false alarms: 0.

### Abrupt increase, change index 180

- Page-Hinkley: first detection 188, delay 8
- ADWIN: first detection 191, delay 11
- no pre-change detections

### Abrupt decrease, change index 180

- Page-Hinkley: first detection 188, delay 8
- ADWIN: first detection 191, delay 11
- no pre-change detections

### Short upward burst

The high-intensity burst occupies indices 180-187 inclusive and then reverts to baseline.

- Page-Hinkley: no detection
- ADWIN: detection 191

Therefore ADWIN's documented defaults reacted to this transient after the eight-point pulse had already ended in the frozen benchmark. For our initial Market-First regime semantic, which should distinguish persistent state changes from a very short pulse unless evidence says otherwise, this is useful negative evidence against promoting ADWIN defaults unchanged.

### Gradual increase, change index 180

- Page-Hinkley: detections 226, 290; first delay 46
- ADWIN: detections 223, 287; first delay 43
- no pre-change detections

## Interpretation

Both maintained detectors can recognize persistent upward, downward, and gradual changes in the frozen synthetic intensity series. Page-Hinkley is the better **first descriptive baseline candidate** because:

1. it matched both abrupt directions;
2. it had no stable false alarms in this benchmark;
3. it ignored the intentionally short pulse that ADWIN default treated as a change;
4. using the maintained River implementation avoids a custom CUSUM implementation before evidence requires one.

This does **not** prove Page-Hinkley is economically superior. The next experiment must use real causal market streams and measure descriptive properties such as detection lead time, persistence, alert frequency, lifecycle position, missingness, and later outcome association without selecting/tuning parameters on the evaluation set.

## Critical input-boundary rule

A detector input series must not convert unobserved time into observed zero activity.

For a fixed-time event-intensity series:
- `0` is valid only when collector coverage proves the interval was observed and no eligible events occurred;
- an interval without demonstrated collector coverage is `MISSING`, not zero;
- market/chain time determines bin membership only after the event has passed the observation-time availability gate;
- exact mint isolation is mandatory;
- later/backfilled events cannot alter an earlier frozen T0 feature event.

This rule is especially important for the Helius historical signature corpus: it proves transaction/event content but it is not continuous live collector coverage and therefore cannot safely fill all empty seconds as zero.

## Next experiment

Build a research-only causal intensity adapter that consumes:
- exact-mint market trade observations;
- explicit observation/coverage intervals;
- fixed one-second or otherwise frozen bins;

and emits:
- observed event count for covered bins;
- explicit missing bins when coverage is unknown;
- provenance/coverage metadata;
- a Page-Hinkley descriptive regime event only across valid observed input points.

Do not tune Page-Hinkley parameters in this step. If defaults fail on real replay, classify the failure before proposing parameter changes.

## Frozen non-conclusions

This work does not establish that:
- a regime change predicts profit;
- a faster detection is always better;
- a short burst should always be ignored;
- Page-Hinkley defaults are production parameters;
- ADWIN is unsuitable in general;
- regime detection should replace the frozen Radar;
- regime evidence should be combined with Social/Event evidence yet.
