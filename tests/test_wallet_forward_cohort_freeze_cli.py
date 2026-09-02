import unittest

from src.wallet_forward_cohort_selection import PROTOCOL_VERSION
from wallet_forward_cohort_freeze import build_parser


class WalletForwardCohortFreezeCliTests(unittest.TestCase):
    def test_protocol_version_defaults_to_v1(self):
        args = build_parser().parse_args(["--file", "wallets.txt"])
        self.assertEqual(args.protocol_version, PROTOCOL_VERSION)

    def test_protocol_version_can_be_frozen_explicitly(self):
        args = build_parser().parse_args(
            [
                "--protocol-version",
                "wallet_forward_acquisition_v2",
                "--file",
                "wallets.txt",
            ]
        )
        self.assertEqual(args.protocol_version, "wallet_forward_acquisition_v2")


if __name__ == "__main__":
    unittest.main()
