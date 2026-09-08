import unittest

from src.multichain_market_contract_v59 import canonical_network_v59
from src.pons_launch_quality_evidence_v67 import (
    PonsDeployerHistoryEvidenceV67,
    PonsEarlyActivityEvidenceV67,
    PonsLaunchStaticEvidenceV67,
    PonsOpeningTaxEvidenceV67,
    PonsPriorFingerprintEvidenceV67,
    build_pons_launch_quality_evidence_v67,
)
from src.protocol_deployment_attestation_v66 import (
    DeploymentCapabilityEvidenceV66,
    build_protocol_deployment_attestation_v66,
)


TOKEN = "0x1111111111111111111111111111111111111111"
CURVE = "0x2222222222222222222222222222222222222222"
DEPLOYER = "0x3333333333333333333333333333333333333333"
RECIPIENT = "0x4444444444444444444444444444444444444444"
FACTORY = "0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e"
RH = canonical_network_v59("eip155", 4663)


class PonsLaunchQualityEvidenceV67Tests(unittest.TestCase):
    def deployment(self, *, tax_kind=None, observed_at=90):
        caps = []
        if tax_kind is not None:
            caps.append(
                DeploymentCapabilityEvidenceV66(
                    capability="current_snipe_tax_bps",
                    evidence_kind=tax_kind,
                    observed_at=observed_at,
                    evidence_reference="attestation-evidence",
                )
            )
        return build_protocol_deployment_attestation_v66(
            protocol_key="pons",
            generation="v2",
            chain=RH,
            deployment_address=FACTORY,
            observed_at=observed_at,
            capabilities=caps,
        )

    def static(self, **overrides):
        values = dict(
            token_address=TOKEN,
            curve_address=CURVE,
            deployer_address=DEPLOYER,
            launch_block_number=100,
            launch_chain_time=1_000,
            launch_observed_at=1_001,
            evidence_observed_at=1_003,
            dev_quote_spent_raw=500,
            dev_tokens_received_raw=50,
            launch_supply_raw=1_000,
            creator_tax_bps=200,
            creator_fee_recipient=DEPLOYER,
            declared_exemption_count=2,
            social_x_present=True,
            social_website_present=True,
            social_telegram_present=False,
            description_length=80,
            evidence_reference="static-a",
        )
        values.update(overrides)
        return PonsLaunchStaticEvidenceV67(**values)

    def test_builds_raw_features_without_weighted_score(self):
        result = build_pons_launch_quality_evidence_v67(
            as_of=1_100,
            deployment=self.deployment(),
            static=self.static(),
            deployer_history=PonsDeployerHistoryEvidenceV67(
                deployer_address=DEPLOYER,
                before_block_number=99,
                history_observed_at=1_010,
                prior_launch_count=10,
                prior_graduated_count=3,
                history_complete=True,
                evidence_reference="deployer-history",
            ),
            fingerprint_history=PonsPriorFingerprintEvidenceV67(
                fingerprint_key="fingerprint-a",
                before_chain_time=999,
                history_observed_at=1_010,
                window_seconds=1_800,
                prior_matching_launch_count=2,
                distinct_prior_deployer_count=2,
                evidence_complete=True,
                evidence_reference="fingerprint-history",
            ),
            early_activity=PonsEarlyActivityEvidenceV67(
                token_address=TOKEN,
                as_of=1_050,
                window_seconds=30,
                event_count=8,
                buy_count=6,
                sell_count=2,
                wallet_identity_coverage_pct=100.0,
                unique_buyer_count=5,
                unique_seller_count=2,
                repeated_wallet_event_share_pct=25.0,
            ),
        )
        self.assertEqual(result.dev_buy_token_share_pct, 5.0)
        self.assertEqual(result.creator_tax_bps, 200)
        self.assertTrue(result.creator_fee_recipient_is_deployer)
        self.assertEqual(result.social_channel_count, 2)
        self.assertEqual(result.deployer_prior_graduation_share_pct, 30.0)
        self.assertEqual(result.fingerprint_prior_matching_launch_count, 2)
        self.assertEqual(result.early_unique_buyer_count, 5)
        self.assertFalse(hasattr(result, "score"))
        self.assertFalse(hasattr(result, "verdict"))

    def test_static_bundle_known_after_as_of_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "static launch bundle"):
            build_pons_launch_quality_evidence_v67(
                as_of=1_100,
                deployment=self.deployment(),
                static=self.static(evidence_observed_at=1_101),
            )

    def test_deployer_history_must_stop_strictly_before_launch_block(self):
        with self.assertRaisesRegex(ValueError, "strictly before launch block"):
            build_pons_launch_quality_evidence_v67(
                as_of=1_100,
                deployment=self.deployment(),
                static=self.static(),
                deployer_history=PonsDeployerHistoryEvidenceV67(
                    deployer_address=DEPLOYER,
                    before_block_number=100,
                    history_observed_at=1_010,
                    prior_launch_count=1,
                    prior_graduated_count=0,
                    history_complete=True,
                    evidence_reference="history",
                ),
            )

    def test_fingerprint_history_discovered_late_stays_missing(self):
        result = build_pons_launch_quality_evidence_v67(
            as_of=1_100,
            deployment=self.deployment(),
            static=self.static(),
            fingerprint_history=PonsPriorFingerprintEvidenceV67(
                fingerprint_key="fp",
                before_chain_time=999,
                history_observed_at=1_200,
                window_seconds=1_800,
                prior_matching_launch_count=9,
                distinct_prior_deployer_count=9,
                evidence_complete=True,
                evidence_reference="late-history",
            ),
        )
        self.assertIsNone(result.fingerprint_prior_matching_launch_count)
        self.assertIn(
            "fingerprint_history_incomplete_or_not_known_by_as_of",
            result.data_quality_flags,
        )

    def test_partial_wallet_coverage_does_not_publish_unique_buyer_metrics(self):
        result = build_pons_launch_quality_evidence_v67(
            as_of=1_100,
            deployment=self.deployment(),
            static=self.static(),
            early_activity=PonsEarlyActivityEvidenceV67(
                token_address=TOKEN,
                as_of=1_050,
                window_seconds=30,
                event_count=10,
                buy_count=8,
                sell_count=2,
                wallet_identity_coverage_pct=90.0,
                unique_buyer_count=7,
                unique_seller_count=2,
                repeated_wallet_event_share_pct=10.0,
            ),
        )
        self.assertEqual(result.early_event_count, 10)
        self.assertIsNone(result.early_unique_buyer_count)
        self.assertIsNone(result.early_repeated_wallet_event_share_pct)
        self.assertIn("early_wallet_identity_coverage_incomplete", result.data_quality_flags)

    def test_source_only_opening_tax_is_not_promoted_to_evidence(self):
        result = build_pons_launch_quality_evidence_v67(
            as_of=1_100,
            deployment=self.deployment(tax_kind="source_only"),
            static=self.static(),
            opening_tax=PonsOpeningTaxEvidenceV67(
                token_address=TOKEN,
                recipient_address=RECIPIENT,
                opening_tax_bps=300,
                chain_time=1_050,
                observed_at=1_051,
                capability_name="current_snipe_tax_bps",
                evidence_reference="source-only-read",
            ),
        )
        self.assertIsNone(result.current_opening_tax_bps)
        self.assertIsNone(result.opening_tax_recipient_address)
        self.assertIn("opening_tax_capability_not_authoritative", result.data_quality_flags)

    def test_deployed_call_opening_tax_is_bound_to_recipient(self):
        result = build_pons_launch_quality_evidence_v67(
            as_of=1_100,
            deployment=self.deployment(tax_kind="deployed_call_succeeded"),
            static=self.static(),
            opening_tax=PonsOpeningTaxEvidenceV67(
                token_address=TOKEN,
                recipient_address=RECIPIENT,
                opening_tax_bps=300,
                chain_time=1_050,
                observed_at=1_051,
                capability_name="current_snipe_tax_bps",
                evidence_reference="rpc-read",
            ),
        )
        self.assertEqual(result.current_opening_tax_bps, 300)
        self.assertEqual(result.opening_tax_recipient_address, RECIPIENT)

    def test_provenance_change_changes_evidence_hash_even_when_values_match(self):
        first = build_pons_launch_quality_evidence_v67(
            as_of=1_100,
            deployment=self.deployment(),
            static=self.static(evidence_reference="source-a"),
        )
        second = build_pons_launch_quality_evidence_v67(
            as_of=1_100,
            deployment=self.deployment(),
            static=self.static(evidence_reference="source-b"),
        )
        self.assertNotEqual(first.evidence_sha256, second.evidence_sha256)

    def test_wrong_chain_deployment_attestation_is_rejected(self):
        wrong = build_protocol_deployment_attestation_v66(
            protocol_key="pons",
            generation="v2",
            chain=canonical_network_v59("eip155", 8453),
            deployment_address=FACTORY,
            observed_at=90,
            capabilities=[],
        )
        with self.assertRaisesRegex(ValueError, "Robinhood Chain"):
            build_pons_launch_quality_evidence_v67(
                as_of=1_100,
                deployment=wrong,
                static=self.static(),
            )


if __name__ == "__main__":
    unittest.main()
