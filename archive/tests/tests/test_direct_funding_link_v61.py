import unittest

from src.direct_funding_link_v61 import (
    FundingTransferObservationV61,
    LaunchActorReferenceV61,
    build_direct_funding_link_evidence_v61,
)
from src.multichain_market_contract_v59 import canonical_network_v59


CHAIN = canonical_network_v59("solana", "mainnet")


def _launch(*, observed_at: int = 101) -> LaunchActorReferenceV61:
    return LaunchActorReferenceV61(
        chain=CHAIN,
        token_address="TOKEN",
        deployer_wallet="DEPLOYER",
        launch_chain_time=100,
        launch_observed_at=observed_at,
        reference_key="launch:TOKEN",
    )


def _transfer(
    key: str,
    *,
    source: str,
    destination: str,
    chain_time: int,
    observed_at: int | None = None,
    asset_kind: str = "native",
    tx: str | None = None,
) -> FundingTransferObservationV61:
    return FundingTransferObservationV61(
        transfer_key=key,
        chain=CHAIN,
        from_wallet=source,
        to_wallet=destination,
        chain_time=chain_time,
        observed_at=chain_time if observed_at is None else observed_at,
        asset_kind=asset_kind,
        asset_address=None if asset_kind == "native" else "MINT",
        amount_raw="1000",
        transaction_key=tx,
    )


class DirectFundingLinkV61Tests(unittest.TestCase):
    def test_direct_native_deployer_funding_is_explicit(self):
        evidence = build_direct_funding_link_evidence_v61(
            reference=_launch(),
            participant_wallet="SNIPER",
            as_of=110,
            transfers=[
                _transfer(
                    "t1",
                    source="DEPLOYER",
                    destination="SNIPER",
                    chain_time=90,
                    observed_at=95,
                    tx="sig1",
                )
            ],
        )
        self.assertEqual(
            evidence.evidence_classification,
            "DIRECT_NATIVE_DEPLOYER_TO_PARTICIPANT_PRELAUNCH",
        )
        self.assertEqual(evidence.deployer_to_participant_count, 1)
        self.assertEqual(evidence.deployer_to_participant_native_count, 1)
        self.assertEqual(evidence.latest_deployer_to_participant_offset_seconds, -10)
        self.assertEqual(evidence.direct_link_transaction_keys, ("sig1",))

    def test_historical_prelaunch_transfer_discovered_after_as_of_is_excluded(self):
        evidence = build_direct_funding_link_evidence_v61(
            reference=_launch(),
            participant_wallet="SNIPER",
            as_of=110,
            transfers=[
                _transfer(
                    "t1",
                    source="DEPLOYER",
                    destination="SNIPER",
                    chain_time=90,
                    observed_at=111,
                )
            ],
        )
        self.assertEqual(evidence.known_prelaunch_transfer_count, 0)
        self.assertEqual(
            evidence.evidence_classification,
            "NO_CAUSALLY_KNOWN_DIRECT_PRELAUNCH_LINK",
        )
        self.assertIn(
            "prelaunch_direct_links_discovered_after_as_of_excluded",
            evidence.data_quality_flags,
        )

    def test_postlaunch_transfer_does_not_become_prelaunch_funding(self):
        evidence = build_direct_funding_link_evidence_v61(
            reference=_launch(),
            participant_wallet="SNIPER",
            as_of=120,
            transfers=[
                _transfer(
                    "t1",
                    source="DEPLOYER",
                    destination="SNIPER",
                    chain_time=105,
                    observed_at=106,
                )
            ],
        )
        self.assertEqual(evidence.known_prelaunch_transfer_count, 0)
        self.assertIn("postlaunch_direct_links_excluded", evidence.data_quality_flags)

    def test_reverse_transfer_is_not_called_deployer_funding(self):
        evidence = build_direct_funding_link_evidence_v61(
            reference=_launch(),
            participant_wallet="SNIPER",
            as_of=110,
            transfers=[
                _transfer(
                    "t1",
                    source="SNIPER",
                    destination="DEPLOYER",
                    chain_time=80,
                )
            ],
        )
        self.assertEqual(
            evidence.evidence_classification,
            "DIRECT_PARTICIPANT_TO_DEPLOYER_PRELAUNCH",
        )
        self.assertEqual(evidence.deployer_to_participant_count, 0)
        self.assertEqual(evidence.participant_to_deployer_count, 1)

    def test_token_transfer_is_distinguished_from_native_funding(self):
        evidence = build_direct_funding_link_evidence_v61(
            reference=_launch(),
            participant_wallet="SNIPER",
            as_of=110,
            transfers=[
                _transfer(
                    "t1",
                    source="DEPLOYER",
                    destination="SNIPER",
                    chain_time=80,
                    asset_kind="token",
                )
            ],
        )
        self.assertEqual(
            evidence.evidence_classification,
            "DIRECT_TOKEN_DEPLOYER_TO_PARTICIPANT_PRELAUNCH",
        )
        self.assertIn(
            "deployer_to_participant_link_is_token_not_native",
            evidence.data_quality_flags,
        )

    def test_unrelated_transfer_is_ignored(self):
        evidence = build_direct_funding_link_evidence_v61(
            reference=_launch(),
            participant_wallet="SNIPER",
            as_of=110,
            transfers=[
                _transfer("t1", source="A", destination="B", chain_time=80)
            ],
        )
        self.assertEqual(evidence.candidate_transfer_count, 0)
        self.assertEqual(evidence.known_prelaunch_transfer_count, 0)

    def test_launch_identity_must_be_known_by_as_of(self):
        with self.assertRaisesRegex(ValueError, "not known by as_of"):
            build_direct_funding_link_evidence_v61(
                reference=_launch(observed_at=120),
                participant_wallet="SNIPER",
                as_of=110,
                transfers=[],
            )

    def test_participant_cannot_equal_deployer(self):
        with self.assertRaisesRegex(ValueError, "cannot equal deployer"):
            build_direct_funding_link_evidence_v61(
                reference=_launch(),
                participant_wallet="DEPLOYER",
                as_of=110,
                transfers=[],
            )

    def test_duplicate_transfer_key_is_rejected(self):
        row = _transfer("t1", source="DEPLOYER", destination="SNIPER", chain_time=80)
        with self.assertRaisesRegex(ValueError, "duplicate transfer_key"):
            build_direct_funding_link_evidence_v61(
                reference=_launch(),
                participant_wallet="SNIPER",
                as_of=110,
                transfers=[row, row],
            )


if __name__ == "__main__":
    unittest.main()
