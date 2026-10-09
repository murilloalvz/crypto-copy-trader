import unittest

import wallet_forward_experiment


class WalletForwardExperimentCommitmentTests(unittest.TestCase):
    def test_experiment_defaults_to_confirmed_and_runtime_records_it(self):
        args = wallet_forward_experiment.build_parser().parse_args(["--file", "wallets.txt"])
        self.assertEqual(args.rpc_commitment, "confirmed")
        self.assertIn("confirmed_commitment", wallet_forward_experiment._runtime_version(args.rpc_commitment))

    def test_finalized_runtime_is_distinct(self):
        confirmed = wallet_forward_experiment._runtime_version("confirmed")
        finalized = wallet_forward_experiment._runtime_version("finalized")
        self.assertNotEqual(confirmed, finalized)
        self.assertIn("finalized_commitment", finalized)


if __name__ == "__main__":
    unittest.main()
