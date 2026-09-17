from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping


VERSION = "coordination_entity_intelligence_v0"

CAUSAL_FEATURE_IDS = (
    "mf_unique_buy_entity_count",
    "mf_top_entity_gross_flow_share_pct",
    "mf_coordination_compression_ratio",
    "mf_entity_repeat_event_share_pct",
    "mf_entity_churn_proxy",
    "mf_funding_linked_buy_wallet_share_pct",
    "mf_deployer_prior_launch_count",
)

POSTDECISION_FEATURE_IDS = (
    "mf_early_buyer_retention_ratio_followup",
    "mf_sell_pressure_followup_ratio",
)

ALL_FEATURE_IDS = CAUSAL_FEATURE_IDS + POSTDECISION_FEATURE_IDS


@dataclass(frozen=True)
class EntityLinkEvidenceV0:
    """Upstream evidence that two wallets likely represent one economic entity.

    This module does not infer these links from outcomes. It only consumes links whose
    observation clock is causal for the requested cutoff.
    """

    left_wallet: str
    right_wallet: str
    observed_wall_ns: int
    relation_type: str
    evidence_source: str


@dataclass(frozen=True)
class FundingRelationEvidenceV0:
    funder_wallet: str
    funded_wallet: str
    observed_wall_ns: int
    evidence_source: str


@dataclass(frozen=True)
class DeployerHistoryEvidenceV0:
    deployer_wallet: str
    observed_wall_ns: int
    history_cutoff_wall_ns: int
    prior_launch_count: int
    evidence_source: str


def _value(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _wallet(row: Any) -> str | None:
    value = _value(row, "wallet_key")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _side(row: Any) -> str | None:
    value = _value(row, "side")
    return value if value in {"buy", "sell"} else None


def _wall_ns(row: Any) -> int | None:
    value = _value(row, "observed_wall_ns")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _gross_ratio(row: Any) -> float | None:
    amount = _finite(_value(row, "quote_amount_raw"))
    reserve = _finite(_value(row, "quote_reserve_raw"))
    if amount is None or reserve is None or amount < 0 or reserve <= 0 or _side(row) is None:
        return None
    return amount / reserve


def _causal_rows(rows: Iterable[Any], cutoff_wall_ns: int) -> list[Any]:
    output = []
    for row in rows:
        observed = _wall_ns(row)
        if observed is not None and observed <= cutoff_wall_ns:
            output.append(row)
    return sorted(
        output,
        key=lambda item: (
            int(_wall_ns(item) or 0),
            str(_value(item, "event_key") or ""),
        ),
    )


def _valid_wallet(value: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError("wallet identifier must be non-empty")
    return value


class _UnionFind:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def add(self, value: str) -> None:
        self.parent.setdefault(value, value)

    def find(self, value: str) -> str:
        self.add(value)
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        lroot, rroot = self.find(left), self.find(right)
        if lroot == rroot:
            return
        # Stable canonical representative keeps replay deterministic.
        if lroot < rroot:
            self.parent[rroot] = lroot
        else:
            self.parent[lroot] = rroot


def _entity_map_v0(
    wallets: Iterable[str],
    entity_links: Iterable[EntityLinkEvidenceV0],
    *,
    cutoff_wall_ns: int,
) -> tuple[dict[str, str], int]:
    wallet_set = {_valid_wallet(wallet) for wallet in wallets}
    uf = _UnionFind(wallet_set)
    accepted = 0
    for link in entity_links:
        if not isinstance(link.observed_wall_ns, int) or link.observed_wall_ns <= 0:
            raise ValueError("entity link observed_wall_ns must be a positive integer")
        if link.observed_wall_ns > cutoff_wall_ns:
            continue
        left = _valid_wallet(link.left_wallet)
        right = _valid_wallet(link.right_wallet)
        if not str(link.relation_type).strip() or not str(link.evidence_source).strip():
            raise ValueError("entity link must declare relation_type and evidence_source")
        uf.union(left, right)
        wallet_set.update((left, right))
        accepted += 1
    return {wallet: uf.find(wallet) for wallet in sorted(wallet_set)}, accepted


def _causal_funding_relations(
    relations: Iterable[FundingRelationEvidenceV0],
    *,
    cutoff_wall_ns: int,
) -> list[FundingRelationEvidenceV0]:
    output = []
    for relation in relations:
        if not isinstance(relation.observed_wall_ns, int) or relation.observed_wall_ns <= 0:
            raise ValueError("funding relation observed_wall_ns must be a positive integer")
        if relation.observed_wall_ns > cutoff_wall_ns:
            continue
        _valid_wallet(relation.funder_wallet)
        _valid_wallet(relation.funded_wallet)
        if not str(relation.evidence_source).strip():
            raise ValueError("funding relation must declare evidence_source")
        output.append(relation)
    return output


def _deployer_prior_launch_count(
    evidence: Iterable[DeployerHistoryEvidenceV0],
    *,
    deployer_wallet: str | None,
    cutoff_wall_ns: int,
) -> int | None:
    if not deployer_wallet:
        return None
    deployer = _valid_wallet(deployer_wallet)
    eligible = []
    for item in evidence:
        if _valid_wallet(item.deployer_wallet) != deployer:
            continue
        if item.prior_launch_count < 0:
            raise ValueError("prior_launch_count must be non-negative")
        if item.observed_wall_ns <= 0 or item.history_cutoff_wall_ns <= 0:
            raise ValueError("deployer history clocks must be positive")
        # Both the observation itself and the history horizon it summarizes must be causal.
        if item.observed_wall_ns <= cutoff_wall_ns and item.history_cutoff_wall_ns <= cutoff_wall_ns:
            eligible.append(item)
    if not eligible:
        return None
    latest = max(
        eligible,
        key=lambda item: (item.history_cutoff_wall_ns, item.observed_wall_ns, item.prior_launch_count),
    )
    return int(latest.prior_launch_count)


def coordination_features_v0(
    rows: Iterable[Any],
    *,
    decision_cutoff_wall_ns: int,
    entity_links: Iterable[EntityLinkEvidenceV0] = (),
    funding_relations: Iterable[FundingRelationEvidenceV0] = (),
    deployer_wallet: str | None = None,
    deployer_history: Iterable[DeployerHistoryEvidenceV0] = (),
) -> dict[str, Any]:
    """Compute diagnostic-only entity/coordination features available by decision cutoff.

    Entity links and history are externally supplied evidence with their own observation clocks.
    Links observed after the decision cutoff are ignored rather than backdated. Funding relations
    are measured separately and never imply common entity ownership by themselves.
    """

    if not isinstance(decision_cutoff_wall_ns, int) or isinstance(decision_cutoff_wall_ns, bool):
        raise ValueError("decision_cutoff_wall_ns must be an integer")
    if decision_cutoff_wall_ns <= 0:
        raise ValueError("decision_cutoff_wall_ns must be positive")

    causal = _causal_rows(rows, decision_cutoff_wall_ns)
    identified_wallets = {_wallet(row) for row in causal if _wallet(row) is not None}
    entity_map, accepted_entity_links = _entity_map_v0(
        (wallet for wallet in identified_wallets if wallet is not None),
        entity_links,
        cutoff_wall_ns=decision_cutoff_wall_ns,
    )

    buy_rows = [row for row in causal if _side(row) == "buy"]
    buy_wallets = {_wallet(row) for row in buy_rows if _wallet(row) is not None}
    buy_identity_complete = bool(buy_rows) and len(buy_wallets) > 0 and all(
        _wallet(row) is not None for row in buy_rows
    )
    all_identity_complete = bool(causal) and all(_wallet(row) is not None for row in causal)

    unique_buy_entity_count = None
    compression_ratio = None
    if buy_identity_complete:
        buy_entities = {entity_map.get(str(wallet), str(wallet)) for wallet in buy_wallets}
        unique_buy_entity_count = len(buy_entities)
        if unique_buy_entity_count > 0:
            compression_ratio = len(buy_wallets) / unique_buy_entity_count

    top_entity_share = None
    repeat_entity_event_share = None
    entity_churn_proxy = None
    valid_flow_rows = all_identity_complete and all(_gross_ratio(row) is not None for row in causal)
    if valid_flow_rows:
        entity_gross: dict[str, float] = defaultdict(float)
        entity_events: dict[str, int] = defaultdict(int)
        entity_buy_gross: dict[str, float] = defaultdict(float)
        entity_sell_gross: dict[str, float] = defaultdict(float)
        for row in causal:
            wallet = str(_wallet(row))
            entity = entity_map.get(wallet, wallet)
            gross = float(_gross_ratio(row) or 0.0)
            entity_gross[entity] += gross
            entity_events[entity] += 1
            if _side(row) == "buy":
                entity_buy_gross[entity] += gross
            else:
                entity_sell_gross[entity] += gross
        total_gross = sum(entity_gross.values())
        if total_gross > 0:
            top_entity_share = 100.0 * max(entity_gross.values(), default=0.0) / total_gross
            matched_turnover = sum(
                2.0 * min(entity_buy_gross[entity], entity_sell_gross[entity])
                for entity in entity_gross
            )
            entity_churn_proxy = matched_turnover / total_gross
        event_count = sum(entity_events.values())
        if event_count > 0:
            repeat_entity_event_share = 100.0 * sum(
                max(0, count - 1) for count in entity_events.values()
            ) / event_count

    causal_funding = _causal_funding_relations(
        funding_relations,
        cutoff_wall_ns=decision_cutoff_wall_ns,
    )
    funding_linked_buy_share = None
    if buy_identity_complete:
        funded = {str(item.funded_wallet).strip() for item in causal_funding}
        funding_linked_buy_share = (
            100.0 * len({wallet for wallet in buy_wallets if wallet in funded}) / len(buy_wallets)
            if buy_wallets
            else None
        )

    deployer_prior_launch_count = _deployer_prior_launch_count(
        deployer_history,
        deployer_wallet=deployer_wallet,
        cutoff_wall_ns=decision_cutoff_wall_ns,
    )

    features = {
        "mf_unique_buy_entity_count": unique_buy_entity_count,
        "mf_top_entity_gross_flow_share_pct": top_entity_share,
        "mf_coordination_compression_ratio": compression_ratio,
        "mf_entity_repeat_event_share_pct": repeat_entity_event_share,
        "mf_entity_churn_proxy": entity_churn_proxy,
        "mf_funding_linked_buy_wallet_share_pct": funding_linked_buy_share,
        "mf_deployer_prior_launch_count": deployer_prior_launch_count,
    }
    return {
        "version": VERSION,
        "inference_role": "DISCOVERY_DIAGNOSTIC_ONLY",
        "selector_eligible": False,
        "threshold_defined": False,
        "decision_cutoff_wall_ns": decision_cutoff_wall_ns,
        "raw_unique_buy_wallet_count": len(buy_wallets) if buy_identity_complete else None,
        "estimated_unique_buy_entity_count": unique_buy_entity_count,
        "accepted_causal_entity_link_count": accepted_entity_links,
        "accepted_causal_funding_relation_count": len(causal_funding),
        "features": features,
    }


def postdecision_coordination_outcomes_v0(
    early_rows: Iterable[Any],
    followup_rows: Iterable[Any],
    *,
    decision_cutoff_wall_ns: int,
    followup_cutoff_wall_ns: int,
    entity_links: Iterable[EntityLinkEvidenceV0] = (),
) -> dict[str, Any]:
    """Future-dependent diagnostics. These outputs must never be detector inputs."""

    if followup_cutoff_wall_ns <= decision_cutoff_wall_ns:
        raise ValueError("followup cutoff must be after decision cutoff")
    early = _causal_rows(early_rows, decision_cutoff_wall_ns)
    followup = [
        row
        for row in _causal_rows(followup_rows, followup_cutoff_wall_ns)
        if int(_wall_ns(row) or 0) > decision_cutoff_wall_ns
    ]
    all_wallets = {
        wallet
        for row in [*early, *followup]
        for wallet in [_wallet(row)]
        if wallet is not None
    }
    entity_map, _ = _entity_map_v0(
        all_wallets,
        entity_links,
        cutoff_wall_ns=followup_cutoff_wall_ns,
    )

    early_buy_rows = [row for row in early if _side(row) == "buy"]
    followup_buy_rows = [row for row in followup if _side(row) == "buy"]
    retention = None
    if early_buy_rows and all(_wallet(row) is not None for row in early_buy_rows) and all(
        _wallet(row) is not None for row in followup_buy_rows
    ):
        early_entities = {
            entity_map.get(str(_wallet(row)), str(_wallet(row))) for row in early_buy_rows
        }
        followup_buy_entities = {
            entity_map.get(str(_wallet(row)), str(_wallet(row))) for row in followup_buy_rows
        }
        if early_entities:
            retention = len(early_entities & followup_buy_entities) / len(early_entities)

    sell_pressure = None
    gross_values = [_gross_ratio(row) for row in followup]
    if followup and not any(value is None for value in gross_values):
        gross_total = sum(float(value) for value in gross_values if value is not None)
        if gross_total > 0:
            sell_gross = sum(
                float(value)
                for row, value in zip(followup, gross_values)
                if value is not None and _side(row) == "sell"
            )
            sell_pressure = sell_gross / gross_total

    return {
        "version": VERSION,
        "inference_role": "POSTDECISION_DIAGNOSTIC_OUTCOME_ONLY",
        "selector_eligible": False,
        "future_dependent": True,
        "decision_cutoff_wall_ns": decision_cutoff_wall_ns,
        "followup_cutoff_wall_ns": followup_cutoff_wall_ns,
        "features": {
            "mf_early_buyer_retention_ratio_followup": retention,
            "mf_sell_pressure_followup_ratio": sell_pressure,
        },
    }


def feature_definitions_v0() -> dict[str, dict[str, Any]]:
    causal_common = {
        "track": "market_first",
        "selector_eligible": False,
        "diagnostic_only": True,
        "execution_only": False,
        "future_dependent": False,
        "threshold_defined": False,
        "causal_availability": "at_or_before_decision_cutoff_only",
    }
    future_common = {
        "track": "market_first",
        "selector_eligible": False,
        "diagnostic_only": True,
        "execution_only": False,
        "future_dependent": True,
        "threshold_defined": False,
        "causal_availability": "after_decision_followup_only",
    }
    return {
        "mf_unique_buy_entity_count": {**causal_common, "description": "Estimated BUY-entity connected-component count using only causal entity-link evidence."},
        "mf_top_entity_gross_flow_share_pct": {**causal_common, "description": "Largest estimated entity share of reserve-normalized gross flow."},
        "mf_coordination_compression_ratio": {**causal_common, "description": "Raw unique BUY-wallet count divided by estimated BUY-entity count; 1 means no observed compression."},
        "mf_entity_repeat_event_share_pct": {**causal_common, "description": "Share of identified causal events beyond the first event per estimated entity."},
        "mf_entity_churn_proxy": {**causal_common, "description": "Entity-level matched buy/sell gross turnover divided by total gross turnover; diagnostic proxy, not a wash-trading claim."},
        "mf_funding_linked_buy_wallet_share_pct": {**causal_common, "description": "Share of BUY wallets with a causally observed inbound funding relationship; funding does not itself merge entities."},
        "mf_deployer_prior_launch_count": {**causal_common, "description": "Prior launch count from deployer history whose observation and summarized-history cutoffs are both no later than the decision cutoff."},
        "mf_early_buyer_retention_ratio_followup": {**future_common, "description": "Fraction of early BUY entities that BUY again during the declared post-decision followup window."},
        "mf_sell_pressure_followup_ratio": {**future_common, "description": "Post-decision SELL gross flow divided by total followup gross flow."},
    }
