# Claude Migration Package

Migration date: 2026-09-27

Migration branch:

`chore/claude-migration-2026-09-27`

Technical base:

`research/rust-signal-plane-live-shadow-v0 @ e0f7bd1e239463e67bd680cc8bab1e15c406d52c`

Later divergent economic authority:

`research/post-transition-pullback-reacceleration-v0 @ 730d32c3a0f382a1646976172a4ebd4cd3267252`

## Read order

### For Claude Code

1. `/CLAUDE.md`
2. `START_HERE_CLAUDE_2026-09-27.md`
3. `BRANCH_AUTHORITY_MAP_2026-09-27.md`
4. `CODEBASE_MAP_2026-09-27.md`
5. `RESEARCH_STATE_LEDGER_2026-09-27.md`
6. branch-local `/PROJECT_CONTEXT.md`
7. exact protocol/result docs for the task

### For the human operator

1. `START_HERE_CLAUDE_2026-09-27.md`
2. `CLAUDE_TOOLING_ECC_PONYTAIL_2026-09-27.md`
3. `BRANCH_AUTHORITY_MAP_2026-09-27.md`

## Files

### `/CLAUDE.md`

Persistent agent operating contract:

- product direction
- branch authority
- scientific constraints
- coding discipline
- Git discipline
- ECC/Ponytail precedence
- default evidence/test behavior

### `START_HERE_CLAUDE_2026-09-27.md`

Full onboarding handoff:

- why the migration base was selected
- why global state is split across branches
- current systems state
- economic/research state
- key frozen hypotheses
- burned samples
- execution maturity
- local bootstrap

### `BRANCH_AUTHORITY_MAP_2026-09-27.md`

Prevents accidental flattening of divergent research lines.

Includes:

- authority by subsystem
- freeze SHAs
- key evidence commits
- unvalidated Work-branch note

### `RESEARCH_STATE_LEDGER_2026-09-27.md`

Compact scientific disposition index:

- PASS
- FAIL
- KILL
- INCONCLUSIVE
- CLOSED_BURNED
- NOT_EVALUATED
- BLOCKED

Formal result docs remain authoritative.

### `CODEBASE_MAP_2026-09-27.md`

Navigation map for the main Signal Plane, Research Plane, V55/V68, Participant Quality, stream, hazard, route-research and Post-Transition code/test surfaces.

### `CLAUDE_TOOLING_ECC_PONYTAIL_2026-09-27.md`

Optional Claude Code setup:

- ECC 2.0 install
- Ponytail install
- project-specific restrictions
- first-session verification prompt

## Migration invariants

The package intentionally does NOT:

- merge systems and Post-Transition branches;
- cherry-pick economic implementation into systems;
- rewrite experimental history;
- alter detector thresholds;
- alter V68;
- rerun burned experiments;
- change Rust hot-path code;
- authorize live money;
- add private-key handling;
- change production dependencies.

## Unfinished ChatGPT Work migration

A previous Work execution reportedly created a local migration branch/worktree before credits ended.

During this migration pass, no separate Work migration branch was visible on the GitHub remote.

Therefore the current package:

- does not claim to contain unseen Work-only changes;
- does not reconstruct them by guess;
- records the known migration requirements independently;
- should be compared explicitly if the Work branch is later recovered/pushed.

## Acceptance checklist

Migration package is acceptable when a fresh Claude Code session can correctly state:

- [ ] systems authority branch + SHA
- [ ] later economic authority branch + SHA
- [ ] why the branches must not be casually merged
- [ ] V48 state
- [ ] V55 state
- [ ] V68 state
- [ ] Native Participant Quality formal KILL
- [ ] Concentration Decay fresh INCONCLUSIVE support state
- [ ] Post-Transition V0 CLOSED/BURNED state
- [ ] why signed price-impact semantics do not rescue V0
- [ ] current systems gates
- [ ] current live-money block
- [ ] difference between systems PASS and economic edge
- [ ] any state marked unvalidated

## First acceptance prompt

Use this in a fresh Claude Code session:

```text
Read CLAUDE.md and every file in docs/migration, but do not edit anything.

Then produce a migration acceptance report containing:
- systems authority branch/SHA;
- later economic authority branch/SHA;
- current formal scientific dispositions;
- burned/consumed samples;
- frozen gates and invariants;
- live-money/execution state;
- known branch divergence;
- all facts marked unvalidated.

For every scientific status, point to the exact repository file that is its authority.

Do not propose code changes yet.
```

If the report is wrong, fix understanding before development.
