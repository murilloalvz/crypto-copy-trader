import unittest

from src.multichain_market_contract_v59 import canonical_network_v59
from src.wallet_cohort_manifest_v65 import (
    WalletCohortEvidenceMemberV65,
    build_wallet_cohort_manifest_v65,
    manifest_is_registered_before_v65,
    manifest_to_v60_members_v65,
)


SOL = canonical_network_v59("solana", "mainnet")
RH = canonical_network_v59("eip155", 4663)


class WalletCohortManifestV65Tests(unittest.TestCase):
    def member(self, wallet, *, chain=SOL, signature="sig", version="v1", as_of=100):
        return WalletCohortEvidenceMemberV65(
            chain=chain,
            wallet_address=wallet,
            strategy_signature=signature,
            evidence_version=version,
            evidence_as_of=as_of,
        )

    def test_member_order_does_not_change_manifest_hash(self):
        a = self.member("wallet-a")
        b = self.member("wallet-b", as_of=101)
        first = build_wallet_cohort_manifest_v65(
            cohort_key="research", registered_at=200, members=[a, b]
        )
        second = build_wallet_cohort_manifest_v65(
            cohort_key="research", registered_at=200, members=[b, a]
        )
        self.assertEqual(first.manifest_sha256, second.manifest_sha256)
        self.assertEqual(first.members, second.members)

    def test_strategy_signature_change_changes_manifest_hash(self):
        first = build_wallet_cohort_manifest_v65(
            cohort_key="research",
            registered_at=200,
            members=[self.member("wallet-a", signature="hft")],
        )
        second = build_wallet_cohort_manifest_v65(
            cohort_key="research",
            registered_at=200,
            members=[self.member("wallet-a", signature="convex")],
        )
        self.assertNotEqual(first.manifest_sha256, second.manifest_sha256)

    def test_member_evidence_must_predate_manifest_registration(self):
        with self.assertRaisesRegex(ValueError, "strictly before"):
            build_wallet_cohort_manifest_v65(
                cohort_key="research",
                registered_at=200,
                members=[self.member("wallet-a", as_of=200)],
            )

    def test_evm_wallets_are_canonicalized_lowercase(self):
        manifest = build_wallet_cohort_manifest_v65(
            cohort_key="rh",
            registered_at=200,
            members=[
                self.member(
                    "0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD",
                    chain=RH,
                )
            ],
        )
        self.assertEqual(
            manifest.members[0].wallet_address,
            "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
        )

    def test_same_text_address_on_different_chains_is_not_duplicate(self):
        # Solana validation preserves non-empty opaque addresses; EVM is typed separately.
        evm = "0x1111111111111111111111111111111111111111"
        manifest = build_wallet_cohort_manifest_v65(
            cohort_key="multi",
            registered_at=200,
            members=[
                self.member(evm, chain=SOL),
                self.member(evm, chain=RH),
            ],
        )
        self.assertEqual(manifest.member_count, 2)

    def test_duplicate_same_chain_wallet_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate wallet identity"):
            build_wallet_cohort_manifest_v65(
                cohort_key="research",
                registered_at=200,
                members=[self.member("wallet-a"), self.member("wallet-a", as_of=101)],
            )

    def test_bridge_to_v60_uses_manifest_registration_as_frozen_at(self):
        manifest = build_wallet_cohort_manifest_v65(
            cohort_key="research",
            registered_at=200,
            members=[
                self.member("wallet-a", chain=SOL, signature="hft", version="lab-v1"),
                self.member(
                    "0x1111111111111111111111111111111111111111",
                    chain=RH,
                    signature="evm-style",
                    version="lab-v2",
                ),
            ],
        )
        rows = manifest_to_v60_members_v65(
            manifest,
            chain_namespace="solana",
            chain_reference="mainnet",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].wallet_address, "wallet-a")
        self.assertEqual(rows[0].frozen_at, 200)
        self.assertEqual(rows[0].cohort_key, "research")
        self.assertEqual(rows[0].strategy_signature, "hft")
        self.assertEqual(rows[0].evidence_version, "lab-v1")

    def test_manifest_temporal_gate_is_strict(self):
        manifest = build_wallet_cohort_manifest_v65(
            cohort_key="research",
            registered_at=200,
            members=[self.member("wallet-a")],
        )
        self.assertFalse(manifest_is_registered_before_v65(manifest, episode_as_of=200))
        self.assertTrue(manifest_is_registered_before_v65(manifest, episode_as_of=201))


if __name__ == "__main__":
    unittest.main()
