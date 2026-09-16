import copy
import hashlib
import json
from pathlib import Path
import unittest

from src.launch_burst_momentum_v0 import (
    EXPECTED_POLICY_HASH,
    load_momentum_policy_v0,
    validate_momentum_policy_v0,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks" / "launch_burst_momentum_v0" / "momentum_policy_v0.frozen.json"


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class LaunchBurstMomentumV0PolicyFreezeTests(unittest.TestCase):
    def test_original_policy_is_exactly_pinned(self):
        policy = load_momentum_policy_v0(POLICY)
        self.assertEqual(policy["policy_hash_sha256"], EXPECTED_POLICY_HASH)

    def test_rehashing_a_changed_threshold_does_not_create_a_new_v0(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        mutated = copy.deepcopy(policy)
        mutated["primary_selector"]["predicates"][1]["value"] = 1.5
        shadow = {k: v for k, v in mutated.items() if k != "policy_hash_sha256"}
        mutated["policy_hash_sha256"] = hashlib.sha256(canonical_json(shadow).encode("utf-8")).hexdigest()
        self.assertNotEqual(mutated["policy_hash_sha256"], EXPECTED_POLICY_HASH)
        with self.assertRaises(ValueError):
            validate_momentum_policy_v0(mutated)


if __name__ == "__main__":
    unittest.main()
