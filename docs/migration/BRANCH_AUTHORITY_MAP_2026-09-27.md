# Branch Authority Map — 2026-09-27

This file records which branch/SHA is authoritative for each major subsystem at migration time.

## Core rule

The migration code base and the global project state are intentionally different concepts.

Do not force one branch to become the authority for everything.

## Authorities

| Scope | Authority | Freeze SHA | Migration interpretation |
|---|---|---:|---|
| Rust Signal Plane / V7 systems contract | `research/rust-signal-plane-live-shadow-v0` | `4bc59974783d0dd3ad57d9338fbaa5b247c7352a` | primary systems authority and migration base (advanced from `e0f7bd1...` via PR #3 merge, 2026-10-02) |
| Research Plane durability/capacity | `research/rust-signal-plane-live-shadow-v0` | `4bc59974783d0dd3ad57d9338fbaa5b247c7352a` | includes role-normalized queue correction and later successful holdout bridge runs |
| Native Participant Quality V1 | `research/rust-signal-plane-live-shadow-v0` | `4bc59974783d0dd3ad57d9338fbaa5b247c7352a` | formal selector result is KILL |
| V48 / V55 / V68 frozen historical economic lineage | systems branch docs + exact protocol/result docs | `4bc5997...` base | frozen contracts remain binding; do not infer a new verdict from migration work |
| Post-Transition Pullback/Reacceleration V0 | `research/post-transition-pullback-reacceleration-v0` | `730d32c3a0f382a1646976172a4ebd4cd3267252` | later divergent economic/research authority |
| Concentration Decay V0 | `research/post-transition-pullback-reacceleration-v0` | `730d32c3...` | discovery ITERATE, fresh confirmation INCONCLUSIVE support, no second iterate |
| Post-Transition Fresh Economic Discovery V0 | `research/post-transition-pullback-reacceleration-v0` | `730d32c3...` | CLOSED/BURNED; no replacement V0 run |
| future signed Jupiter price-impact semantics | `research/post-transition-pullback-reacceleration-v0` | `730d32c3...` | applies only to future protocols; does not rescue burned V0 |

## Branch divergence

At migration inspection time:

- systems branch: `research/rust-signal-plane-live-shadow-v0 @ 4bc5997...` (advanced from `e0f7bd1...` via PR #3 merge, 2026-10-02)
- economic branch: `research/post-transition-pullback-reacceleration-v0 @ 730d32c3...`
- comparison status: `diverged`
- merge base: `319351ded652af29288552ef1f436fdb8149e81b`
- Post-Transition commits ahead from merge base: 150
- systems-side commits on the other divergent line: 375

This is meaningful scientific lineage, not repository clutter.

## Systems branch evidence

### V7 / Signal Plane

Relevant later systems commits include:

- `013ffbde4226e3f9bf320e37161c8c32c0e243ed` — promote V7 live evidence contract
- `b01c9f47e213cf4371ff61ea1a25e814c6dc6b83` — freeze V7 promotion contract
- `23e7346c634755391387ecf9c3eaea2f9491c7ec` — batch Research Plane persistence
- `c2da6645bfab60f2d31cbaed1960727dc762829e` — batch continuation triggers in Research Plane
- `8fc432d6084842daf285ff227d30ae5c32dee0f9` — add Research Plane headroom for role-normalized load
- `e0f7bd1e239463e67bd680cc8bab1e15c406d52c` — close Native Participant Quality holdout v1

### Research Plane capacity correction

Authority doc:

`docs/role-normalized-research-plane-capacity-incident-2026-09-24.md`

Frozen correction:

- queue 4096 -> 16384
- drain timeout 60s -> 120s
- overflow remains hard FAIL
- dropped records never become acceptable
- no Signal Plane backpressure added

Do not "optimize" this by weakening accounting.

### Native Participant Quality

Authority result:

`docs/native-participant-quality-holdout-v1-result-2026-09-24.md`

Formal classification:

`KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`

Do not promote from descriptive tail-risk separation.

## Post-Transition branch evidence

Latest freeze:

`730d32c3a0f382a1646976172a4ebd4cd3267252`

Important tail commits:

- `3aee9084061bd927f7a9b25e10d1a74a59dcd41d` — close burned Post-Transition fresh discovery V0
- `b076f34fee303e3b61aa3e1ce2f38a994e142183` — freeze closure marker
- `f6f87c2be9f6c6a6e49af013c74560cadd779e90` — block accidental rerun of burned V0
- `682bf939aac6257facf3a6c617cb9c4aae3f5f1d` — future signed price-impact magnitude semantics
- `229e6ea240daea481b3fcedcd5714b85ab3becb4` — test future signed-impact semantics
- `730d32c3a0f382a1646976172a4ebd4cd3267252` — document future signed-impact magnitude semantics

### Burned V0

Closure artifact:

`benchmarks/post_transition_reacceleration_v0/fresh_economic_discovery_v0.closed.json`

Frozen facts:

- `status=CLOSED_BURNED`
- `replacement_run_authorized=false`
- `result_classification=FAIL_POST_TRANSITION_FRESH_ECONOMIC_DISCOVERY_V0`
- `fresh_economic_outcomes_opened=true`
- `episode_count=2`
- `conditional_economic_n=0`

Do not rerun or reinterpret.

### Signed price impact

Future protocol behavior only:

- finite signed `priceImpact` is valid data
- missing/non-finite => unavailable
- magnitude gate uses `abs(priceImpact)`

Burned V0 remains non-usable because its observed magnitudes were approximately 2.512pp and 87.611pp, both above the frozen 2pp maximum.

## If a future task spans authorities

Do not immediately merge branches.

First produce:

1. exact files needed from each line;
2. scientific contracts affected;
3. whether the work is documentation-only, systems-only, or economic;
4. merge/cherry-pick alternatives;
5. evidence that semantics remain equivalent;
6. explicit list of divergent results that must remain historical.

Only then choose an integration strategy.

## Unknown / unvalidated state

The earlier ChatGPT Work execution reportedly created a migration branch/worktree before credits ended, but that branch is not visible on the GitHub remote as of this migration pass.

Therefore:

- no state from that unfinished Work branch is claimed here;
- nothing from it is silently reconstructed;
- if it later appears on GitHub, compare it explicitly against `chore/claude-migration-2026-09-27`.
