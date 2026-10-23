import unittest

from src.multichain_market_contract_v59 import canonical_network_v59
from src.protocol_deployment_attestation_v66 import (
    DeploymentCapabilityEvidenceV66,
    build_protocol_deployment_attestation_v66,
    capability_authoritative_for_event_v66,
    capability_authoritative_for_read_v66,
)


RH = canonical_network_v59("eip155", 4663)
FACTORY = "0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e"


class ProtocolDeploymentAttestationV66Tests(unittest.TestCase):
    def cap(self, name, kind, *, observed_at=100, ref="evidence"):
        return DeploymentCapabilityEvidenceV66(
            capability=name,
            evidence_kind=kind,
            observed_at=observed_at,
            evidence_reference=ref,
        )

    def test_capability_order_does_not_change_attestation_hash(self):
        a = self.cap("token_launched_event", "deployed_event_observed")
        b = self.cap("get_launched_token", "deployed_call_succeeded")
        first = build_protocol_deployment_attestation_v66(
            protocol_key="pons",
            generation="v2",
            chain=RH,
            deployment_address=FACTORY,
            observed_at=200,
            capabilities=[a, b],
        )
        second = build_protocol_deployment_attestation_v66(
            protocol_key="pons",
            generation="v2",
            chain=RH,
            deployment_address=FACTORY.lower(),
            observed_at=200,
            capabilities=[b, a],
        )
        self.assertEqual(first.attestation_sha256, second.attestation_sha256)
        self.assertEqual(first.deployment_address, FACTORY.lower())

    def test_source_only_is_not_authoritative_for_runtime_read(self):
        attestation = build_protocol_deployment_attestation_v66(
            protocol_key="pons",
            generation="v2",
            chain=RH,
            deployment_address=FACTORY,
            observed_at=200,
            capabilities=[self.cap("current_snipe_tax_bps", "source_only")],
        )
        self.assertFalse(
            capability_authoritative_for_read_v66(attestation, "current_snipe_tax_bps")
        )
        self.assertIn("non_authoritative_capabilities_present", attestation.data_quality_flags)

    def test_third_party_claim_is_not_authoritative_for_runtime_read(self):
        attestation = build_protocol_deployment_attestation_v66(
            protocol_key="pons",
            generation="v2",
            chain=RH,
            deployment_address=FACTORY,
            observed_at=200,
            capabilities=[self.cap("current_snipe_tax_bps", "third_party_claim")],
        )
        self.assertFalse(
            capability_authoritative_for_read_v66(attestation, "current_snipe_tax_bps")
        )

    def test_successful_deployed_call_is_authoritative_for_read_but_not_event(self):
        attestation = build_protocol_deployment_attestation_v66(
            protocol_key="pons",
            generation="v2",
            chain=RH,
            deployment_address=FACTORY,
            observed_at=200,
            capabilities=[self.cap("real_quote_reserve", "deployed_call_succeeded")],
        )
        self.assertTrue(
            capability_authoritative_for_read_v66(attestation, "real_quote_reserve")
        )
        self.assertFalse(
            capability_authoritative_for_event_v66(attestation, "real_quote_reserve")
        )

    def test_observed_deployed_event_is_authoritative_for_event_but_not_read(self):
        attestation = build_protocol_deployment_attestation_v66(
            protocol_key="pons",
            generation="v2",
            chain=RH,
            deployment_address=FACTORY,
            observed_at=200,
            capabilities=[self.cap("pool_graduated_event", "deployed_event_observed")],
        )
        self.assertTrue(
            capability_authoritative_for_event_v66(attestation, "pool_graduated_event")
        )
        self.assertFalse(
            capability_authoritative_for_read_v66(attestation, "pool_graduated_event")
        )

    def test_verified_runtime_source_match_is_authoritative_for_both(self):
        attestation = build_protocol_deployment_attestation_v66(
            protocol_key="pons",
            generation="v2",
            chain=RH,
            deployment_address=FACTORY,
            observed_at=200,
            runtime_code_hash="11" * 32,
            source_commit_sha="22" * 32,
            capabilities=[self.cap("curve_contract_semantics", "verified_runtime_source_match")],
        )
        self.assertTrue(
            capability_authoritative_for_read_v66(attestation, "curve_contract_semantics")
        )
        self.assertTrue(
            capability_authoritative_for_event_v66(attestation, "curve_contract_semantics")
        )
        self.assertNotIn("runtime_code_hash_unavailable", attestation.data_quality_flags)
        self.assertNotIn("source_commit_unpinned", attestation.data_quality_flags)

    def test_conflicting_capability_fails_closed_for_authority(self):
        attestation = build_protocol_deployment_attestation_v66(
            protocol_key="pons",
            generation="v2",
            chain=RH,
            deployment_address=FACTORY,
            observed_at=200,
            capabilities=[self.cap("opening_tax", "conflicting")],
        )
        self.assertFalse(capability_authoritative_for_read_v66(attestation, "opening_tax"))
        self.assertFalse(capability_authoritative_for_event_v66(attestation, "opening_tax"))
        self.assertIn("conflicting_capability_evidence", attestation.data_quality_flags)

    def test_capability_evidence_cannot_postdate_attestation(self):
        with self.assertRaisesRegex(ValueError, "cannot postdate"):
            build_protocol_deployment_attestation_v66(
                protocol_key="pons",
                generation="v2",
                chain=RH,
                deployment_address=FACTORY,
                observed_at=100,
                capabilities=[self.cap("x", "source_only", observed_at=101)],
            )

    def test_duplicate_capability_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate deployment capability"):
            build_protocol_deployment_attestation_v66(
                protocol_key="pons",
                generation="v2",
                chain=RH,
                deployment_address=FACTORY,
                observed_at=200,
                capabilities=[
                    self.cap("x", "source_only"),
                    self.cap("x", "third_party_claim"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
