import unittest

from benchmarks.launch_burst_live_capture_v0.run import _classification_gates


class _State:
    chunk_errors = []
    semantic_errors = []
    persistence_errors = []
    research_errors = []
    lifecycle_events_ingested = 3
    market_trade_adapted_events = 9


class LaunchBurstLiveCaptureV0Tests(unittest.TestCase):
    def test_gate_passes_only_for_clean_duration_capture_with_causal_data(self):
        footer = {
            "valid_operational_shadow": True,
            "stop_reason": "duration_elapsed",
            "counters": {
                "transport_errors": 0,
                "reconnects": 0,
                "rpc_errors": 0,
                "write_errors": 0,
            },
        }
        gates = _classification_gates(
            footer=footer,
            state=_State(),
            chunk_report={"status": "PROCESSED"},
        )
        self.assertTrue(all(gates.values()))

    def test_transport_gap_fails_capture(self):
        footer = {
            "valid_operational_shadow": True,
            "stop_reason": "duration_elapsed",
            "counters": {
                "transport_errors": 1,
                "reconnects": 1,
                "rpc_errors": 0,
                "write_errors": 0,
            },
        }
        gates = _classification_gates(
            footer=footer,
            state=_State(),
            chunk_report={"status": "PROCESSED"},
        )
        self.assertFalse(gates["no_transport_errors"])
        self.assertFalse(gates["no_reconnects"])

    def test_empty_causal_evidence_fails_capture(self):
        state = _State()
        state.lifecycle_events_ingested = 0
        state.market_trade_adapted_events = 0
        footer = {
            "valid_operational_shadow": True,
            "stop_reason": "duration_elapsed",
            "counters": {
                "transport_errors": 0,
                "reconnects": 0,
                "rpc_errors": 0,
                "write_errors": 0,
            },
        }
        gates = _classification_gates(
            footer=footer,
            state=state,
            chunk_report={"status": "NO_TARGET_EVENTS"},
        )
        self.assertFalse(gates["causal_lifecycle_seen"])
        self.assertFalse(gates["causal_trade_seen"])


if __name__ == "__main__":
    unittest.main()
