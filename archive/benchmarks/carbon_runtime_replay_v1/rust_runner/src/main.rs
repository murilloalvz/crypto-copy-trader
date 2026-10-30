use async_trait::async_trait;
use carbon_core::{
    datasource::{BlockDetails, Datasource, DatasourceId, Update, UpdateType},
    error::CarbonResult,
    pipeline::{Pipeline, ShutdownStrategy},
    processor::Processor,
};
use serde_json::{json, Value};
use std::{
    env,
    sync::{
        atomic::{AtomicU64, AtomicUsize, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

const VERSION: &str = "carbon_runtime_replay_v1";
const CARBON_VERSION: &str = "2.0.0";
const CARBON_RELEASE_COMMIT: &str = "e901103c93833c9c79407cb4321561e30796ad51";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Mode {
    Inline,
    Handoff,
}

impl Mode {
    fn parse(value: &str) -> Result<Self, String> {
        match value {
            "inline" => Ok(Self::Inline),
            "handoff" => Ok(Self::Handoff),
            other => Err(format!("unsupported --mode {other:?}; expected inline|handoff")),
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::Inline => "inline",
            Self::Handoff => "handoff",
        }
    }
}

#[derive(Debug, Clone)]
struct Config {
    mode: Mode,
    events: usize,
    source_gap_us: u64,
    slow_every: usize,
    slow_ms: u64,
    carbon_channel: usize,
    handoff_buffer: usize,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            mode: Mode::Inline,
            events: 10_000,
            source_gap_us: 200,
            slow_every: 0,
            slow_ms: 0,
            carbon_channel: 256,
            handoff_buffer: 1024,
        }
    }
}

fn parse_usize(name: &str, value: Option<String>) -> Result<usize, String> {
    value
        .ok_or_else(|| format!("missing value for {name}"))?
        .parse::<usize>()
        .map_err(|e| format!("invalid {name}: {e}"))
}

fn parse_u64(name: &str, value: Option<String>) -> Result<u64, String> {
    value
        .ok_or_else(|| format!("missing value for {name}"))?
        .parse::<u64>()
        .map_err(|e| format!("invalid {name}: {e}"))
}

fn parse_args() -> Result<Config, String> {
    let mut cfg = Config::default();
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--mode" => {
                cfg.mode = Mode::parse(
                    &args
                        .next()
                        .ok_or_else(|| "missing value for --mode".to_string())?,
                )?;
            }
            "--events" => cfg.events = parse_usize("--events", args.next())?,
            "--source-gap-us" => cfg.source_gap_us = parse_u64("--source-gap-us", args.next())?,
            "--slow-every" => cfg.slow_every = parse_usize("--slow-every", args.next())?,
            "--slow-ms" => cfg.slow_ms = parse_u64("--slow-ms", args.next())?,
            "--carbon-channel" => {
                cfg.carbon_channel = parse_usize("--carbon-channel", args.next())?
            }
            "--handoff-buffer" => {
                cfg.handoff_buffer = parse_usize("--handoff-buffer", args.next())?
            }
            "-h" | "--help" => {
                return Err(
                    "usage: carbon-runtime-replay-v1 --mode inline|handoff \
                     [--events N] [--source-gap-us N] [--slow-every N] [--slow-ms N] \
                     [--carbon-channel N] [--handoff-buffer N]"
                        .to_string(),
                );
            }
            other => return Err(format!("unknown argument: {other}")),
        }
    }

    if cfg.events == 0 {
        return Err("--events must be > 0".to_string());
    }
    if cfg.carbon_channel == 0 {
        return Err("--carbon-channel must be > 0".to_string());
    }
    if cfg.handoff_buffer == 0 {
        return Err("--handoff-buffer must be > 0".to_string());
    }
    Ok(cfg)
}

fn max_atomic(target: &AtomicUsize, candidate: usize) {
    let mut current = target.load(Ordering::Relaxed);
    while candidate > current {
        match target.compare_exchange_weak(
            current,
            candidate,
            Ordering::Relaxed,
            Ordering::Relaxed,
        ) {
            Ok(_) => break,
            Err(actual) => current = actual,
        }
    }
}

fn elapsed_ns(start: Instant) -> u64 {
    start.elapsed().as_nanos().min(u64::MAX as u128) as u64
}

struct Shared {
    start: Instant,
    ready_ns: Vec<AtomicU64>,
    send_block_ns: Vec<AtomicU64>,
    process_start_ns: Vec<AtomicU64>,
    process_end_ns: Vec<AtomicU64>,
    worker_end_ns: Vec<AtomicU64>,
    processed_order: Mutex<Vec<usize>>,
    worker_order: Mutex<Vec<usize>>,
    source_sent: AtomicUsize,
    pipeline_current: AtomicUsize,
    pipeline_high_water: AtomicUsize,
    handoff_enqueued: AtomicUsize,
    handoff_dropped: AtomicUsize,
    downstream_current: AtomicUsize,
    downstream_high_water: AtomicUsize,
    worker_completed: AtomicUsize,
    source_finished_ns: AtomicU64,
}

impl Shared {
    fn new(events: usize) -> Self {
        let atomics = || {
            (0..events)
                .map(|_| AtomicU64::new(0))
                .collect::<Vec<AtomicU64>>()
        };
        Self {
            start: Instant::now(),
            ready_ns: atomics(),
            send_block_ns: atomics(),
            process_start_ns: atomics(),
            process_end_ns: atomics(),
            worker_end_ns: atomics(),
            processed_order: Mutex::new(Vec::with_capacity(events)),
            worker_order: Mutex::new(Vec::with_capacity(events)),
            source_sent: AtomicUsize::new(0),
            pipeline_current: AtomicUsize::new(0),
            pipeline_high_water: AtomicUsize::new(0),
            handoff_enqueued: AtomicUsize::new(0),
            handoff_dropped: AtomicUsize::new(0),
            downstream_current: AtomicUsize::new(0),
            downstream_high_water: AtomicUsize::new(0),
            worker_completed: AtomicUsize::new(0),
            source_finished_ns: AtomicU64::new(0),
        }
    }

    fn mark_ready(&self, seq: usize) {
        self.ready_ns[seq].store(elapsed_ns(self.start).saturating_add(1), Ordering::Relaxed);
        let outstanding = self.pipeline_current.fetch_add(1, Ordering::Relaxed) + 1;
        max_atomic(&self.pipeline_high_water, outstanding);
    }

    fn cancel_ready(&self) {
        self.pipeline_current.fetch_sub(1, Ordering::Relaxed);
    }

    fn mark_processed(&self, seq: usize, started_ns: u64, ended_ns: u64) {
        self.process_start_ns[seq].store(started_ns.saturating_add(1), Ordering::Relaxed);
        self.process_end_ns[seq].store(ended_ns.saturating_add(1), Ordering::Relaxed);
        self.processed_order.lock().unwrap().push(seq);
        self.pipeline_current.fetch_sub(1, Ordering::Relaxed);
    }

    fn mark_handoff_enqueued(&self) {
        self.handoff_enqueued.fetch_add(1, Ordering::Relaxed);
        let outstanding = self.downstream_current.fetch_add(1, Ordering::Relaxed) + 1;
        max_atomic(&self.downstream_high_water, outstanding);
    }

    fn mark_handoff_dropped(&self) {
        self.handoff_dropped.fetch_add(1, Ordering::Relaxed);
    }

    fn mark_worker_done(&self, seq: usize) {
        self.worker_end_ns[seq].store(elapsed_ns(self.start).saturating_add(1), Ordering::Relaxed);
        self.worker_order.lock().unwrap().push(seq);
        self.worker_completed.fetch_add(1, Ordering::Relaxed);
        self.downstream_current.fetch_sub(1, Ordering::Relaxed);
    }
}

#[derive(Clone)]
struct ReplayDatasource {
    cfg: Config,
    shared: Arc<Shared>,
}

#[async_trait]
impl Datasource for ReplayDatasource {
    async fn consume(
        &self,
        id: DatasourceId,
        sender: mpsc::Sender<(Update, DatasourceId)>,
        cancellation_token: CancellationToken,
    ) -> CarbonResult<()> {
        for seq in 0..self.cfg.events {
            if cancellation_token.is_cancelled() {
                break;
            }

            if self.cfg.source_gap_us > 0 {
                let target_offset =
                    Duration::from_micros(self.cfg.source_gap_us.saturating_mul(seq as u64));
                let elapsed = self.shared.start.elapsed();
                if target_offset > elapsed {
                    tokio::time::sleep(target_offset - elapsed).await;
                }
            }

            self.shared.mark_ready(seq);
            let send_started = Instant::now();
            let update = Update::BlockDetails(BlockDetails {
                slot: seq as u64,
                block_hash: None,
                previous_block_hash: None,
                rewards: None,
                num_reward_partitions: None,
                block_time: None,
                block_height: None,
            });
            if sender.send((update, id.clone())).await.is_err() {
                self.shared.cancel_ready();
                break;
            }
            let blocked_ns = send_started.elapsed().as_nanos().min(u64::MAX as u128) as u64;
            self.shared.send_block_ns[seq]
                .store(blocked_ns.saturating_add(1), Ordering::Relaxed);
            self.shared.source_sent.fetch_add(1, Ordering::Relaxed);
        }

        self.shared
            .source_finished_ns
            .store(elapsed_ns(self.shared.start).saturating_add(1), Ordering::Relaxed);
        Ok(())
    }

    fn update_types(&self) -> Vec<UpdateType> {
        vec![UpdateType::BlockDetails]
    }
}

fn is_slow(seq: usize, slow_every: usize) -> bool {
    slow_every > 0 && seq > 0 && seq % slow_every == 0
}

struct InlineProcessor {
    shared: Arc<Shared>,
    slow_every: usize,
    slow_ms: u64,
}

impl Processor<BlockDetails> for InlineProcessor {
    fn process(&mut self, data: &BlockDetails) -> impl std::future::Future<Output = CarbonResult<()>> + Send {
        let seq = data.slot as usize;
        let shared = Arc::clone(&self.shared);
        let slow_every = self.slow_every;
        let slow_ms = self.slow_ms;
        async move {
            let started_ns = elapsed_ns(shared.start);
            if is_slow(seq, slow_every) && slow_ms > 0 {
                tokio::time::sleep(Duration::from_millis(slow_ms)).await;
            }
            let ended_ns = elapsed_ns(shared.start);
            shared.mark_processed(seq, started_ns, ended_ns);
            Ok(())
        }
    }
}

struct HandoffProcessor {
    shared: Arc<Shared>,
    sender: mpsc::Sender<usize>,
}

impl Processor<BlockDetails> for HandoffProcessor {
    fn process(&mut self, data: &BlockDetails) -> impl std::future::Future<Output = CarbonResult<()>> + Send {
        let seq = data.slot as usize;
        let shared = Arc::clone(&self.shared);
        let sender = self.sender.clone();
        async move {
            let started_ns = elapsed_ns(shared.start);
            match sender.try_send(seq) {
                Ok(()) => shared.mark_handoff_enqueued(),
                Err(_) => shared.mark_handoff_dropped(),
            }
            let ended_ns = elapsed_ns(shared.start);
            shared.mark_processed(seq, started_ns, ended_ns);
            Ok(())
        }
    }
}

fn read_atomic(value: &AtomicU64) -> Option<u64> {
    match value.load(Ordering::Relaxed) {
        0 => None,
        n => Some(n - 1),
    }
}

fn percentile_ms(values_ns: &[u64], pct: f64) -> Option<f64> {
    if values_ns.is_empty() {
        return None;
    }
    let mut values = values_ns.to_vec();
    values.sort_unstable();
    if values.len() == 1 {
        return Some(values[0] as f64 / 1_000_000.0);
    }
    let rank = (values.len() - 1) as f64 * pct / 100.0;
    let lo = rank.floor() as usize;
    let hi = rank.ceil() as usize;
    let weight = rank - lo as f64;
    let interpolated = values[lo] as f64 * (1.0 - weight) + values[hi] as f64 * weight;
    Some(interpolated / 1_000_000.0)
}

fn metric_triplet(values_ns: &[u64]) -> Value {
    json!({
        "count": values_ns.len(),
        "p50_ms": percentile_ms(values_ns, 50.0),
        "p95_ms": percentile_ms(values_ns, 95.0),
        "p99_ms": percentile_ms(values_ns, 99.0),
        "max_ms": values_ns.iter().copied().max().map(|x| x as f64 / 1_000_000.0),
    })
}

fn order_violations(order: &[usize]) -> usize {
    order.windows(2).filter(|pair| pair[0] >= pair[1]).count()
}

fn build_report(cfg: &Config, shared: &Shared) -> Value {
    let mut send_block = Vec::new();
    let mut queue_wait = Vec::new();
    let mut pipeline_e2e = Vec::new();
    let mut downstream_e2e = Vec::new();
    let mut bystander_after_slow = Vec::new();

    for seq in 0..cfg.events {
        if let Some(value) = read_atomic(&shared.send_block_ns[seq]) {
            send_block.push(value);
        }
        let ready = read_atomic(&shared.ready_ns[seq]);
        let process_start = read_atomic(&shared.process_start_ns[seq]);
        let process_end = read_atomic(&shared.process_end_ns[seq]);
        let worker_end = read_atomic(&shared.worker_end_ns[seq]);

        if let (Some(ready), Some(started)) = (ready, process_start) {
            queue_wait.push(started.saturating_sub(ready));
        }
        if let (Some(ready), Some(ended)) = (ready, process_end) {
            pipeline_e2e.push(ended.saturating_sub(ready));
            if seq > 0 && is_slow(seq - 1, cfg.slow_every) {
                bystander_after_slow.push(ended.saturating_sub(ready));
            }
        }
        if let (Some(ready), Some(ended)) = (ready, worker_end) {
            downstream_e2e.push(ended.saturating_sub(ready));
        }
    }

    let processed_order = shared.processed_order.lock().unwrap().clone();
    let worker_order = shared.worker_order.lock().unwrap().clone();
    let source_finished_ns = read_atomic(&shared.source_finished_ns).unwrap_or(0);
    let pipeline_finished_ns = shared
        .process_end_ns
        .iter()
        .filter_map(read_atomic)
        .max()
        .unwrap_or(0);
    let worker_finished_ns = shared
        .worker_end_ns
        .iter()
        .filter_map(read_atomic)
        .max()
        .unwrap_or(0);

    let processed = processed_order.len();
    let worker_completed = shared.worker_completed.load(Ordering::Relaxed);
    let pipeline_seconds = pipeline_finished_ns as f64 / 1_000_000_000.0;
    let worker_seconds = worker_finished_ns as f64 / 1_000_000_000.0;

    json!({
        "type": "carbon_runtime_replay_result",
        "version": VERSION,
        "carbon_version": CARBON_VERSION,
        "carbon_release_commit": CARBON_RELEASE_COMMIT,
        "mode": cfg.mode.as_str(),
        "config": {
            "events": cfg.events,
            "source_gap_us": cfg.source_gap_us,
            "slow_every": cfg.slow_every,
            "slow_ms": cfg.slow_ms,
            "carbon_channel": cfg.carbon_channel,
            "handoff_buffer": cfg.handoff_buffer,
        },
        "counts": {
            "source_sent": shared.source_sent.load(Ordering::Relaxed),
            "pipeline_processed": processed,
            "handoff_enqueued": shared.handoff_enqueued.load(Ordering::Relaxed),
            "handoff_dropped": shared.handoff_dropped.load(Ordering::Relaxed),
            "worker_completed": worker_completed,
        },
        "correctness": {
            "pipeline_order_violations": order_violations(&processed_order),
            "worker_order_violations": order_violations(&worker_order),
            "pipeline_current_at_end": shared.pipeline_current.load(Ordering::Relaxed),
            "downstream_current_at_end": shared.downstream_current.load(Ordering::Relaxed),
        },
        "pressure": {
            "pipeline_outstanding_high_water": shared.pipeline_high_water.load(Ordering::Relaxed),
            "downstream_outstanding_high_water": shared.downstream_high_water.load(Ordering::Relaxed),
        },
        "timing": {
            "source_finished_ms": source_finished_ns as f64 / 1_000_000.0,
            "pipeline_finished_ms": pipeline_finished_ns as f64 / 1_000_000.0,
            "worker_finished_ms": worker_finished_ns as f64 / 1_000_000.0,
            "pipeline_throughput_eps": if pipeline_seconds > 0.0 { processed as f64 / pipeline_seconds } else { 0.0 },
            "worker_throughput_eps": if worker_seconds > 0.0 { worker_completed as f64 / worker_seconds } else { 0.0 },
            "source_send_block": metric_triplet(&send_block),
            "pipeline_queue_wait": metric_triplet(&queue_wait),
            "pipeline_e2e": metric_triplet(&pipeline_e2e),
            "bystander_after_slow": metric_triplet(&bystander_after_slow),
            "downstream_e2e": metric_triplet(&downstream_e2e),
        }
    })
}

async fn run(cfg: Config) -> CarbonResult<Value> {
    let shared = Arc::new(Shared::new(cfg.events));
    let datasource = ReplayDatasource {
        cfg: cfg.clone(),
        shared: Arc::clone(&shared),
    };

    if cfg.mode == Mode::Inline {
        let processor = InlineProcessor {
            shared: Arc::clone(&shared),
            slow_every: cfg.slow_every,
            slow_ms: cfg.slow_ms,
        };
        let mut pipeline = Pipeline::builder()
            .datasource(datasource)
            .block_details(processor)
            .channel_buffer_size(cfg.carbon_channel)
            .shutdown_strategy(ShutdownStrategy::ProcessPending)
            .build()?;
        pipeline.run().await?;
        drop(pipeline);
    } else {
        let (handoff_tx, mut handoff_rx) = mpsc::channel::<usize>(cfg.handoff_buffer);
        let worker_shared = Arc::clone(&shared);
        let slow_every = cfg.slow_every;
        let slow_ms = cfg.slow_ms;
        let worker = tokio::spawn(async move {
            while let Some(seq) = handoff_rx.recv().await {
                if is_slow(seq, slow_every) && slow_ms > 0 {
                    tokio::time::sleep(Duration::from_millis(slow_ms)).await;
                }
                worker_shared.mark_worker_done(seq);
            }
        });

        let processor = HandoffProcessor {
            shared: Arc::clone(&shared),
            sender: handoff_tx,
        };
        let mut pipeline = Pipeline::builder()
            .datasource(datasource)
            .block_details(processor)
            .channel_buffer_size(cfg.carbon_channel)
            .shutdown_strategy(ShutdownStrategy::ProcessPending)
            .build()?;
        pipeline.run().await?;
        drop(pipeline);
        let _ = worker.await;
    }

    Ok(build_report(&cfg, &shared))
}

#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() {
    let cfg = match parse_args() {
        Ok(cfg) => cfg,
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(2);
        }
    };

    match run(cfg).await {
        Ok(report) => println!("{}", serde_json::to_string(&report).unwrap()),
        Err(error) => {
            eprintln!("carbon runtime replay failed: {error:?}");
            std::process::exit(1);
        }
    }
}
