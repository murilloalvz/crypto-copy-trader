from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import time
from typing import Any

from benchmarks.helius_standard_wss_shadow_v0 import TRACE_VERSION
from benchmarks.helius_standard_wss_shadow_v0.collect import (
    COVERAGE_CLASSIFICATION,
    SOURCE_PROVIDER,
    Counters,
    trace_header,
)
from benchmarks.market_first_live_discovery_v0 import LIVE_DISCOVERY_VERSION


DEFAULT_CHUNK_MAX_BYTES = 32 * 1024 * 1024


class RotatingTraceHandleV0:
    """File-like JSONL sink that rotates only between complete WSS trace rows.

    Each finalized chunk has exactly one ordinary Helius shadow header/footer, so the
    frozen reducer can consume chunks independently. Rotation never edits a notification.
    """

    def __init__(
        self,
        *,
        raw_dir: Path,
        finalized_queue: asyncio.Queue[Path | None],
        active_event: asyncio.Event,
        counters: Counters,
        duration_seconds: float,
        max_bytes: int = DEFAULT_CHUNK_MAX_BYTES,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.finalized_queue = finalized_queue
        self.active_event = active_event
        self.counters = counters
        self.duration_seconds = float(duration_seconds)
        self.max_bytes = int(max_bytes)
        self._index = 0
        self._handle = None
        self._path: Path | None = None
        self._bytes = 0
        self._payload_rows = 0
        self._closed = False
        self._open_chunk()

    @property
    def chunk_count(self) -> int:
        return self._index

    def _raw_line(self, row: dict[str, Any]) -> str:
        return json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"

    def _direct_write(self, text: str) -> None:
        if self._handle is None:
            raise RuntimeError("trace chunk is not open")
        self._handle.write(text)
        self._bytes += len(text.encode("utf-8"))

    def _open_chunk(self) -> None:
        self._index += 1
        self._path = self.raw_dir / f"chunk-{self._index:06d}.jsonl"
        self._handle = self._path.open(
            "w", encoding="utf-8", newline="\n", buffering=1024 * 1024
        )
        self._bytes = 0
        self._payload_rows = 0
        header = trace_header(
            duration_seconds=self.duration_seconds,
            max_log_notifications=0,
            started_wall_ns=time.time_ns(),
        )
        header.update(
            {
                "live_discovery_version": LIVE_DISCOVERY_VERSION,
                "trace_chunk_index": self._index,
                "rotating_trace": True,
            }
        )
        self._direct_write(self._raw_line(header))
        self._handle.flush()

    def _footer(self, *, stop_reason: str) -> dict[str, Any]:
        return {
            "type": "trace_footer",
            "version": TRACE_VERSION,
            "source_provider": SOURCE_PROVIDER,
            "coverage_classification": COVERAGE_CLASSIFICATION,
            "chain_complete_coverage_claimed": False,
            "valid_chain_complete_coverage": False,
            "valid_operational_shadow": self.counters.sessions_activated > 0,
            "stop_reason": stop_reason,
            "trace_chunk_index": self._index,
            "live_discovery_version": LIVE_DISCOVERY_VERSION,
            "payload_rows": self._payload_rows,
            "counters_snapshot": asdict(self.counters),
        }

    def _finalize_chunk(self, *, stop_reason: str, open_next: bool) -> None:
        if self._handle is None or self._path is None:
            return
        self._direct_write(self._raw_line(self._footer(stop_reason=stop_reason)))
        self._handle.flush()
        self._handle.close()
        finalized = self._path
        self._handle = None
        self._path = None
        self.finalized_queue.put_nowait(finalized)
        if open_next:
            self._open_chunk()

    def write(self, text: str) -> int:
        if self._closed:
            raise ValueError("I/O operation on closed rotating trace")
        if not isinstance(text, str):
            raise TypeError("rotating trace accepts text only")
        encoded_bytes = len(text.encode("utf-8"))
        if self._payload_rows > 0 and self._bytes + encoded_bytes > self.max_bytes:
            self._finalize_chunk(stop_reason="chunk_rotation", open_next=True)

        if '"type":"transport_session_active"' in text or '"type": "transport_session_active"' in text:
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                row = None
            if isinstance(row, dict) and row.get("type") == "transport_session_active":
                self.active_event.set()

        self._direct_write(text)
        self._payload_rows += 1
        return len(text)

    def flush(self) -> None:
        if self._handle is not None:
            self._handle.flush()

    def close(self, *, stop_reason: str) -> None:
        if self._closed:
            return
        self._closed = True
        self._finalize_chunk(stop_reason=stop_reason, open_next=False)
        self.finalized_queue.put_nowait(None)
