import math
from dataclasses import dataclass

from src.discovery.models import WaveTokenSnapshot


@dataclass(frozen=True)
class WaveRadarPolicy:
    """Conservative gates for a useful but read-only momentum radar."""

    min_liquidity_usd: float = 50_000.0
    min_volume_5m_usd: float = 5_000.0
    min_volume_acceleration: float = 1.2
    min_wave_score: float = 55.0
    min_holders: int = 50
    min_transactions: int = 50
    max_risk_score: float = 6.0
    max_top10_pct: float = 40.0
    max_dev_pct: float = 10.0
    max_insiders_pct: float = 20.0
    max_snipers_pct: float = 20.0
    min_lp_burn_pct: float = 90.0


RADAR_BARRIER_LABELS = {
    "price_unavailable": "preço atual indisponível",
    "pool_unavailable": "pool principal indisponível",
    "liquidity_low": "liquidez abaixo do mínimo",
    "volume_5m_low": "volume de 5 minutos abaixo do mínimo",
    "volume_not_accelerating": "volume de 5 minutos ainda não está acelerando",
    "wave_score_low": "Wave Score abaixo do mínimo",
    "holders_unavailable": "quantidade de holders indisponível",
    "holders_low": "poucos holders",
    "transactions_low": "poucas transações",
    "risk_unavailable": "Risk Score indisponível",
    "risk_high": "Risk Score acima do máximo",
    "top10_concentration_high": "concentração excessiva no Top 10",
    "developer_concentration_high": "concentração excessiva do desenvolvedor",
    "insider_concentration_high": "concentração excessiva de insiders",
    "sniper_concentration_high": "concentração excessiva de snipers",
    "trade_imbalance_extreme": "desequilíbrio extremo entre compras e vendas",
    "mint_authority_enabled": "mint authority ainda habilitada",
    "freeze_authority_enabled": "freeze authority ainda habilitada",
}

RADAR_CAUTION_LABELS = {
    "lp_burn_unconfirmed": (
        "LP burn abaixo de 90% ou não aplicável ao tipo de pool; "
        "o Risk Score agregado permanece como barreira"
    ),
}


@dataclass(frozen=True)
class WaveRadarResult:
    token: WaveTokenSnapshot
    wave_score: float
    passed: bool
    reasons: tuple[str, ...]
    barriers: tuple[str, ...]
    cautions: tuple[str, ...]
    score_components: dict[str, float]
    volume_acceleration: float | None
    buy_pressure_pct: float | None


@dataclass(frozen=True)
class WaveRadarReport:
    analyzed_count: int
    passed_count: int
    results: tuple[WaveRadarResult, ...]
    rejected_by_reason: dict[str, int]


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _log_scale(value: float, floor: float, ceiling: float) -> float:
    if value <= floor:
        return 0.0
    if value >= ceiling:
        return 1.0
    return math.log(value / floor) / math.log(ceiling / floor)


def evaluate_wave_token(
    token: WaveTokenSnapshot,
    policy: WaveRadarPolicy | None = None,
) -> WaveRadarResult:
    policy = policy or WaveRadarPolicy()
    hourly_baseline_5m = token.volume_1h_usd / 12 if token.volume_1h_usd > 0 else 0
    acceleration = (
        token.volume_5m_usd / hourly_baseline_5m
        if hourly_baseline_5m > 0
        else None
    )
    trade_sides = token.buys + token.sells
    buy_pressure = 100 * token.buys / trade_sides if trade_sides > 0 else None

    components = {
        "liquidity": 20
        * _log_scale(token.liquidity_usd, policy.min_liquidity_usd, 2_000_000),
        "volume_5m": 25
        * _log_scale(token.volume_5m_usd, policy.min_volume_5m_usd, 250_000),
        "volume_acceleration": 20
        * (0.0 if acceleration is None else _clamp((acceleration - 1) / 4)),
        # Momentum saudável não é o mesmo que 100% de compras. Uma razão
        # extrema pode indicar volume manipulado, portanto a nota cai após 65%.
        "buy_pressure": 10
        * (
            0.0
            if buy_pressure is None
            else (
                _clamp((buy_pressure - 45) / 20)
                if buy_pressure <= 65
                else _clamp((85 - buy_pressure) / 20)
            )
        ),
        "risk": 15
        * (
            0.0
            if token.risk_score is None
            else _clamp((7 - token.risk_score) / 6)
        ),
        "distribution": 10
        * (
            0.0
            if token.top10_pct is None
            else _clamp((policy.max_top10_pct - token.top10_pct) / 30)
        ),
    }
    wave_score = round(sum(components.values()), 1)
    barriers = []
    if token.price_usd <= 0:
        barriers.append("price_unavailable")
    if not token.pool_address:
        barriers.append("pool_unavailable")
    if token.liquidity_usd < policy.min_liquidity_usd:
        barriers.append("liquidity_low")
    if token.volume_5m_usd < policy.min_volume_5m_usd:
        barriers.append("volume_5m_low")
    if acceleration is None or acceleration < policy.min_volume_acceleration:
        barriers.append("volume_not_accelerating")
    if wave_score < policy.min_wave_score:
        barriers.append("wave_score_low")
    if token.holders is None:
        barriers.append("holders_unavailable")
    elif token.holders < policy.min_holders:
        barriers.append("holders_low")
    if token.total_transactions < policy.min_transactions:
        barriers.append("transactions_low")
    if token.risk_score is None:
        barriers.append("risk_unavailable")
    elif token.risk_score > policy.max_risk_score:
        barriers.append("risk_high")
    if token.top10_pct is not None and token.top10_pct > policy.max_top10_pct:
        barriers.append("top10_concentration_high")
    if token.dev_pct is not None and token.dev_pct > policy.max_dev_pct:
        barriers.append("developer_concentration_high")
    if token.insiders_pct is not None and token.insiders_pct > policy.max_insiders_pct:
        barriers.append("insider_concentration_high")
    if token.snipers_pct is not None and token.snipers_pct > policy.max_snipers_pct:
        barriers.append("sniper_concentration_high")
    if buy_pressure is not None and (buy_pressure < 10 or buy_pressure > 90):
        barriers.append("trade_imbalance_extreme")
    if token.mint_authority:
        barriers.append("mint_authority_enabled")
    if token.freeze_authority:
        barriers.append("freeze_authority_enabled")

    cautions = []
    # lpBurn=0 is normal for some concentrated-liquidity markets, including
    # Meteora DLMM. The source Risk Score already incorporates removable LP,
    # so treating this raw field as a universal hard gate creates false rejects.
    if token.lp_burn_pct is not None and token.lp_burn_pct < policy.min_lp_burn_pct:
        cautions.append("lp_burn_unconfirmed")

    holder_text = "holders indisponíveis" if token.holders is None else f"{token.holders} holders"
    reasons = [
        f"US$ {token.volume_5m_usd:,.0f} de volume em 5 minutos",
        f"US$ {token.liquidity_usd:,.0f} de liquidez atual",
        f"{holder_text} e {token.total_transactions} transações",
    ]
    if acceleration is not None:
        reasons.append(
            f"ritmo de volume {acceleration:.1f}x versus a média de 5min da última hora"
        )
    if buy_pressure is not None:
        reasons.append(f"pressão compradora observada de {buy_pressure:.1f}%")
    if token.risk_score is not None:
        reasons.append(f"Risk Score da fonte: {token.risk_score:.1f}/10")

    return WaveRadarResult(
        token=token,
        wave_score=wave_score,
        passed=not barriers,
        reasons=tuple(reasons),
        barriers=tuple(barriers),
        cautions=tuple(cautions),
        score_components={key: round(value, 2) for key, value in components.items()},
        volume_acceleration=acceleration,
        buy_pressure_pct=buy_pressure,
    )


def build_wave_radar_report(
    tokens: list[WaveTokenSnapshot] | tuple[WaveTokenSnapshot, ...],
    policy: WaveRadarPolicy | None = None,
) -> WaveRadarReport:
    evaluated = [evaluate_wave_token(token, policy) for token in tokens]
    ranked = sorted(
        evaluated,
        key=lambda item: (
            not item.passed,
            -item.wave_score,
            -item.token.volume_5m_usd,
            item.token.token,
        ),
    )
    rejected = {}
    for item in evaluated:
        for barrier in item.barriers:
            rejected[barrier] = rejected.get(barrier, 0) + 1
    return WaveRadarReport(
        analyzed_count=len(evaluated),
        passed_count=sum(item.passed for item in evaluated),
        results=tuple(ranked),
        rejected_by_reason=dict(sorted(rejected.items())),
    )
