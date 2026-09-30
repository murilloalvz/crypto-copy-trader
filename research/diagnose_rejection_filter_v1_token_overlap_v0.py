"""Read-only V1 robustness diagnostic: token overlap across cohorts and a de-duplicated re-read.

PAPER / RESEARCH / READ-ONLY. NON-GATING: it cannot change V1's recorded result nor any V2 gate; it only
says how much V1's independence assumption mattered (the same token can recur as separate episodes in
adjacent cohorts).

Part 1 (outcome-blind, sqlite mode=ro): episodes vs distinct tokens per V1 cohort, tokens shared across
cohorts, overlap with the V0 F1 cohort. Part 2 (descriptive, consumed V1 data): V1 catastrophic rates
after keeping the first episode per token, with the same frozen V1 gates for reference.
"""
from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from pathlib import Path

V1_KEYS = {f"G{i}": f"rejection-filter-v1-20260929-01-G{i}" for i in range(1, 5)}
V0_KEYS = {"F1": "rejection-filter-v0-20260929-01-F1"}
DB = Path(os.getenv("DATABASE_PATH", "data/copytrader.db"))


def overlap_counts(pairs: list[tuple[str, str]]) -> dict:
    """pairs = (cohort, token). Pure, outcome-blind."""
    by_cohort: dict[str, list[str]] = defaultdict(list)
    for cohort, token in pairs:
        by_cohort[cohort].append(token)
    token_cohorts: dict[str, set[str]] = defaultdict(set)
    for cohort, toks in by_cohort.items():
        for t in toks:
            token_cohorts[t].add(cohort)
    episodes = sum(len(v) for v in by_cohort.values())
    return {
        "episodes": episodes,
        "distinct_tokens": len(token_cohorts),
        "repeat_episodes": episodes - len(token_cohorts),
        "tokens_in_more_than_one_cohort": sum(1 for c in token_cohorts.values() if len(c) > 1),
        "per_cohort": {c: {"episodes": len(v), "distinct_tokens": len(set(v))} for c, v in sorted(by_cohort.items())},
    }


def load_pairs(conn, keys: dict[str, str]) -> list[tuple[str, str]]:
    out = []
    for cohort, key in keys.items():
        for (tok,) in conn.execute(
                "SELECT token_mint FROM opportunity_route_research_decisions WHERE acquisition_run_key=?", (key,)):
            out.append((cohort, str(tok)))
    return out


def main() -> int:
    if not DB.is_file():
        raise SystemExit(f"Database not found: {DB}")
    conn = sqlite3.connect(f"file:{DB.resolve().as_posix()}?mode=ro", uri=True, timeout=30)
    v1_pairs, v0_pairs = load_pairs(conn, V1_KEYS), load_pairs(conn, V0_KEYS)
    conn.close()

    print("[Part 1] token overlap, V1 cohorts (outcome-blind)")
    o = overlap_counts(v1_pairs)
    print(f"  episodes={o['episodes']} distinct_tokens={o['distinct_tokens']} repeat_episodes={o['repeat_episodes']} "
          f"tokens_in_>1_cohort={o['tokens_in_more_than_one_cohort']}")
    for c, v in o["per_cohort"].items():
        print(f"  {c}: episodes={v['episodes']} distinct_tokens={v['distinct_tokens']}")
    v1_tokens, v0_tokens = {t for _, t in v1_pairs}, {t for _, t in v0_pairs}
    print(f"  V0 F1 tokens={len(v0_tokens)}; shared with V1={len(v0_tokens & v1_tokens)}")

    print("\n[Part 2] V1 re-read keeping the first episode per token (descriptive, consumed data; NON-GATING)")
    import rejection_filter_holdout_v0_analyze as v0
    import rejection_filter_holdout_v2_analyze as an2

    raw, integrity = an2.load_raw_rows(V1_KEYS)
    rows = an2.prepare_rows_v2(raw)
    post = an2.dedup_first_per_token(rows)
    cohorts = tuple(V1_KEYS)
    for label, kwargs in (("V1 gates (direction in every cohort)", {}), ("direction in >= 3 of 4 cohorts", {"direction_min": 3})):
        r = v0.evaluate(post, cohorts, **kwargs)
        agg = r["aggregate"]["groups"]
        print(f"  [{label}] raw_classification={r['classification']} paired={r['aggregate']['paired']}")
        for g in ("KEPT", "REJECTED"):
            print(f"    {g}: n={agg[g]['n']} catastrophic={agg[g]['catastrophic']} rate={agg[g]['cat_rate_pct']}")
        print(f"    support={r['support_checks']}")
        print(f"    effect={r.get('effect_checks')} values={r.get('effect_values')}")
    print(f"  integrity={integrity}")
    print("\nThis output cannot change any recorded result or any V2 gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
