from dataclasses import dataclass

from src.wallet_forward_runs import WalletForwardRun


REGIME_FIELDS = (
    "runtime_version",
    "cohort",
    "interval_seconds",
    "quote_delays_seconds",
    "with_jupiter_quotes",
    "copy_size_usd",
    "quote_mode",
    "quote_intake_grace_seconds",
)


@dataclass(frozen=True)
class WalletForwardRunCompatibility:
    run_count: int
    reference_run_key: str | None
    label: str
    differing_fields: tuple[str, ...]
    pooling_allowed_automatically: bool


def compare_wallet_forward_run_regimes(
    runs: list[WalletForwardRun] | tuple[WalletForwardRun, ...],
) -> WalletForwardRunCompatibility:
    """Compare frozen technical regimes without ever auto-pooling their observations.

    Even identical manifests remain separate experimental runs. This helper only answers whether
    the technical configuration is comparable; it never decides that economic samples should be
    merged. Runtime version and cohort order are intentionally part of the regime because parser /
    causal-boundary behavior and sequential polling order can affect observability.
    """

    items = list(runs)
    if not items:
        return WalletForwardRunCompatibility(
            run_count=0,
            reference_run_key=None,
            label="NO_RUNS",
            differing_fields=(),
            pooling_allowed_automatically=False,
        )
    if len({item.run_key for item in items}) != len(items):
        raise ValueError("run manifests must be unique")

    reference = items[0]
    differing: list[str] = []
    for field in REGIME_FIELDS:
        reference_value = getattr(reference, field)
        if any(getattr(item, field) != reference_value for item in items[1:]):
            differing.append(field)

    if len(items) == 1:
        label = "SINGLE_RUN"
    elif differing:
        label = "MIXED_TECHNICAL_REGIME_DO_NOT_POOL"
    else:
        label = "SAME_TECHNICAL_REGIME_COMPARE_SEPARATELY"

    return WalletForwardRunCompatibility(
        run_count=len(items),
        reference_run_key=reference.run_key,
        label=label,
        differing_fields=tuple(differing),
        pooling_allowed_automatically=False,
    )
