import unittest

from benchmarks.launch_burst_live_capture_v1.run import _classification_gates


class _State:
    chunk_errors = []
    semantic_errors = []
    persistence_errors = []
    research_errors = []
    lifecycle_events_ingested = 3
    market_trade_adapted_events = 9


class LaunchBurstLiveCaptureV1Tests(unittest.TestCase):
    def _acquisition(self):
        return {
            "valid_operational_shadow": True,
            "stop_reason": "duration_elapsed",
            "chunk_count": 2,
            "chunk_max_bytes": 32 * 1024 * 1024,
            "counters": {
                "transport_errors": 0,
                "reconnects": 0,
                "rpc_errors": 0,
                "write_errors": 0,
            },
        }

    def test_clean_rotating_capture_passes(self):
        gates = _classification_gates(
            acquisition=self._acquisition(),
            state=_State(),
            chunk_reports=[{"status": "PROCESSED"}, {"status": "NO_TARGET_EVENTS"}],
        )
        self.assertTrue(all(gates.values()))

    def test_missing_chunk_fails_closed(self):
        gates = _classification_gates(
            acquisition=self._acquisition(),
            state=_State(),
            chunk_reports=[{"status": "PROCESSED"}],
        )
        self.assertFalse(gates["all_chunks_consumed"])

    def test_failed_chunk_fails_closed(self):
        gates = _classification_gates(
            acquisition=self._acquisition(),
            state=_State(),
            chunk_reports=[{"status": "PROCESSED"}, {"status": "FAILED"}],
        )
        self.assertFalse(gates["all_chunks_processed"])

    def test_transport_gap_still_fails_capture(self):
        acquisition = self._acquisition()
        acquisition["counters"]["transport_errors"] = 1
        acquisition["counters"]["reconnects"] = 1
        gates = _classification_gates(
            acquisition=acquisition,
            state=_State(),
            chunk_reports=[{"status": "PROCESSED"}, {"status": "PROCESSED"}],
        )
        self.assertFalse(gates["no_transport_errors"])
        self.assertFalse(gates["no_reconnects"])


if __name__ == "__main__":
    unittest.main()
