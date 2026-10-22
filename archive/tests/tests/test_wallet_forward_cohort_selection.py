import unittest

from src.wallet_forward_cohort_selection import (
    WalletForwardAcquisitionProfile,
    select_wallet_forward_cohort,
    with_extra_exclusion,
)


def profile(
    address: str,
    *,
    signature: str,
    active_days_7d: int,
    swaps_72h: int,
    latest_age: int,
    eligible: bool = True,
) -> WalletForwardAcquisitionProfile:
    return WalletForwardAcquisitionProfile(
        address=address,
        cutoff_at=1_000_000,
        swap_count=30,
        roundtrip_share_pct=70.0,
        complete_like_sizing_count=5,
        frequency_rate_per_day=8.0,
        frequency_bucket="active",
        latest_swap_at=1_000_000 - latest_age,
        latest_swap_age_seconds=latest_age,
        swaps_72h=swaps_72h,
        active_days_7d=active_days_7d,
        signature=signature,
        flags=(),
        eligible=eligible,
        exclusion_reasons=() if eligible else ("blocked",),
    )


class WalletForwardCohortSelectionTests(unittest.TestCase):
    def test_ineligible_profiles_are_never_selected(self):
        rows = [
            profile("A", signature="s1", active_days_7d=5, swaps_72h=20, latest_age=10),
            profile(
                "B",
                signature="s2",
                active_days_7d=7,
                swaps_72h=99,
                latest_age=1,
                eligible=False,
            ),
        ]

        selected = select_wallet_forward_cohort(rows, max_wallets=5)

        self.assertEqual([item.address for item in selected], ["A"])

    def test_selection_prefers_signature_diversity_before_fill(self):
        rows = [
            profile("A", signature="same", active_days_7d=7, swaps_72h=30, latest_age=10),
            profile("B", signature="same", active_days_7d=6, swaps_72h=25, latest_age=20),
            profile("C", signature="other", active_days_7d=4, swaps_72h=10, latest_age=30),
        ]

        selected = select_wallet_forward_cohort(rows, max_wallets=2)

        self.assertEqual([item.address for item in selected], ["A", "C"])

    def test_selection_fill_uses_pre_t0_activity_rank(self):
        rows = [
            profile("A", signature="same", active_days_7d=6, swaps_72h=20, latest_age=50),
            profile("B", signature="same", active_days_7d=6, swaps_72h=25, latest_age=60),
            profile("C", signature="other", active_days_7d=5, swaps_72h=50, latest_age=10),
        ]

        selected = select_wallet_forward_cohort(rows, max_wallets=3)

        self.assertEqual([item.address for item in selected], ["B", "C", "A"])

    def test_extra_exclusion_cannot_leave_profile_eligible(self):
        item = profile("A", signature="s1", active_days_7d=5, swaps_72h=20, latest_age=10)

        blocked = with_extra_exclusion(item, "pre_t0_sync_partial")

        self.assertFalse(blocked.eligible)
        self.assertEqual(blocked.exclusion_reasons, ("pre_t0_sync_partial",))

    def test_invalid_max_wallets_is_rejected(self):
        with self.assertRaises(ValueError):
            select_wallet_forward_cohort([], max_wallets=0)


if __name__ == "__main__":
    unittest.main()
