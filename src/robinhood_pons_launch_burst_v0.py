"""Robinhood Chain / Pons V2 Launch Burst V0 primitives.

Research-only, feature-only market-first surface.

Scientific rules:
- Robinhood/Pons is a separate stratum from Solana/Pump.
- Windows are causal on local observation time, never on future outcome data.
- Canonical chain ordering is retained as (block_number, transaction_index, log_index).
- V0 headline cohort is native-ETH quoted Pons V2 launches only. Custom-pair
  launches are counted for coverage but not mixed into quote-flow distributions.
- No economic outcome, selector, threshold, score, or trade recommendation lives here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from statistics import median
from typing import Iterable, Mapping, Sequence


ROBINHOOD_CHAIN_ID = 4663
PONS_V2_FACTORY = "0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
WINDOWS_SECONDS = (1, 5, 10, 30)
METHOD_VERSION = "robinhood_pons_launch_burst_v0"

TOKEN_LAUNCHED_SIGNATURE = "TokenLaunched(address,address,address,address,uint256,uint256)"
CURVE_BUY_SIGNATURE = "CurveBuy(address,address,uint256,uint256,uint256,uint256)"
CURVE_SELL_SIGNATURE = "CurveSell(address,address,uint256,uint256,uint256,uint256)"


def _norm_address(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("address must be a string")
    value = value.strip().lower()
    if not value.startswith("0x") or len(value) != 42:
        raise ValueError(f"invalid EVM address: {value!r}")
    int(value[2:], 16)
    return value


def _require_nonnegative_int(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _hex_int(value: str | int | None, *, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise TypeError("hex quantity must be str or int")
    return int(value, 16)


def _topic_address(topic: str) -> str:
    if not isinstance(topic, str) or not topic.startswith("0x"):
        raise ValueError("invalid indexed address topic")
    body = topic[2:].rjust(64, "0")
    if len(body) != 64:
        raise ValueError("indexed address topic must be 32 bytes")
    return _norm_address("0x" + body[-40:])


def _data_words(data: str) -> list[int]:
    if not isinstance(data, str) or not data.startswith("0x"):
        raise ValueError("log data must be 0x-prefixed hex")
    body = data[2:]
    if len(body) % 64 != 0:
        raise ValueError("log data must be whole 32-byte ABI words")
    return [int(body[i : i + 64], 16) for i in range(0, len(body), 64)]


def _data_address(word: int) -> str:
    return _norm_address(f"0x{word & ((1 << 160) - 1):040x}")


@dataclass(frozen=True)
class PonsLaunchObservationV0:
    token: str
    curve: str
    deployer: str
    pair_token: str
    launch_config_id: int
    graduation_threshold_raw: int
    block_number: int
    transaction_index: int
    log_index: int
    transaction_hash: str
    block_hash: str
    observed_at_ns: int
    block_timestamp_s: int | None = None

    def __post_init__(self) -> None:
        for name in ("token", "curve", "deployer", "pair_token"):
            object.__setattr__(self, name, _norm_address(getattr(self, name)))
        for name in ("launch_config_id", "graduation_threshold_raw", "block_number", "transaction_index", "log_index", "observed_at_ns"):
            _require_nonnegative_int(getattr(self, name), name)
        if self.block_timestamp_s is not None:
            _require_nonnegative_int(self.block_timestamp_s, "block_timestamp_s")

    @property
    def is_native_eth_quote(self) -> bool:
        return self.pair_token == ZERO_ADDRESS

    @property
    def chain_order(self) -> tuple[int, int, int]:
        return self.block_number, self.transaction_index, self.log_index


@dataclass(frozen=True)
class PonsTradeObservationV0:
    side: str
    curve: str
    actor: str
    recipient: str
    quote_amount_raw: int
    token_amount_raw: int
    fee_raw: int
    tax_raw: int
    block_number: int
    transaction_index: int
    log_index: int
    transaction_hash: str
    block_hash: str
    observed_at_ns: int
    block_timestamp_s: int | None = None

    def __post_init__(self) -> None:
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        for name in ("curve", "actor", "recipient"):
            object.__setattr__(self, name, _norm_address(getattr(self, name)))
        for name in ("quote_amount_raw", "token_amount_raw", "fee_raw", "tax_raw", "block_number", "transaction_index", "log_index", "observed_at_ns"):
            _require_nonnegative_int(getattr(self, name), name)
        if self.block_timestamp_s is not None:
            _require_nonnegative_int(self.block_timestamp_s, "block_timestamp_s")

    @property
    def chain_order(self) -> tuple[int, int, int]:
        return self.block_number, self.transaction_index, self.log_index


@dataclass(frozen=True)
class PonsBurstSnapshotV0:
    method_version: str
    token: str
    curve: str
    deployer: str
    pair_token: str
    native_eth_cohort: bool
    graduation_threshold_raw: int
    horizon_seconds: int
    launch_observed_at_ns: int
    cutoff_observed_at_ns: int
    snapshot_observed_at_ns: int
    snapshot_dispatch_lag_ms: float
    trade_count: int
    buy_count: int
    sell_count: int
    unique_actors: int
    unique_buyers: int
    unique_sellers: int
    unique_recipients: int
    recipient_mismatch_count: int
    recipient_mismatch_share: float | None
    gross_buy_quote_raw: int
    gross_sell_quote_raw: int
    gross_quote_activity_raw: int
    signed_quote_flow_raw: int
    signed_quote_flow_over_activity: float | None
    gross_tokens_bought_raw: int
    gross_tokens_sold_raw: int
    net_token_demand_raw: int
    fee_raw: int
    tax_raw: int
    buy_fee_share_bps_observed: float | None
    buy_total_charge_share_bps_observed: float | None
    sell_total_charge_share_bps_observed: float | None
    deployer_buy_quote_raw: int
    deployer_buy_quote_share: float | None
    top1_buyer_quote_share: float | None
    top3_buyer_quote_share: float | None
    first_trade_delay_ms: float | None
    time_to_3_trades_ms: float | None
    time_to_5_trades_ms: float | None
    median_interarrival_ms: float | None
    max_interarrival_ms: float | None
    trade_rate_per_second: float
    early_half_trade_count: int
    late_half_trade_count: int
    half_window_acceleration: float | None
    first_buy_effective_quote_per_token: float | None
    last_buy_effective_quote_per_token: float | None
    buy_effective_price_ratio_last_over_first: float | None
    first_chain_order: tuple[int, int, int] | None
    last_chain_order: tuple[int, int, int] | None
    data_quality_flags: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def decode_token_launched_log_v0(log: Mapping[str, object], *, topic0: str) -> PonsLaunchObservationV0 | None:
    topics = list(log.get("topics") or [])
    if len(topics) != 4 or str(topics[0]).lower() != topic0.lower():
        return None
    words = _data_words(str(log.get("data", "0x")))
    if len(words) != 3:
        raise ValueError("TokenLaunched data must contain exactly three ABI words")
    return PonsLaunchObservationV0(
        token=_topic_address(str(topics[1])), curve=_topic_address(str(topics[2])), deployer=_topic_address(str(topics[3])),
        pair_token=_data_address(words[0]), launch_config_id=words[1], graduation_threshold_raw=words[2],
        block_number=_hex_int(log.get("blockNumber")), transaction_index=_hex_int(log.get("transactionIndex")), log_index=_hex_int(log.get("logIndex")),
        transaction_hash=str(log.get("transactionHash") or ""), block_hash=str(log.get("blockHash") or ""),
        observed_at_ns=_require_nonnegative_int(int(log.get("observed_at_ns") or 0), "observed_at_ns"),
        block_timestamp_s=(_require_nonnegative_int(int(log["block_timestamp_s"]), "block_timestamp_s") if log.get("block_timestamp_s") is not None else None),
    )


def decode_curve_trade_log_v0(log: Mapping[str, object], *, buy_topic0: str, sell_topic0: str) -> PonsTradeObservationV0 | None:
    topics = list(log.get("topics") or [])
    if len(topics) != 3:
        return None
    kind = str(topics[0]).lower()
    if kind == buy_topic0.lower(): side = "BUY"
    elif kind == sell_topic0.lower(): side = "SELL"
    else: return None
    words = _data_words(str(log.get("data", "0x")))
    if len(words) != 4:
        raise ValueError(f"{side} data must contain exactly four ABI words")
    return PonsTradeObservationV0(
        side=side, curve=_norm_address(str(log.get("address"))), actor=_topic_address(str(topics[1])), recipient=_topic_address(str(topics[2])),
        quote_amount_raw=words[0] if side == "BUY" else words[1], token_amount_raw=words[1] if side == "BUY" else words[0], fee_raw=words[2], tax_raw=words[3],
        block_number=_hex_int(log.get("blockNumber")), transaction_index=_hex_int(log.get("transactionIndex")), log_index=_hex_int(log.get("logIndex")),
        transaction_hash=str(log.get("transactionHash") or ""), block_hash=str(log.get("blockHash") or ""),
        observed_at_ns=_require_nonnegative_int(int(log.get("observed_at_ns") or 0), "observed_at_ns"),
        block_timestamp_s=(_require_nonnegative_int(int(log["block_timestamp_s"]), "block_timestamp_s") if log.get("block_timestamp_s") is not None else None),
    )


def _share(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator > 0 else None


def _effective_price(quote_raw: int, token_raw: int) -> float | None:
    return quote_raw / token_raw if token_raw > 0 else None


def _time_to_n_ms(trades: Sequence[PonsTradeObservationV0], launch_ns: int, n: int) -> float | None:
    if len(trades) < n: return None
    return max(0, trades[n - 1].observed_at_ns - launch_ns) / 1_000_000.0


def build_snapshot_v0(*, launch: PonsLaunchObservationV0, trades: Iterable[PonsTradeObservationV0], horizon_seconds: int, snapshot_observed_at_ns: int) -> PonsBurstSnapshotV0:
    if horizon_seconds not in WINDOWS_SECONDS:
        raise ValueError(f"unsupported horizon: {horizon_seconds}")
    cutoff_ns = launch.observed_at_ns + horizon_seconds * 1_000_000_000
    if snapshot_observed_at_ns < cutoff_ns:
        raise ValueError("snapshot cannot be frozen before its causal cutoff")
    all_trades = list(trades)
    rows = sorted((row for row in all_trades if row.curve == launch.curve and launch.observed_at_ns <= row.observed_at_ns <= cutoff_ns), key=lambda row: (row.observed_at_ns, row.chain_order))
    buys = [row for row in rows if row.side == "BUY"]
    sells = [row for row in rows if row.side == "SELL"]
    gross_buy_quote = sum(row.quote_amount_raw for row in buys); gross_sell_quote = sum(row.quote_amount_raw for row in sells)
    activity = gross_buy_quote + gross_sell_quote; signed = gross_buy_quote - gross_sell_quote
    tokens_bought = sum(row.token_amount_raw for row in buys); tokens_sold = sum(row.token_amount_raw for row in sells)
    fee_raw = sum(row.fee_raw for row in rows); tax_raw = sum(row.tax_raw for row in rows); mismatch = sum(row.actor != row.recipient for row in rows)
    buyer_quote: dict[str, int] = defaultdict(int)
    for row in buys: buyer_quote[row.actor] += row.quote_amount_raw
    buyer_amounts = sorted(buyer_quote.values(), reverse=True); top1 = buyer_amounts[0] if buyer_amounts else 0; top3 = sum(buyer_amounts[:3])
    deployer_buy = sum(row.quote_amount_raw for row in buys if row.actor == launch.deployer)
    buy_fees = sum(row.fee_raw for row in buys); buy_taxes = sum(row.tax_raw for row in buys)
    sell_fees = sum(row.fee_raw for row in sells); sell_taxes = sum(row.tax_raw for row in sells); sell_gross_before_charges = sum(row.quote_amount_raw + row.fee_raw + row.tax_raw for row in sells)
    times = [row.observed_at_ns for row in rows]; interarrival_ms = [(times[i] - times[i - 1]) / 1_000_000.0 for i in range(1, len(times))]
    half_cutoff = launch.observed_at_ns + horizon_seconds * 500_000_000; early_count = sum(row.observed_at_ns <= half_cutoff for row in rows); late_count = len(rows) - early_count
    buy_prices = [_effective_price(row.quote_amount_raw, row.token_amount_raw) for row in buys]; buy_prices = [v for v in buy_prices if v is not None]
    first_buy_price = buy_prices[0] if buy_prices else None; last_buy_price = buy_prices[-1] if buy_prices else None
    flags: list[str] = []
    if not launch.is_native_eth_quote: flags.append("CUSTOM_PAIR_NOT_HEADLINE_COHORT")
    if not rows: flags.append("NO_TRADES_WITHIN_WINDOW")
    if gross_buy_quote and buy_fees == 0: flags.append("ZERO_BUY_FEE_OBSERVED")
    if any(row.observed_at_ns < launch.observed_at_ns for row in all_trades): flags.append("PRE_LAUNCH_OBSERVATION_IGNORED")
    return PonsBurstSnapshotV0(
        METHOD_VERSION, launch.token, launch.curve, launch.deployer, launch.pair_token, launch.is_native_eth_quote, launch.graduation_threshold_raw,
        horizon_seconds, launch.observed_at_ns, cutoff_ns, snapshot_observed_at_ns, (snapshot_observed_at_ns-cutoff_ns)/1_000_000.0,
        len(rows), len(buys), len(sells), len({r.actor for r in rows}), len({r.actor for r in buys}), len({r.actor for r in sells}), len({r.recipient for r in rows}), mismatch, _share(mismatch,len(rows)),
        gross_buy_quote, gross_sell_quote, activity, signed, _share(signed,activity), tokens_bought, tokens_sold, tokens_bought-tokens_sold, fee_raw, tax_raw,
        (10_000.0*buy_fees/gross_buy_quote if gross_buy_quote else None), (10_000.0*(buy_fees+buy_taxes)/gross_buy_quote if gross_buy_quote else None),
        (10_000.0*(sell_fees+sell_taxes)/sell_gross_before_charges if sell_gross_before_charges else None), deployer_buy, _share(deployer_buy,gross_buy_quote), _share(top1,gross_buy_quote), _share(top3,gross_buy_quote),
        _time_to_n_ms(rows,launch.observed_at_ns,1), _time_to_n_ms(rows,launch.observed_at_ns,3), _time_to_n_ms(rows,launch.observed_at_ns,5),
        median(interarrival_ms) if interarrival_ms else None, max(interarrival_ms) if interarrival_ms else None, len(rows)/horizon_seconds, early_count, late_count,
        ((late_count-early_count)/len(rows) if rows else None), first_buy_price, last_buy_price, (last_buy_price/first_buy_price if first_buy_price and last_buy_price is not None else None),
        rows[0].chain_order if rows else None, rows[-1].chain_order if rows else None, tuple(flags)
    )


class RobinhoodPonsBurstBookV0:
    def __init__(self) -> None:
        self.launches_by_curve: dict[str, PonsLaunchObservationV0] = {}
        self.trades_by_curve: dict[str, list[PonsTradeObservationV0]] = defaultdict(list)
        self._seen_event_keys: set[tuple[str, int]] = set(); self._emitted: set[tuple[str, int]] = set()
        self.custom_pair_launches = 0; self.orphan_trade_count = 0

    @staticmethod
    def _event_key(tx_hash: str, log_index: int) -> tuple[str, int]: return tx_hash.lower(), log_index

    def add_launch(self, launch: PonsLaunchObservationV0) -> bool:
        key = self._event_key(launch.transaction_hash, launch.log_index)
        if key in self._seen_event_keys: return False
        self._seen_event_keys.add(key); existing = self.launches_by_curve.get(launch.curve)
        if existing is not None and existing != launch: raise ValueError(f"curve already mapped to a different launch: {launch.curve}")
        self.launches_by_curve[launch.curve] = launch
        if not launch.is_native_eth_quote: self.custom_pair_launches += 1
        return True

    def add_trade(self, trade: PonsTradeObservationV0) -> bool:
        key = self._event_key(trade.transaction_hash, trade.log_index)
        if key in self._seen_event_keys: return False
        self._seen_event_keys.add(key); launch = self.launches_by_curve.get(trade.curve)
        if launch is None: self.orphan_trade_count += 1; return False
        if trade.chain_order < launch.chain_order: raise ValueError("trade chain order precedes launch chain order")
        self.trades_by_curve[trade.curve].append(trade); return True

    def ready_snapshots(self, now_ns: int) -> list[PonsBurstSnapshotV0]:
        _require_nonnegative_int(now_ns,"now_ns"); output=[]
        for curve, launch in tuple(self.launches_by_curve.items()):
            for horizon in WINDOWS_SECONDS:
                key=(curve,horizon); cutoff=launch.observed_at_ns+horizon*1_000_000_000
                if key in self._emitted or now_ns < cutoff: continue
                output.append(build_snapshot_v0(launch=launch,trades=self.trades_by_curve.get(curve,()),horizon_seconds=horizon,snapshot_observed_at_ns=now_ns)); self._emitted.add(key)
        output.sort(key=lambda row:(row.launch_observed_at_ns,row.curve,row.horizon_seconds)); return output

    def counts(self) -> dict[str,int]:
        native=sum(row.is_native_eth_quote for row in self.launches_by_curve.values())
        return {"launches":len(self.launches_by_curve),"native_eth_launches":native,"custom_pair_launches":self.custom_pair_launches,"trades":sum(len(rows) for rows in self.trades_by_curve.values()),"orphan_trade_count":self.orphan_trade_count,"snapshots_emitted":len(self._emitted)}
