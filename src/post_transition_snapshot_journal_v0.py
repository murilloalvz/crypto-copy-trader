from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

from src.post_transition_reacceleration_v0 import PostTransitionSnapshot


VERSION = "post_transition_snapshot_journal_v0"
GENESIS_HASH = "0" * 64


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def snapshot_key(snapshot: PostTransitionSnapshot) -> str:
    identity = snapshot.identity
    pool = str(identity.get("pool") or "").strip()
    if not pool:
        raise ValueError("snapshot identity missing pool")
    arrival = snapshot.as_of_arrival_index
    if arrival is None:
        raise ValueError("immutable snapshot requires as_of_arrival_index")
    return (
        f"{pool}:"
        f"{int(snapshot.as_of_observed_at)}:"
        f"{int(arrival)}"
    )


class ImmutableSnapshotJournalV0:
    """Append-only, hash-chained research snapshot journal.

    Existing records are verified on open. Re-appending one exact snapshot key
    is idempotent; reusing a key with a different payload raises.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records_by_key: dict[str, dict[str, Any]] = {}
        self._last_hash = GENESIS_HASH
        self._sequence = 0
        if self.path.exists():
            self._load_and_verify()

    def _load_and_verify(self) -> None:
        previous = GENESIS_HASH
        sequence = 0
        records: dict[str, dict[str, Any]] = {}

        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"journal line {line_number} is not an object")
            expected_sequence = sequence + 1
            if int(row.get("sequence") or 0) != expected_sequence:
                raise ValueError("snapshot journal sequence mismatch")
            if row.get("previous_record_hash_sha256") != previous:
                raise ValueError("snapshot journal previous-hash mismatch")
            stored_hash = str(row.get("record_hash_sha256") or "")
            unsigned = dict(row)
            unsigned.pop("record_hash_sha256", None)
            actual_hash = _sha256_json(unsigned)
            if stored_hash != actual_hash:
                raise ValueError("snapshot journal record hash mismatch")

            key = str(row.get("snapshot_key") or "")
            if not key:
                raise ValueError("snapshot journal missing snapshot_key")
            if key in records:
                raise ValueError("snapshot journal duplicate snapshot_key")
            records[key] = row
            previous = stored_hash
            sequence = expected_sequence

        self._records_by_key = records
        self._last_hash = previous
        self._sequence = sequence

    def append(self, snapshot: PostTransitionSnapshot) -> tuple[bool, dict[str, Any]]:
        key = snapshot_key(snapshot)
        payload = asdict(snapshot)
        payload_hash = _sha256_json(payload)

        existing = self._records_by_key.get(key)
        if existing is not None:
            if existing.get("snapshot_payload_sha256") != payload_hash:
                raise ValueError("conflicting immutable snapshot replay")
            return False, existing

        unsigned = {
            "type": "post_transition_snapshot_record_v0",
            "version": VERSION,
            "sequence": self._sequence + 1,
            "snapshot_key": key,
            "snapshot_payload_sha256": payload_hash,
            "previous_record_hash_sha256": self._last_hash,
            "snapshot": payload,
        }
        record = {
            **unsigned,
            "record_hash_sha256": _sha256_json(unsigned),
        }
        with self.path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(_canonical_json(record) + "\n")
            handle.flush()

        self._records_by_key[key] = record
        self._sequence += 1
        self._last_hash = str(record["record_hash_sha256"])
        return True, record

    def summary(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "path": str(self.path.resolve()),
            "record_count": self._sequence,
            "genesis_hash_sha256": GENESIS_HASH,
            "final_record_hash_sha256": self._last_hash,
            "hash_chain_valid": True,
        }


def verify_snapshot_journal(path: Path) -> dict[str, Any]:
    return ImmutableSnapshotJournalV0(Path(path)).summary()
