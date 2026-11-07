from collections import Counter
from collections.abc import Callable

from src.discovery.birdeye import BirdeyeClient, BirdeyeError
from src.discovery.models import CandidateInput, DiscoveryReport
from src.discovery.ranking import (
    CandidatePolicy,
    filter_30d,
    filter_recent,
    prefilter_leaderboard,
    rank_candidates,
)

ProgressCallback = Callable[[str, int, int, str], None]


class WalletDiscoveryService:
    """Orchestrate discovery without writing to the tracker or its SQLite database."""

    def __init__(
        self,
        client: BirdeyeClient | None = None,
        policy: CandidatePolicy | None = None,
        progress: ProgressCallback | None = None,
    ):
        self.client = client or BirdeyeClient()
        self.policy = policy or CandidatePolicy()
        self.progress = progress

    def _notify(self, stage: str, current: int, total: int, address: str) -> None:
        if self.progress:
            self.progress(stage, current, total, address)

    def discover(self, source_limit: int = 250) -> DiscoveryReport:
        leaderboard = self.client.trader_leaderboard(
            source_limit, period="30d", sort_by="realized_pnl"
        )
        rejected = Counter()
        rejected_addresses: set[str] = set()
        prefiltered = []
        for rank, wallet in enumerate(leaderboard, start=1):
            reasons = prefilter_leaderboard(wallet, self.policy)
            if reasons:
                rejected.update(reasons)
                rejected_addresses.add(wallet.address)
            else:
                prefiltered.append((rank, wallet))

        enriched_30d = []
        data_errors: dict[str, str] = {}
        for current, (rank, wallet) in enumerate(prefiltered, start=1):
            self._notify("30d", current, len(prefiltered), wallet.address)
            try:
                metrics_30d = self.client.wallet_pnl(wallet.address, "30d")
            except BirdeyeError as exc:
                data_errors[wallet.address] = f"30d: {exc}"
                continue
            reasons = filter_30d(metrics_30d, self.policy)
            if reasons:
                rejected.update(reasons)
                rejected_addresses.add(wallet.address)
            else:
                enriched_30d.append((rank, wallet, metrics_30d))

        final_inputs = []
        for current, (rank, wallet, metrics_30d) in enumerate(enriched_30d, start=1):
            self._notify("7d/90d", current, len(enriched_30d), wallet.address)
            try:
                metrics_7d = self.client.wallet_pnl(wallet.address, "7d")
            except BirdeyeError as exc:
                data_errors[wallet.address] = f"7d: {exc}"
                continue
            reasons = filter_recent(metrics_7d, self.policy)
            if reasons:
                rejected.update(reasons)
                rejected_addresses.add(wallet.address)
                continue
            try:
                metrics_90d = self.client.wallet_pnl(wallet.address, "90d")
            except BirdeyeError as exc:
                metrics_90d = None
                data_errors[wallet.address] = f"90d: {exc}"
            final_inputs.append(
                CandidateInput(
                    address=wallet.address,
                    source_rank=rank,
                    leaderboard=wallet,
                    metrics_30d=metrics_30d,
                    metrics_7d=metrics_7d,
                    metrics_90d=metrics_90d,
                )
            )

        ranked = rank_candidates(final_inputs)
        return DiscoveryReport(
            source_count=len(leaderboard),
            prefiltered_count=len(prefiltered),
            enriched_30d_count=len(enriched_30d),
            fully_evaluated_count=len(final_inputs),
            candidates=tuple(ranked),
            rejected_by_reason=dict(sorted(rejected.items())),
            data_errors=data_errors,
            rejected_count=len(rejected_addresses),
        )
