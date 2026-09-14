import unittest

from benchmarks.robinhood_launch_burst_v0.direct_quote_state import (
    PASS_NO_SNIPE,
    PASS_SNIPE,
    read_curve_quote_state_v0,
)
from src.pons_v2_curve_quote_v0 import (
    SNIPE_MODE_LIVE_VIEW,
    SNIPE_MODE_PROVEN_ABSENT,
)


def word(value):
    return f"{int(value):064x}"


class FakeQuoteStateRpc:
    def __init__(self, *, reorg=False):
        self.reorg = reorg
        self.block_reads = 0
        self.calls = []
        self.selectors = {
            "feeBps()": "0x11111111",
            "creatorTaxBps()": "0x22222222",
            "getReserves()": "0x33333333",
            "sellableTokens()": "0x44444444",
            "readyToGraduate()": "0x55555555",
            "currentSnipeTaxBps(address)": "0x66666666",
            "graduated()": "0x77777777",
        }

    def block_number(self):
        return 1234

    def sha3_text(self, text):
        return self.selectors[text] + "00" * 28

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "eth_getBlockByNumber":
            self.block_reads += 1
            suffix = "bb" if self.reorg and self.block_reads > 1 else "aa"
            return {
                "number": "0x4d2",
                "hash": "0x" + suffix * 32,
                "timestamp": "0x64",
            }
        if method == "eth_getCode":
            return "0x60006000"
        if method == "eth_call":
            data = params[0]["data"]
            selector = data[:10]
            if selector == "0x11111111":
                return "0x" + word(100)
            if selector == "0x22222222":
                return "0x" + word(50)
            if selector == "0x33333333":
                return "0x" + word(1_000_000) + word(2_000_000)
            if selector == "0x44444444":
                return "0x" + word(1_500_000)
            if selector == "0x55555555":
                return "0x" + word(0)
            if selector == "0x77777777":
                return "0x" + word(0)
            if selector == "0x66666666":
                return "0x" + word(5_000)
            raise AssertionError(data)
        raise AssertionError(method)


def capabilities(classification):
    suffix = "snipe_view" if classification == PASS_SNIPE else "base_curve_no_snipe_view"
    return {
        "classification": classification,
        "generation_key": f"pons_v2:0x{'aa' * 20}:{suffix}",
        "factory": "0x" + "aa" * 20,
    }


class PonsV2CurveQuoteStateV0Tests(unittest.TestCase):
    def test_snipe_generation_reads_every_view_at_one_pinned_block(self):
        rpc = FakeQuoteStateRpc()
        state, evidence = read_curve_quote_state_v0(
            rpc,
            curve="0x" + "11" * 20,
            recipient="0x" + "22" * 20,
            capability_report=capabilities(PASS_SNIPE),
        )
        self.assertEqual(state.quote_reserve_raw, 1_000_000)
        self.assertEqual(state.token_reserve_raw, 2_000_000)
        self.assertEqual(state.sellable_tokens_raw, 1_500_000)
        self.assertEqual(state.fee_bps, 100)
        self.assertEqual(state.creator_tax_bps, 50)
        self.assertEqual(state.current_snipe_tax_bps, 5_000)
        self.assertEqual(state.snipe_mode, SNIPE_MODE_LIVE_VIEW)
        self.assertFalse(state.ready_to_graduate)
        self.assertFalse(state.graduated)
        self.assertEqual(evidence["block"]["number"], 1234)
        self.assertEqual(evidence["block"]["hash"], "0x" + "aa" * 32)
        self.assertTrue(evidence["reorg_guard_passed"])
        self.assertFalse(evidence["fill_claimed"])

        eth_calls = [params for method, params in rpc.calls if method == "eth_call"]
        self.assertTrue(eth_calls)
        self.assertTrue(all(params[1] == "0x4d2" for params in eth_calls))
        self.assertTrue(any(params[0]["data"].startswith("0x66666666") for params in eth_calls))

    def test_proven_no_snipe_generation_does_not_invent_or_query_snipe_state(self):
        rpc = FakeQuoteStateRpc()
        state, evidence = read_curve_quote_state_v0(
            rpc,
            curve="0x" + "11" * 20,
            recipient="0x" + "22" * 20,
            capability_report=capabilities(PASS_NO_SNIPE),
        )
        self.assertEqual(state.snipe_mode, SNIPE_MODE_PROVEN_ABSENT)
        self.assertEqual(state.current_snipe_tax_bps, 0)
        self.assertNotIn("currentSnipeTaxBps", evidence["raw_calls"])
        eth_calls = [params for method, params in rpc.calls if method == "eth_call"]
        self.assertFalse(any(params[0]["data"].startswith("0x66666666") for params in eth_calls))

    def test_non_pass_capability_report_is_rejected(self):
        rpc = FakeQuoteStateRpc()
        with self.assertRaises(ValueError):
            read_curve_quote_state_v0(
                rpc,
                curve="0x" + "11" * 20,
                recipient="0x" + "22" * 20,
                capability_report={
                    "classification": "FAIL_PONS_PROTOCOL_CAPABILITIES_V0_CORE_VIEW_MISSING",
                    "generation_key": "bad",
                    "factory": "0x" + "aa" * 20,
                },
            )

    def test_reorg_during_pinned_read_is_rejected(self):
        rpc = FakeQuoteStateRpc(reorg=True)
        with self.assertRaisesRegex(RuntimeError, "block hash changed"):
            read_curve_quote_state_v0(
                rpc,
                curve="0x" + "11" * 20,
                recipient="0x" + "22" * 20,
                capability_report=capabilities(PASS_SNIPE),
            )


if __name__ == "__main__":
    unittest.main()
