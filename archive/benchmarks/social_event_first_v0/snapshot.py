from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any, Iterable

from src.social_event_evidence_v0 import (
    SocialEventEvidenceV0,
    social_event_evidence_from_mapping_v0,
    social_event_evidence_to_dict_v0,
)


SNAPSHOT_VERSION = "social_event_snapshot_v0"
PASS = "PASS_SOCIAL_EVENT_SNAPSHOT_V0"


def _pct(num: int, den: int) -> float | None:
    return 100.0 * num / den if den else None


def _read_jsonl(path: Path) -> list[SocialEventEvidenceV0]:
    rows: list[SocialEventEvidenceV0] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"JSON object required at {path}:{line_number}")
            rows.append(social_event_evidence_from_mapping_v0(payload))
    return rows


def _dedupe(evidence: Iterable[SocialEventEvidenceV0]) -> list[SocialEventEvidenceV0]:
    indexed: dict[str, SocialEventEvidenceV0] = {}
    for item in evidence:
        previous = indexed.get(item.evidence_key)
        if previous is not None and previous != item:
            raise ValueError(f"conflicting duplicate social/event evidence: {item.evidence_key}")
        indexed[item.evidence_key] = item
    return list(indexed.values())


def build_social_event_snapshot_v0(
    *,
    evidence: Iterable[SocialEventEvidenceV0],
    token_mint: str,
    lookback_start_wall_ns: int,
    market_anchor_wall_ns: int,
    decision_cutoff_wall_ns: int,
) -> dict[str, Any]:
    token_mint = str(token_mint).strip()
    if not token_mint:
        raise ValueError("token_mint is required")
    if not (0 < lookback_start_wall_ns <= market_anchor_wall_ns <= decision_cutoff_wall_ns):
        raise ValueError("expected 0 < lookback_start <= market_anchor <= decision_cutoff")

    deduped = _dedupe(evidence)
    eligible = [
        item
        for item in deduped
        if item.token_mint == token_mint
        and lookback_start_wall_ns <= item.causal_available_wall_ns <= decision_cutoff_wall_ns
    ]
    eligible.sort(key=lambda item: (item.causal_available_wall_ns, item.evidence_key))

    source_counts = Counter(item.source_key for item in eligible)
    source_kind_counts = Counter(item.source_kind for item in eligible)
    event_kind_counts = Counter(item.event_kind for item in eligible)
    actor_counts = Counter(item.actor_key for item in eligible if item.actor_key is not None)
    total = len(eligible)
    actor_covered = sum(item.actor_key is not None for item in eligible)
    publication_covered = sum(item.published_at_ns is not None for item in eligible)
    mapping_covered = sum(item.token_mapping_observed_wall_ns is not None for item in eligible)
    pre_anchor = sum(item.causal_available_wall_ns < market_anchor_wall_ns for item in eligible)
    post_anchor = total - pre_anchor

    delays_ms = [
        (item.causal_available_wall_ns - market_anchor_wall_ns) / 1_000_000.0
        for item in eligible
    ]

    evidence_refs = []
    for item in eligible:
        evidence_refs.append(
            {
                "evidence_key": item.evidence_key,
                "source_kind": item.source_kind,
                "source_key": item.source_key,
                "event_kind": item.event_kind,
                "actor_key": item.actor_key,
                "observed_wall_ns": item.observed_wall_ns,
                "token_mapping_observed_wall_ns": item.token_mapping_observed_wall_ns,
                "causal_available_wall_ns": item.causal_available_wall_ns,
                "published_at_ns": item.published_at_ns,
            }
        )

    return {
        "type": "social_event_snapshot",
        "version": SNAPSHOT_VERSION,
        "classification": PASS,
        "token_mint": token_mint,
        "lookback_start_wall_ns": lookback_start_wall_ns,
        "market_anchor_wall_ns": market_anchor_wall_ns,
        "decision_cutoff_wall_ns": decision_cutoff_wall_ns,
        "causal_time_field": "causal_available_wall_ns",
        "features": {
            "observed_event_count": total,
            "unique_source_count": len(source_counts),
            "unique_actor_count": len(actor_counts),
            "pre_anchor_event_count": pre_anchor,
            "post_anchor_event_count": post_anchor,
            "source_kind_counts": dict(sorted(source_kind_counts.items())),
            "event_kind_counts": dict(sorted(event_kind_counts.items())),
            "actor_identity_coverage_pct": _pct(actor_covered, total),
            "published_timestamp_coverage_pct": _pct(publication_covered, total),
            "token_mapping_timestamp_coverage_pct": _pct(mapping_covered, total),
            "top_source_event_share_pct": _pct(max(source_counts.values(), default=0), total),
            "top_actor_event_share_pct": _pct(max(actor_counts.values(), default=0), actor_covered),
            "first_available_delay_ms_from_anchor": delays_ms[0] if delays_ms else None,
            "last_available_delay_ms_from_anchor": delays_ms[-1] if delays_ms else None,
        },
        "evidence_keys": [item.evidence_key for item in eligible],
        "evidence": evidence_refs,
        "guardrails": {
            "published_at_is_metadata_not_causal_clock": True,
            "token_mapping_cannot_be_backdated": True,
            "only_evidence_available_by_decision_cutoff_included": True,
            "no_sentiment_score": True,
            "no_source_weighting": True,
            "no_trade_recommendation": True,
            "no_market_outcome_used": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a causal Social/Event-First snapshot from local JSONL evidence")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--token-mint", required=True)
    parser.add_argument("--lookback-start-wall-ns", type=int, required=True)
    parser.add_argument("--market-anchor-wall-ns", type=int, required=True)
    parser.add_argument("--decision-cutoff-wall-ns", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = _read_jsonl(args.input)
        snapshot = build_social_event_snapshot_v0(
            evidence=evidence,
            token_mint=args.token_mint,
            lookback_start_wall_ns=args.lookback_start_wall_ns,
            market_anchor_wall_ns=args.market_anchor_wall_ns,
            decision_cutoff_wall_ns=args.decision_cutoff_wall_ns,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(snapshot, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_SOCIAL_EVENT_SNAPSHOT_V0", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
