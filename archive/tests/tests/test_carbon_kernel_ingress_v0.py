import unittest

from benchmarks.carbon_kernel_ingress_v0.replay import (
    PUMP_PROGRAM_ID,
    TRADE_EVENT_DISCRIMINATOR,
    carbon_input,
    synthetic_pump_trade_payload,
)


class CarbonKernelIngressV0Tests(unittest.TestCase):
    def test_synthetic_pump_trade_payload_uses_exact_discriminator(self):
        payload = synthetic_pump_trade_payload(5)
        self.assertGreater(len(payload), 8)
        self.assertEqual(payload[:8], TRADE_EVENT_DISCRIMINATOR)

    def test_carbon_input_uses_pump_trade_contract(self):
        row = carbon_input(9)
        self.assertEqual(row["type"], "carbon_decoder_input")
        self.assertEqual(row["event_type"], "pump_trade")
        self.assertEqual(row["program_id"], PUMP_PROGRAM_ID)
        self.assertTrue(row["event_key"].endswith(":pump_trade"))
        self.assertTrue(row["payload_base64"])


if __name__ == "__main__":
    unittest.main()
