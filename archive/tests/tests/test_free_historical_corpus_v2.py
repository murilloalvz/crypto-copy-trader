import unittest

from benchmarks.free_historical_corpus_v2.collect import Counters, FixedRateLimiter, helius_rpc_url


class FreeHistoricalCorpusV2Tests(unittest.TestCase):
    def test_rpc_url_requires_key(self):
        with self.assertRaises(ValueError):
            helius_rpc_url("   ")

    def test_rpc_url_encodes_secret(self):
        url = helius_rpc_url("abc+123/xyz")
        self.assertEqual(
            url,
            "https://mainnet.helius-rpc.com/?api-key=abc%2B123%2Fxyz",
        )

    def test_credit_estimate_counts_standard_rpc_calls(self):
        counters = Counters(signature_rpc_calls=2, transaction_rpc_calls=500)
        self.assertEqual(counters.estimated_standard_rpc_credits, 502)

    def test_rate_limiter_rejects_nonpositive_rps(self):
        with self.assertRaises(ValueError):
            FixedRateLimiter(0)


if __name__ == "__main__":
    unittest.main()
