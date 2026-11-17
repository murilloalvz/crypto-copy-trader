import unittest

from benchmarks.launch_burst_live_capture_v2.run import (
    _BurstNoResearchKernel,
    _classification_gates,
)


class _InnerKernel:
    def __init__(self):
        self.lifecycle = []
        self.trades = []

    def ingest_lifecycle(self, observation):
        self.lifecycle.append(observation)
        return "lifecycle-ok"

    def ingest_trade(self, observation):
        self.trades.append(observation)
        return object()

    def stats(self):
        return object()


class _State:
    chunk_errors = []
    semantic_errors = []
    persistence_errors = []
    research_errors = []
    research_handoffs_processed = 0
    first_trigger_episodes = 0
    signal_boundaries_sealed = 0
    lifecycle_events_ingested = 3
    market_trade_adapted_events = 9


class LaunchBurstLiveCaptureV2Tests(unittest.TestCase):
    def test_no_research_kernel_discards_trigger_but_preserves_ingest(self):
        kernel = _BurstNoResearchKernel()
        inner = _InnerKernel()
        kernel._inner = inner

        self.assertEqual(kernel.ingest_lifecycle("life"), "lifecycle-ok")
        self.assertIsNone(kernel.ingest_trade("trade"))
        self.assertEqual(inner.lifecycle, ["life"])
        self.assertEqual(inner.trades, ["trade"])

    def test_clean_signal_only_capture_gates_pass(self):
        acquisition = {
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
        gates = _classification_gates(
            acquisition=acquisition,
            state=_State(),
            chunk_reports=[{"status": "PROCESSED"}, {"status": "PROCESSED"}],
        )
        self.assertTrue(all(gates.values()))

    def test_any_research_plane_activity_fails_isolation_gate(self):
        state = _State()
        state.research_handoffs_processed = 1
        acquisition = {
            "valid_operational_shadow": True,
            "stop_reason": "duration_elapsed",
            "chunk_count": 1,
            "chunk_max_bytes": 32 * 1024 * 1024,
            "counters": {
                "transport_errors": 0,
                "reconnects": 0,
                "rpc_errors": 0,
                "write_errors": 0,
            },
        }
        gates = _classification_gates(
            acquisition=acquisition,
            state=state,
            chunk_reports=[{"status": "PROCESSED"}],
        )
        self.assertFalse(gates["research_plane_disabled_by_design"])


if __name__ == "__main__":
    unittest.main()
