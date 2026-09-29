# Claude Code Tooling — ECC + Ponytail — 2026-09-27

These are optional **user-level Claude Code tools**. They are not vendored into this repository.

Project-specific rules in `CLAUDE.md` always override generic tooling behavior.

## 1. ECC 2.0

Official source:

`https://github.com/affaan-m/ECC`

Current Claude Code plugin identifier:

`ecc@ecc`

Install inside Claude Code:

```text
/plugin marketplace add https://github.com/affaan-m/ECC
/plugin install ecc@ecc
```

If an old Everything Claude Code 1.x plugin is already installed:

```text
/plugin uninstall everything-claude-code@everything-claude-code
```

Do not intentionally run both old and new ECC plugins at once. That can duplicate skills/hooks.

For this project, ECC is useful for:

- planning;
- scoped implementation;
- code review;
- test discipline;
- security review;
- debugging;
- maintaining explicit working context.

ECC must not override:

- frozen scientific contracts;
- branch authority;
- fail-closed semantics;
- burned-sample rules;
- live-money blocks.

## 2. Ponytail

Official source:

`https://github.com/DietrichGebert/ponytail`

Install inside Claude Code as two separate commands:

```text
/plugin marketplace add DietrichGebert/ponytail
/plugin install ponytail@ponytail
```

Use Ponytail as an **anti-overengineering / scope-control layer**.

Good uses here:

- challenge unnecessary abstractions;
- prefer existing code paths;
- avoid speculative frameworks;
- reduce needless LOC;
- ask whether a dependency is actually required;
- keep fixes local.

Ponytail is NOT allowed to simplify away scientific or systems safety.

Never remove merely because it looks verbose:

- causal clock checks;
- fail-closed validation;
- explicit missingness;
- queue accounting;
- sequence validation;
- durability checks;
- result closure markers;
- protocol hashes;
- preregistered gates;
- regression tests protecting scientific semantics.

For this repo:

`scientific auditability > minimal LOC`

when those goals conflict.

## 3. Suggested Claude session bootstrap

After cloning/switching to the migration branch:

```powershell
git fetch --all --prune
git switch chore/claude-migration-2026-09-27
git status
```

Then start Claude Code from the repository root.

In the first session, tell Claude:

```text
Read CLAUDE.md and docs/migration/START_HERE_CLAUDE_2026-09-27.md first.
Then read docs/migration/BRANCH_AUTHORITY_MAP_2026-09-27.md and
docs/migration/RESEARCH_STATE_LEDGER_2026-09-27.md.

Do not modify code yet.

Summarize:
1. the systems authority branch/SHA;
2. the later economic authority branch/SHA;
3. every currently CLOSED/KILL/INCONCLUSIVE/NOT_EVALUATED experiment listed there;
4. the burned samples;
5. the frozen systems and scientific invariants;
6. the current execution/live-money state;
7. what remains unvalidated in this checkout.

Stop after the summary.
```

Compare Claude's answer with the migration docs before assigning a development task.

## 4. First development-task protocol

For the first real task, use:

```text
Before changing anything:
- identify the authority branch/subsystem for this task;
- read only the directly relevant implementation, tests, protocol and result docs;
- list frozen constraints;
- list what evidence would justify a code change;
- propose the smallest patch;
- state targeted tests.

Do not broaden the task, retune scientific gates, merge research lines, or touch live-money execution.
```

## 5. Do not commit user-global agent config

Do not commit:

- `~/.claude/settings.json`
- plugin cache
- personal MCP credentials
- API keys
- user-level hooks copied from third-party tools

The repo should remain usable without ECC/Ponytail. Those tools improve the agent workflow, not project correctness.
