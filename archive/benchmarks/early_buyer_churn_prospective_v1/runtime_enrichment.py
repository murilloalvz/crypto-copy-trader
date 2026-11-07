from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from benchmarks.early_buyer_churn_v0.run import FEATURE_ID, _derive_feature
from benchmarks.launch_burst_prospective_route_live_v3 import live as live_v3
from benchmarks.launch_burst_prospective_route_paper_v2 import live as paper_v2


VERSION = "early_buyer_churn_prospective_runtime_v1"
EXTERNAL_EVIDENCE_KEY = "early_buyer_churn_prospective_v1"


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out >= 0 else None


class OnlinePumpFeatureStateWithChurnV1(live_v3.OnlinePumpFeatureState):
    """Exact prospective instrumentation for the frozen Early Buyer Churn feature."""

    def __init__(self) -> None:
        super().__init__()
        self.churn_seen_event_keys: set[str] = set()
        self.churn_trades: dict[str, list[dict[str, Any]]] = {}

    def ingest_processed_chunk(self, chunk_dir: Path) -> None:
        super().ingest_processed_chunk(chunk_dir)

        carbon = chunk_dir / "carbon-canonical.jsonl"
        manifest = chunk_dir / "target-manifest.jsonl"
        if not carbon.exists():
            return
        ordered, errors = paper_v2._paired_rows(carbon, manifest)
        if errors:
            raise RuntimeError(
                "early buyer churn prospective chunk pairing errors: "
                + ";".join(errors[:5])
            )

        for row, manifest_row in ordered:
            event_key = str(row.get("event_key") or "").strip()
            if not event_key or event_key in self.churn_seen_event_keys:
                continue
            self.churn_seen_event_keys.add(event_key)
            if row.get("status") != "decoded" or row.get("event_type") != "pump_trade":
                continue

            mint = str(row.get("mint") or "").strip()
            wallet = str(row.get("wallet") or "").strip()
            side = str(row.get("side") or "").strip()
            chain_time = _nonnegative_int(row.get("timestamp"))
            token_amount_raw = _positive_int(row.get("token_amount_raw"))
            wall_ns = _nonnegative_int(manifest_row.get("first_received_wall_ns"))
            if (
                not mint
                or not wallet
                or side not in {"buy", "sell"}
                or chain_time is None
                or token_amount_raw is None
                or wall_ns is None
            ):
                raise RuntimeError(
                    f"invalid decoded Pump trade for churn instrumentation: {event_key}"
                )
            self.churn_trades.setdefault(mint, []).append(
                {
                    "event_key": event_key,
                    "observed_wall_ns": wall_ns,
                    "chain_time": chain_time,
                    "wallet": wallet,
                    "side": side,
                    "token_amount_raw": token_amount_raw,
                }
            )

    def _enrich(self, token_mint: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        enriched = dict(snapshot)
        features = dict(enriched.get("features") or {})
        external = dict(enriched.get("external_evidence") or {})

        if enriched.get("complete") is not True:
            features[FEATURE_ID] = None
            external[EXTERNAL_EVIDENCE_KEY] = {
                "version": VERSION,
                "feature_id": FEATURE_ID,
                "status": "RIGHT_CENSORED",
                "feature_value": None,
                "external_provider_used": False,
                "computed_before_provider_quotes": True,
            }
            enriched["features"] = features
            enriched["external_evidence"] = external
            return enriched

        anchor = self.anchors.get((token_mint, "pump"))
        if not isinstance(anchor, dict):
            raise RuntimeError(f"missing Pump anchor for churn snapshot: {token_mint}")

        result = _derive_feature(
            token_mint=token_mint,
            anchor_wall_ns=int(anchor["observed_wall_ns"]),
            cutoff_wall_ns=int(enriched["decision_cutoff_wall_ns"]),
            chain_t0=int(anchor["chain_t0"]),
            trades=self.churn_trades,
        )
        features[FEATURE_ID] = result[FEATURE_ID]
        external[EXTERNAL_EVIDENCE_KEY] = {
            "version": VERSION,
            "feature_id": FEATURE_ID,
            "status": result["status"],
            "feature_value": result[FEATURE_ID],
            "event_count": result["event_count"],
            "buy_event_count": result["buy_event_count"],
            "sell_event_count": result["sell_event_count"],
            "unique_buy_wallet_count": result["unique_buy_wallet_count"],
            "flipper_wallet_count": result["flipper_wallet_count"],
            "flipper_wallet_share": result["flipper_wallet_share"],
            "total_bought_raw": result["total_bought_raw"],
            "matched_sellback_raw": result["matched_sellback_raw"],
            "unmatched_sell_raw": result["unmatched_sell_raw"],
            "external_provider_used": False,
            "computed_after_causal_window_complete": True,
            "computed_before_provider_quotes": True,
            "decision_cutoff_wall_ns": int(enriched["decision_cutoff_wall_ns"]),
        }
        enriched["features"] = features
        enriched["external_evidence"] = external
        return enriched

    def ready_snapshots(
        self, *, coverage_through_wall_ns: int
    ) -> list[tuple[str, dict[str, Any]]]:
        ready = super().ready_snapshots(
            coverage_through_wall_ns=coverage_through_wall_ns
        )
        return [
            (token_mint, self._enrich(token_mint, snapshot))
            for token_mint, snapshot in ready
        ]

    def right_censored_snapshots(self) -> list[tuple[str, dict[str, Any]]]:
        rows = super().right_censored_snapshots()
        return [
            (token_mint, self._enrich(token_mint, snapshot))
            for token_mint, snapshot in rows
        ]


@contextmanager
def patched_early_buyer_churn_prospective_v1() -> Iterator[None]:
    original_state = live_v3.OnlinePumpFeatureState
    live_v3.OnlinePumpFeatureState = OnlinePumpFeatureStateWithChurnV1
    try:
        yield
    finally:
        live_v3.OnlinePumpFeatureState = original_state
