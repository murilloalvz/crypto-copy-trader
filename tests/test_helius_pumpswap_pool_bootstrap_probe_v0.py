import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.helius_standard_wss_shadow_v0.bootstrap_pools import (
    BATCH_SIZE,
    _chunks,
    observed_pumpswap_pools,
)


class HeliusPumpSwapPoolBootstrapProbeV0Tests(unittest.TestCase):
    def test_observed_pools_are_exact_deduplicated_and_pumpswap_only(self):
        rows = [
            {"type": "carbon_canonical_event", "status": "decoded", "event_type": "pumpswap_buy", "pool": "POOL_B"},
            {"type": "carbon_canonical_event", "status": "decoded", "event_type": "pumpswap_sell", "pool": "POOL_A"},
            {"type": "carbon_canonical_event", "status": "decoded", "event_type": "pumpswap_buy", "pool": "POOL_B"},
            {"type": "carbon_canonical_event", "status": "decoded", "event_type": "pump_trade", "pool": "NOT_A_SWAP_POOL"},
            {"type": "carbon_canonical_event", "status": "decode_failed", "event_type": "pumpswap_buy", "pool": "FAILED_POOL"},
            {"type": "carbon_decoder_footer", "input_events": 5},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "carbon.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            pools = observed_pumpswap_pools(path)
        self.assertEqual(pools, ("POOL_A", "POOL_B"))

    def test_batches_never_exceed_rpc_limit(self):
        pools = tuple(f"POOL_{index:03d}" for index in range(205))
        batches = list(_chunks(pools))
        self.assertEqual([len(batch) for batch in batches], [BATCH_SIZE, BATCH_SIZE, 5])
        self.assertEqual(tuple(item for batch in batches for item in batch), pools)


if __name__ == "__main__":
    unittest.main()
