import math
from dataclasses import dataclass

from src.discovery.models import WaveTokenSnapshot
from src.wave_radar import WaveRadarPolicy, volume_windows_are_consistent


MARKET_INTEGRITY_METHOD_VERSION = "market_integrity_v1_aggregate_observational"


@dataclass(frozen=True)
class MarketIntegrityFeatures:
    """Descriptive market-integrity features from one causal aggregate snapshot.

    These fields are deliberately not a manipulation score. Aggregate search data can
    describe concentration, imbalance and volume shape, but it cannot prove wash trading,
    self-trading or coordinated wallet behavior without transaction/counterparty detail.
    """

    token_mint: str
    method_version: str
    buy_pressure_pct: float | None
    trade_imbalance_pct: float | None
    volume_acceleration: float | None
    volume_5m_share_of_1h_pct: float | None
    volume_1h_share_of_24h_pct: float | None
    transactions_per_holder: float | None
    top10_pct: float | None
    dev_pct: float | None
    insiders_pct: float | None
    snipers_pct: float | None
    risk_score: float | None
    lp_burn_pct: float | None
    existing_gate_flags: tuple[str, ...]
    data_quality_flags: tuple[str, ...]
    detection_limits: tuple[str, ...]


_DETECTION_LIMITS = (
    "aggregate_snapshot_cannot_identify_self_trading",
    "counterparty_graph_unavailable",
    "order_level_sequence_unavailable",
    "funding_relationships_unavailable",
)


def _safe_pct(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return 100.0 * numerator / denominator


def build_market_integrity_features(
    token: WaveTokenSnapshot,
    policy: WaveRadarPolicy | None = None,
) -> MarketIntegrityFeatures:
    """Build observational integrity features without changing Wave eligibility.

    Flags that reuse Wave thresholds are explicitly named ``existing_gate_flags`` so this
    module cannot be mistaken for a new set of entry filters. New descriptive ratios are
    returned as raw features only; no new threshold is invented here.
    """

    policy = policy or WaveRadarPolicy()
    if not token.token.strip():
        raise ValueError("token mint cannot be empty")
    if token.buys < 0 or token.sells < 0 or token.total_transactions < 0:
        raise ValueError("trade counts must be non-negative")
    if min(token.volume_5m_usd, token.volume_1h_usd, token.volume_24h_usd) < 0:
        raise ValueError("volume fields must be non-negative")

    trade_sides = token.buys + token.sells
    buy_pressure = _safe_pct(token.buys, trade_sides)
    trade_imbalance = (
        _safe_pct(abs(token.buys - token.sells), trade_sides)
        if trade_sides > 0
        else None
    )
    windows_consistent = volume_windows_are_consistent(token)
    hourly_baseline_5m = token.volume_1h_usd / 12 if token.volume_1h_usd > 0 else 0.0
    acceleration = (
        token.volume_5m_usd / hourly_baseline_5m
        if windows_consistent and hourly_baseline_5m > 0
        else None
    )

    existing_gate_flags: list[str] = []
    if buy_pressure is not None and (buy_pressure < 10 or buy_pressure > 90):
        existing_gate_flags.append("trade_imbalance_extreme")
    if token.top10_pct is not None and token.top10_pct > policy.max_top10_pct:
        existing_gate_flags.append("top10_concentration_high")
    if token.dev_pct is not None and token.dev_pct > policy.max_dev_pct:
        existing_gate_flags.append("developer_concentration_high")
    if token.insiders_pct is not None and token.insiders_pct > policy.max_insiders_pct:
        existing_gate_flags.append("insider_concentration_high")
    if token.snipers_pct is not None and token.snipers_pct > policy.max_snipers_pct:
        existing_gate_flags.append("sniper_concentration_high")
    if token.lp_burn_pct is not None and token.lp_burn_pct < policy.min_lp_burn_pct:
        existing_gate_flags.append("lp_burn_unconfirmed")

    quality: list[str] = []
    if not windows_consistent:
        quality.append("volume_windows_inconsistent")
    if trade_sides == 0:
        quality.append("trade_counts_unavailable")
    elif token.buys == 0 or token.sells == 0:
        quality.append("one_sided_trade_counts")
    if token.holders is None or token.holders <= 0:
        quality.append("holders_unavailable")
    if token.risk_score is None:
        quality.append("risk_unavailable")
    if token.top10_pct is None:
        quality.append("top10_unavailable")
    if token.dev_pct is None:
        quality.append("developer_share_unavailable")
    if token.insiders_pct is None:
        quality.append("insider_share_unavailable")
    if token.snipers_pct is None:
        quality.append("sniper_share_unavailable")

    transactions_per_holder = (
        token.total_transactions / token.holders
        if token.holders is not None and token.holders > 0
        else None
    )

    # Avoid serializing inf/nan into JSON-facing dataclasses even if a provider returns
    # pathological floats. Invalid finite observations are represented as unavailable.
    def finite_or_none(value: float | None) -> float | None:
        return value if value is not None and math.isfinite(value) else None

    return MarketIntegrityFeatures(
        token_mint=token.token,
        method_version=MARKET_INTEGRITY_METHOD_VERSION,
        buy_pressure_pct=finite_or_none(buy_pressure),
        trade_imbalance_pct=finite_or_none(trade_imbalance),
        volume_acceleration=finite_or_none(acceleration),
        volume_5m_share_of_1h_pct=finite_or_none(
            _safe_pct(token.volume_5m_usd, token.volume_1h_usd)
        ),
        volume_1h_share_of_24h_pct=finite_or_none(
            _safe_pct(token.volume_1h_usd, token.volume_24h_usd)
        ),
        transactions_per_holder=finite_or_none(transactions_per_holder),
        top10_pct=token.top10_pct,
        dev_pct=token.dev_pct,
        insiders_pct=token.insiders_pct,
        snipers_pct=token.snipers_pct,
        risk_score=token.risk_score,
        lp_burn_pct=token.lp_burn_pct,
        existing_gate_flags=tuple(existing_gate_flags),
        data_quality_flags=tuple(quality),
        detection_limits=_DETECTION_LIMITS,
    )
