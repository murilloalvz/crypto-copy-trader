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
    "enrollment_duration_seconds",
    "follow_up_duration_seconds",
)


@dataclass(frozen=True)
class WalletForwardRunCompatibility:
    run_count: int
    reference_run_key: str | None
    label: str
    differing_fields: tuple[str, ...]
    pooling_allowed_automatically: bool


def _regime_value(run: WalletForwardRun, field: str):
    if field == "enrollment_duration_seconds":
        if run.enrollment_ends_at is None:
            return None
        return run.enrollment_ends_at - run.started_at
    if field == "follow_up_duration_seconds":
        if run.enrollment_ends_at is None or run.follow_up_ends_at is None:
            return None
        return run.follow_up_ends_at - run.enrollment_ends_at
    return getattr(run, field)


def compare_wallet_forward_run_regimes(
    runs: list[WalletForwardRun] | tuple[WalletForwardRun, ...],
) -> WalletForwardRunCompatibility:
    """Compare frozen technical regimes without ever auto-pooling their observations.

    Even identical manifests remain separate experimental runs. This helper only answers whether
    the technical configuration is comparable; it never decides that economic samples should be
    merged. Runtime version and cohort order are intentionally part of the regime because parser /
    causal-boundary behavior and sequential polling order can affect observability. Enrollment and
    follow-up are compared by duration rather than absolute timestamps so equivalent protocols run
    on different calendar dates remain comparable while different censoring designs do not.
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
        reference_value = _regime_value(reference, field)
        if any(_regime_value(item, field) != reference_value for item in items[1:]):
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
