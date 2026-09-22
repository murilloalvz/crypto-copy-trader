use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    cmp::Ordering,
    collections::{BTreeSet, HashMap},
    env,
    fs::File,
    io::{BufRead, BufReader, BufWriter, Error, ErrorKind, Write},
    path::PathBuf,
    time::Instant,
};

const VERSION: &str = "rust_indexed_signal_plane_v0";
const RADAR_VERSION: &str = "market_opportunity_radar_v1_2_clock_domains";
const FAST_WINDOW_SECONDS: i64 = 30;
const BASELINE_HORIZON_SECONDS: i64 = 300;
const MIN_FAST_EVENTS: usize = 6;
const MIN_UNIQUE_WALLETS: usize = 4;
const MIN_UNIQUE_TRANSACTIONS: usize = 4;
const MIN_BASELINE_EVENTS: usize = 3;
const MIN_ACTIVITY_ACCELERATION_RATIO: f64 = 3.0;
const FRESH_MARKET_MAX_AGE_SECONDS: i64 = 120;
const PRESSURE_THRESHOLD_PCT: f64 = 20.0;

#[derive(Debug, Deserialize)]
struct TraceHeader {
    #[serde(rename = "type")]
    kind: String,
    version: String,
    record_count: usize,
}

#[derive(Debug, Deserialize)]
struct RawRecord {
    #[serde(rename = "type")]
    kind: String,
    sequence: usize,
    observation: Value,
}

#[derive(Debug, Clone, Deserialize)]
struct Trade {
    token_mint: String,
    side: String,
    chain_time: i64,
    observed_at: i64,
    wallet_address: Option<String>,
    notional_usd: Option<f64>,
    price_usd: Option<f64>,
    venue: Option<String>,
    transaction_key: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct Lifecycle {
    token_mint: String,
    market_started_at: i64,
    observed_at: i64,
    venue: Option<String>,
}

#[derive(Debug, Clone)]
struct TradeRow {
    chain_time: i64,
    observed_at: i64,
    sequence: usize,
    trade: Trade,
}

#[derive(Debug, Clone, Serialize)]
struct Features {
    token_mint: String,
    as_of: i64,
    chain_as_of: i64,
    fast_window_seconds: i64,
    baseline_horizon_seconds: i64,
    fast_event_count: usize,
    baseline_event_count: usize,
    fast_buy_count: usize,
    fast_sell_count: usize,
    fast_unique_wallet_count: usize,
    fast_unique_transaction_count: Option<usize>,
    wallet_identity_coverage_pct: Option<f64>,
    transaction_identity_coverage_pct: Option<f64>,
    notional_coverage_pct: Option<f64>,
    price_coverage_pct: Option<f64>,
    fast_event_rate_per_second: f64,
    baseline_event_rate_per_second: Option<f64>,
    activity_acceleration_ratio: Option<f64>,
    signed_notional_imbalance_pct: Option<f64>,
    count_imbalance_pct: Option<f64>,
    direction: String,
    first_price_usd: Option<f64>,
    last_price_usd: Option<f64>,
    fast_return_pct: Option<f64>,
    median_observation_lag_seconds: Option<f64>,
    max_observation_lag_seconds: Option<i64>,
    venues: Vec<String>,
    market_age_seconds: Option<i64>,
    data_quality_flags: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
struct Trigger {
    token_mint: String,
    as_of: i64,
    method_version: String,
    trigger_kind: String,
    direction: String,
    features: Features,
}

#[derive(Default)]
struct State {
    rows: HashMap<String, Vec<TradeRow>>,
    lifecycle: HashMap<String, Lifecycle>,
    last_observed_at: HashMap<String, i64>,
    latest_chain_time: HashMap<String, i64>,
    late_chain_time_inserts: usize,
    compactions: usize,
}

fn uses_lifecycle(venue: &Option<String>) -> bool {
    let normalized = venue.as_deref().unwrap_or("").trim().to_ascii_lowercase();
    matches!(normalized.as_str(), "pump" | "pump_bonding_curve" | "pumpfun" | "pump.fun")
}

fn coverage(known: usize, total: usize) -> Option<f64> {
    if total == 0 {
        None
    } else {
        Some(100.0 * known as f64 / total as f64)
    }
}

fn cmp_row(a: &TradeRow, chain_time: i64, observed_at: i64, sequence: usize) -> Ordering {
    (a.chain_time, a.observed_at, a.sequence).cmp(&(chain_time, observed_at, sequence))
}

fn upper_bound_chain(rows: &[TradeRow], value: i64) -> usize {
    rows.partition_point(|row| row.chain_time <= value)
}

impl State {
    fn ingest_lifecycle(&mut self, item: Lifecycle) {
        if !uses_lifecycle(&item.venue) {
            return;
        }
        let replace = self
            .lifecycle
            .get(&item.token_mint)
            .map(|current| item.observed_at >= current.observed_at)
            .unwrap_or(true);
        if replace {
            self.lifecycle.insert(item.token_mint.clone(), item);
        }
    }

    fn ingest_trade(&mut self, sequence: usize, trade: Trade) -> Result<Option<Trigger>, String> {
        if trade.side != "buy" && trade.side != "sell" {
            return Err(format!("invalid side at sequence {sequence}"));
        }
        if trade.chain_time < 0 || trade.observed_at < 0 {
            return Err(format!("negative clock at sequence {sequence}"));
        }
        if let Some(previous) = self.last_observed_at.get(&trade.token_mint) {
            if trade.observed_at < *previous {
                return Err(format!("same-asset observed_at regression at sequence {sequence}"));
            }
        }
        self.last_observed_at
            .insert(trade.token_mint.clone(), trade.observed_at);

        let chain_as_of = self
            .latest_chain_time
            .get(&trade.token_mint)
            .map(|previous| (*previous).max(trade.chain_time))
            .unwrap_or(trade.chain_time);
        self.latest_chain_time
            .insert(trade.token_mint.clone(), chain_as_of);

        let token_mint = trade.token_mint.clone();
        let observed_at = trade.observed_at;
        let lifecycle_needed = uses_lifecycle(&trade.venue);
        let rows = self.rows.entry(token_mint.clone()).or_default();
        let row = TradeRow {
            chain_time: trade.chain_time,
            observed_at,
            sequence,
            trade,
        };
        if rows
            .last()
            .map(|last| cmp_row(last, row.chain_time, row.observed_at, row.sequence) != Ordering::Greater)
            .unwrap_or(true)
        {
            rows.push(row);
        } else {
            self.late_chain_time_inserts += 1;
            let index = rows.partition_point(|current| {
                cmp_row(current, row.chain_time, row.observed_at, row.sequence) != Ordering::Greater
            });
            rows.insert(index, row);
        }

        let cutoff = chain_as_of - BASELINE_HORIZON_SECONDS;
        let prune_to = upper_bound_chain(rows, cutoff);
        if prune_to > 0 {
            rows.drain(0..prune_to);
            self.compactions += 1;
        }

        let baseline_lower = chain_as_of - BASELINE_HORIZON_SECONDS;
        let fast_lower = chain_as_of - FAST_WINDOW_SECONDS;
        let baseline_start = upper_bound_chain(rows, baseline_lower);
        let fast_start = upper_bound_chain(rows, fast_lower);
        let fast_end = upper_bound_chain(rows, chain_as_of);
        let baseline_count = fast_start.saturating_sub(baseline_start);
        let fast: Vec<&Trade> = rows[fast_start..fast_end].iter().map(|row| &row.trade).collect();

        let lifecycle = if lifecycle_needed {
            self.lifecycle.get(&token_mint)
        } else {
            None
        };
        Ok(detect(
            &fast,
            baseline_count,
            &token_mint,
            observed_at,
            chain_as_of,
            lifecycle,
        ))
    }
}

fn detect(
    fast: &[&Trade],
    baseline_count: usize,
    token_mint: &str,
    as_of: i64,
    chain_as_of: i64,
    lifecycle: Option<&Lifecycle>,
) -> Option<Trigger> {
    let mut buys = 0usize;
    let mut sells = 0usize;
    let mut wallets = BTreeSet::new();
    let mut transactions = BTreeSet::new();
    let mut wallet_rows = 0usize;
    let mut transaction_rows = 0usize;
    let mut notional_rows = 0usize;
    let mut price_rows = 0usize;
    let mut buy_notional = 0.0f64;
    let mut sell_notional = 0.0f64;
    let mut venues = BTreeSet::new();

    for item in fast {
        if item.side == "buy" {
            buys += 1;
        } else {
            sells += 1;
        }
        if let Some(wallet) = &item.wallet_address {
            wallet_rows += 1;
            wallets.insert(wallet.clone());
        }
        if let Some(tx) = &item.transaction_key {
            transaction_rows += 1;
            transactions.insert(tx.clone());
        }
        if let Some(notional) = item.notional_usd {
            notional_rows += 1;
            if item.side == "buy" {
                buy_notional += notional;
            } else {
                sell_notional += notional;
            }
        }
        if item.price_usd.is_some() {
            price_rows += 1;
        }
        if let Some(venue) = &item.venue {
            venues.insert(venue.clone());
        }
    }

    let wallet_coverage = coverage(wallet_rows, fast.len());
    let transaction_coverage = coverage(transaction_rows, fast.len());
    let unique_transaction_count = if transaction_rows > 0 {
        Some(transactions.len())
    } else {
        None
    };
    let notional_coverage = coverage(notional_rows, fast.len());
    let price_coverage = coverage(price_rows, fast.len());

    let notionals_complete = !fast.is_empty() && notional_rows == fast.len();
    let signed_notional_imbalance_pct = if notionals_complete {
        let total = buy_notional + sell_notional;
        if total > 0.0 {
            Some(100.0 * (buy_notional - sell_notional) / total)
        } else {
            None
        }
    } else {
        None
    };
    let count_imbalance_pct = if fast.is_empty() {
        None
    } else {
        Some(100.0 * (buys as f64 - sells as f64) / fast.len() as f64)
    };
    let pressure = signed_notional_imbalance_pct.or(count_imbalance_pct);
    let direction = match pressure {
        None => "unknown_pressure",
        Some(value) if value >= PRESSURE_THRESHOLD_PCT => "upward_pressure",
        Some(value) if value <= -PRESSURE_THRESHOLD_PCT => "downward_pressure",
        Some(_) => "mixed_pressure",
    }
    .to_string();

    let prices_complete = !fast.is_empty() && price_rows == fast.len();
    let first_price = if prices_complete {
        fast.first().and_then(|item| item.price_usd)
    } else {
        None
    };
    let last_price = if prices_complete {
        fast.last().and_then(|item| item.price_usd)
    } else {
        None
    };
    let fast_return_pct = match (first_price, last_price) {
        (Some(first), Some(last)) if fast.len() >= 2 => Some(100.0 * (last / first - 1.0)),
        _ => None,
    };

    let fast_rate = fast.len() as f64 / FAST_WINDOW_SECONDS as f64;
    let baseline_duration = BASELINE_HORIZON_SECONDS - FAST_WINDOW_SECONDS;
    let baseline_rate = if baseline_count > 0 {
        Some(baseline_count as f64 / baseline_duration as f64)
    } else {
        None
    };
    let acceleration = baseline_rate.and_then(|rate| if rate > 0.0 { Some(fast_rate / rate) } else { None });

    let mut market_age = None;
    let mut quality = Vec::new();
    match lifecycle {
        Some(item) if item.observed_at > as_of => {
            quality.push("lifecycle_not_available_by_as_of".to_string());
        }
        Some(item) if item.market_started_at <= chain_as_of => {
            market_age = Some(chain_as_of - item.market_started_at);
        }
        Some(_) => quality.push("lifecycle_started_after_chain_as_of".to_string()),
        None => quality.push("lifecycle_missing".to_string()),
    }

    if !fast.is_empty() && wallet_rows < fast.len() {
        quality.push("partial_wallet_identity_coverage".to_string());
    }
    if !fast.is_empty() && transaction_rows == 0 {
        quality.push("transaction_identity_missing".to_string());
    } else if !fast.is_empty() && transaction_rows < fast.len() {
        quality.push("partial_transaction_identity_coverage".to_string());
    }
    if !fast.is_empty() && !notionals_complete {
        quality.push("partial_notional_coverage".to_string());
    }
    if !fast.is_empty() && !prices_complete {
        quality.push("partial_price_coverage".to_string());
    }
    if fast.is_empty() {
        quality.push("no_fast_window_events".to_string());
    }
    if baseline_count < MIN_BASELINE_EVENTS {
        quality.push("baseline_activity_insufficient".to_string());
    }
    if !fast.is_empty() {
        quality.push("observation_lag_unavailable_unaligned_clock_domains".to_string());
    }
    if fast.iter().any(|item| item.chain_time > item.observed_at) {
        quality.push("chain_clock_ahead_of_local_observation_clock_observed".to_string());
    }

    let features = Features {
        token_mint: token_mint.to_string(),
        as_of,
        chain_as_of,
        fast_window_seconds: FAST_WINDOW_SECONDS,
        baseline_horizon_seconds: BASELINE_HORIZON_SECONDS,
        fast_event_count: fast.len(),
        baseline_event_count: baseline_count,
        fast_buy_count: buys,
        fast_sell_count: sells,
        fast_unique_wallet_count: wallets.len(),
        fast_unique_transaction_count: unique_transaction_count,
        wallet_identity_coverage_pct: wallet_coverage,
        transaction_identity_coverage_pct: transaction_coverage,
        notional_coverage_pct: notional_coverage,
        price_coverage_pct: price_coverage,
        fast_event_rate_per_second: fast_rate,
        baseline_event_rate_per_second: baseline_rate,
        activity_acceleration_ratio: acceleration,
        signed_notional_imbalance_pct,
        count_imbalance_pct,
        direction: direction.clone(),
        first_price_usd: first_price,
        last_price_usd: last_price,
        fast_return_pct,
        median_observation_lag_seconds: None,
        max_observation_lag_seconds: None,
        venues: venues.into_iter().collect(),
        market_age_seconds: market_age,
        data_quality_flags: quality,
    };

    let transaction_breadth_ready = if transaction_coverage == Some(100.0) {
        unique_transaction_count
            .map(|count| count >= MIN_UNIQUE_TRANSACTIONS)
            .unwrap_or(false)
    } else {
        true
    };
    let fast_ready = fast.len() >= MIN_FAST_EVENTS;
    let breadth_ready = wallets.len() >= MIN_UNIQUE_WALLETS;
    let established_ready = fast_ready
        && breadth_ready
        && transaction_breadth_ready
        && baseline_count >= MIN_BASELINE_EVENTS
        && acceleration
            .map(|value| value >= MIN_ACTIVITY_ACCELERATION_RATIO)
            .unwrap_or(false);
    let fresh_ready = fast_ready
        && breadth_ready
        && transaction_breadth_ready
        && market_age
            .map(|age| age >= 0 && age <= FRESH_MARKET_MAX_AGE_SECONDS)
            .unwrap_or(false);

    let trigger_kind = if established_ready {
        "activity_acceleration"
    } else if fresh_ready {
        "fresh_market_burst"
    } else {
        return None;
    };

    Some(Trigger {
        token_mint: token_mint.to_string(),
        as_of,
        method_version: RADAR_VERSION.to_string(),
        trigger_kind: trigger_kind.to_string(),
        direction,
        features,
    })
}

fn invalid(message: impl Into<String>) -> Error {
    Error::new(ErrorKind::InvalidData, message.into())
}

fn parse_args() -> Result<(PathBuf, PathBuf), String> {
    let mut trace = None;
    let mut out = None;
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--trace" => trace = args.next().map(PathBuf::from),
            "--out" => out = args.next().map(PathBuf::from),
            other => return Err(format!("unsupported argument {other}")),
        }
    }
    Ok((
        trace.ok_or_else(|| "missing --trace".to_string())?,
        out.ok_or_else(|| "missing --out".to_string())?,
    ))
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let (trace_path, out_path) = parse_args().map_err(invalid)?;
    let reader = BufReader::new(File::open(&trace_path)?);
    let mut lines = reader.lines();

    let header_line = lines.next().ok_or_else(|| invalid("trace is empty"))??;
    let header: TraceHeader = serde_json::from_str(&header_line)?;
    if header.kind != "trace_header" {
        return Err(invalid("unsupported trace header").into());
    }

    let mut state = State::default();
    let mut decisions: Vec<Value> = Vec::new();
    let mut service_ns: Vec<u64> = Vec::with_capacity(header.record_count);
    let wall_started = Instant::now();
    let mut seen = 0usize;

    for line in lines {
        let raw = line?;
        if raw.trim().is_empty() {
            continue;
        }
        let record: RawRecord = serde_json::from_str(&raw)?;
        let started = Instant::now();
        let trigger = match record.kind.as_str() {
            "trade" => {
                let trade: Trade = serde_json::from_value(record.observation)?;
                state.ingest_trade(record.sequence, trade).map_err(invalid)?
            }
            "lifecycle" => {
                let lifecycle: Lifecycle = serde_json::from_value(record.observation)?;
                state.ingest_lifecycle(lifecycle);
                None
            }
            other => return Err(invalid(format!("unsupported record type {other}")).into()),
        };
        service_ns.push(started.elapsed().as_nanos().min(u64::MAX as u128) as u64);
        if record.kind == "trade" {
            decisions.push(json!({
                "sequence": record.sequence,
                "trigger": trigger,
            }));
        }
        seen += 1;
    }

    if seen != header.record_count {
        return Err(invalid(format!(
            "record_count mismatch: header={} seen={seen}",
            header.record_count
        ))
        .into());
    }

    let report = json!({
        "type": "rust_indexed_signal_plane_report",
        "version": VERSION,
        "trace_version": header.version,
        "record_count": seen,
        "trade_decision_points": decisions.len(),
        "late_chain_time_inserts": state.late_chain_time_inserts,
        "compactions": state.compactions,
        "wall_ns": wall_started.elapsed().as_nanos().min(u64::MAX as u128) as u64,
        "service_ns": service_ns,
        "decisions": decisions,
    });

    if let Some(parent) = out_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut writer = BufWriter::new(File::create(out_path)?);
    serde_json::to_writer(&mut writer, &report)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    Ok(())
}
