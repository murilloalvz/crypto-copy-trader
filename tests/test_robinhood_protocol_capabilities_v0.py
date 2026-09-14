import unittest

from benchmarks.robinhood_launch_burst_v0.protocol_capabilities import probe_protocol_capabilities_v0


class FakeCapabilityRpc:
    def __init__(self, *, snipe_supported=True, core_supported=True):
        self.snipe_supported = snipe_supported
        self.core_supported = core_supported

    def block_number(self):
        return 1000

    def sha3_text(self, text):
        mapping = {
            "feeBps()": "0x11111111" + "00" * 28,
            "creatorTaxBps()": "0x22222222" + "00" * 28,
            "getReserves()": "0x33333333" + "00" * 28,
            "sellableTokens()": "0x44444444" + "00" * 28,
            "readyToGraduate()": "0x55555555" + "00" * 28,
            "currentSnipeTaxBps(address)": "0x66666666" + "00" * 28,
        }
        return mapping[text]

    def call(self, method, params):
        if method == "eth_getLogs":
            return [{
                "blockNumber": "0x3e8",
                "transactionIndex": "0x0",
                "logIndex": "0x1",
                "transactionHash": "0xtx",
                "topics": [
                    "0xtopic0",
                    "0x" + "00" * 12 + "11" * 20,
                    "0x" + "00" * 12 + "22" * 20,
                    "0x" + "00" * 12 + "33" * 20,
                ],
            }]
        if method == "eth_call":
            data = params[0]["data"]
            if data.startswith("0x66666666") and not self.snipe_supported:
                raise RuntimeError("execution reverted")
            if data[:10] in {"0x11111111", "0x22222222", "0x33333333", "0x44444444"} and not self.core_supported:
                raise RuntimeError("missing core view")
            return "0x" + "00" * 32
        raise AssertionError(method)


class RobinhoodProtocolCapabilitiesV0Tests(unittest.TestCase):
    def test_snipe_view_generation_is_explicit(self):
        result = probe_protocol_capabilities_v0(
            FakeCapabilityRpc(snipe_supported=True),
            factory="0x" + "aa" * 20,
            token_launched_topic0="0xtopic0",
            lookback_blocks=100,
        )
        self.assertEqual(result["classification"], "PASS_PONS_PROTOCOL_CAPABILITIES_V0_SNIPE_VIEW")
        self.assertTrue(result["capabilities"]["currentSnipeTaxBps"]["supported"])
        self.assertIn("snipe_view", result["generation_key"])

    def test_base_curve_without_snipe_view_remains_valid_separate_generation(self):
        result = probe_protocol_capabilities_v0(
            FakeCapabilityRpc(snipe_supported=False),
            factory="0x" + "aa" * 20,
            token_launched_topic0="0xtopic0",
            lookback_blocks=100,
        )
        self.assertEqual(
            result["classification"],
            "PASS_PONS_PROTOCOL_CAPABILITIES_V0_BASE_CURVE_NO_SNIPE_VIEW",
        )
        self.assertFalse(result["capabilities"]["currentSnipeTaxBps"]["supported"])

    def test_missing_core_curve_views_fail(self):
        result = probe_protocol_capabilities_v0(
            FakeCapabilityRpc(core_supported=False),
            factory="0x" + "aa" * 20,
            token_launched_topic0="0xtopic0",
            lookback_blocks=100,
        )
        self.assertEqual(
            result["classification"],
            "FAIL_PONS_PROTOCOL_CAPABILITIES_V0_CORE_VIEW_MISSING",
        )


if __name__ == "__main__":
    unittest.main()
