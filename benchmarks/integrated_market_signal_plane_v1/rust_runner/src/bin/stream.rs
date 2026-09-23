use serde_json::{json, Value};
use std::io::{self, BufRead, BufWriter, Write};

mod frozen_kernel {
    include!("../main.rs");

    pub struct StreamKernel {
        state: State,
    }

    impl StreamKernel {
        pub fn new() -> Self {
            Self {
                state: State::default(),
            }
        }

        pub fn process(&mut self, value: Value) -> Result<Value, String> {
            let row_type = value
                .get("type")
                .and_then(Value::as_str)
                .ok_or_else(|| "missing type".to_string())?;
            if row_type == "signal_batch" {
                let batch_id = value
                    .get("batch_id")
                    .and_then(Value::as_u64)
                    .ok_or_else(|| "missing batch_id".to_string())?;
                let records = value
                    .get("records")
                    .and_then(Value::as_array)
                    .ok_or_else(|| "missing records".to_string())?;
                let batch_started = Instant::now();
                let mut results: Vec<Value> = Vec::with_capacity(records.len());
                for record in records {
                    if !record.is_object() {
                        return Err("batch record must be object".to_string());
                    }
                    results.push(self.process_signal_record(record)?);
                }
                let batch_service_ns = batch_started
                    .elapsed()
                    .as_nanos()
                    .min(u64::MAX as u128) as u64;
                return Ok(json!({
                    "type": "signal_batch_result",
                    "batch_id": batch_id,
                    "count": results.len(),
                    "batch_service_ns": batch_service_ns,
                    "results": results,
                }));
            }
            if row_type != "signal_record" {
                return Err(format!("unsupported input type {row_type}"));
            }
            self.process_signal_record(&value)
        }

        fn process_signal_record(&mut self, value: &Value) -> Result<Value, String> {
            let sequence = value
                .get("sequence")
                .and_then(Value::as_u64)
                .ok_or_else(|| "missing sequence".to_string())? as usize;
            let kind = value
                .get("kind")
                .and_then(Value::as_str)
                .ok_or_else(|| "missing kind".to_string())?;
            let observation = value
                .get("observation")
                .ok_or_else(|| "missing observation".to_string())?;
            let _source_received_wall_ns = value
                .get("source_received_wall_ns")
                .and_then(Value::as_u64)
                .ok_or_else(|| "missing source_received_wall_ns".to_string())?;
            let _canonical_ready_wall_ns = value
                .get("canonical_ready_wall_ns")
                .and_then(Value::as_u64)
                .ok_or_else(|| "missing canonical_ready_wall_ns".to_string())?;

            let started = Instant::now();
            let trigger = match kind {
                "trade" => {
                    let trade: Trade = Trade::deserialize(observation)
                        .map_err(|error| format!("parse_trade:{error}"))?;
                    self.state.ingest_trade(sequence, trade)?
                }
                "lifecycle" => {
                    let lifecycle: Lifecycle = Lifecycle::deserialize(observation)
                        .map_err(|error| format!("parse_lifecycle:{error}"))?;
                    self.state.ingest_lifecycle(lifecycle);
                    None
                }
                other => return Err(format!("unsupported kind {other}")),
            };
            let service_ns = started.elapsed().as_nanos().min(u64::MAX as u128) as u64;

            Ok(json!({
                "type": "signal_result",
                "sequence": sequence,
                "service_ns": service_ns,
                "trigger": trigger,
                "late_chain_time_inserts": self.state.late_chain_time_inserts,
            }))
        }
    }

    pub fn version() -> &'static str {
        VERSION
    }
}

fn write_row(writer: &mut impl Write, row: &Value) -> Result<(), Box<dyn std::error::Error>> {
    serde_json::to_writer(&mut *writer, row)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut writer = BufWriter::new(stdout.lock());
    let mut kernel = frozen_kernel::StreamKernel::new();

    write_row(
        &mut writer,
        &json!({
            "type": "rust_signal_stream_ready",
            "version": frozen_kernel::version(),
            "transport": "ndjson_stdio_v1_signal_batch",
        }),
    )?;

    for (line_number, line_result) in stdin.lock().lines().enumerate() {
        let line = line_result?;
        if line.trim().is_empty() {
            continue;
        }
        let input: Value = match serde_json::from_str(&line) {
            Ok(value) => value,
            Err(error) => {
                write_row(
                    &mut writer,
                    &json!({
                        "type": "signal_error",
                        "line_number": line_number + 1,
                        "error": format!("parse_json:{error}"),
                    }),
                )?;
                continue;
            }
        };
        match kernel.process(input) {
            Ok(result) => write_row(&mut writer, &result)?,
            Err(error) => write_row(
                &mut writer,
                &json!({
                    "type": "signal_error",
                    "line_number": line_number + 1,
                    "error": error,
                }),
            )?,
        }
    }
    Ok(())
}


#[cfg(test)]
mod tests {
    use super::*;

    fn lifecycle_record(sequence: u64, observed_at: i64) -> Value {
        json!({
            "type": "signal_record",
            "sequence": sequence,
            "kind": "lifecycle",
            "source_received_wall_ns": 1_000_000_000u64 + sequence,
            "canonical_ready_wall_ns": 1_000_100_000u64 + sequence,
            "observation": {
                "token_mint": "TOKEN",
                "market_started_at": 100i64,
                "observed_at": observed_at,
                "venue": "pump"
            }
        })
    }

    fn trade_record_with_observed(
        sequence: u64,
        side: &str,
        chain_time: i64,
        observed_at: i64,
    ) -> Value {
        json!({
            "type": "signal_record",
            "sequence": sequence,
            "kind": "trade",
            "source_received_wall_ns": 2_000_000_000u64 + sequence,
            "canonical_ready_wall_ns": 2_000_100_000u64 + sequence,
            "observation": {
                "token_mint": "TOKEN",
                "side": side,
                "chain_time": chain_time,
                "observed_at": observed_at,
                "wallet_address": format!("wallet-{sequence}"),
                "notional_usd": 10.0,
                "price_usd": 1.0 + (sequence as f64 * 0.01),
                "venue": "pump",
                "transaction_key": format!("tx-{sequence}")
            }
        })
    }

    fn trade_record(sequence: u64, side: &str, chain_time: i64) -> Value {
        trade_record_with_observed(sequence, side, chain_time, chain_time)
    }

    #[test]
    fn signal_batch_preserves_sequential_kernel_semantics() {
        let records = vec![
            lifecycle_record(0, 100),
            trade_record(1, "buy", 101),
            trade_record(2, "buy", 102),
            trade_record(3, "sell", 103),
            trade_record(4, "buy", 104),
            trade_record(5, "buy", 105),
            trade_record(6, "buy", 106),
        ];

        let mut sequential = frozen_kernel::StreamKernel::new();
        let sequential_rows: Vec<Value> = records
            .iter()
            .cloned()
            .map(|row| sequential.process(row).expect("sequential process"))
            .collect();

        let mut batched = frozen_kernel::StreamKernel::new();
        let batch = batched
            .process(json!({
                "type": "signal_batch",
                "batch_id": 42u64,
                "records": records,
            }))
            .expect("batch process");

        assert_eq!(batch["type"], "signal_batch_result");
        assert_eq!(batch["batch_id"], 42u64);
        assert_eq!(batch["count"], sequential_rows.len());
        let batch_rows = batch["results"].as_array().expect("results array");
        assert_eq!(batch_rows.len(), sequential_rows.len());

        for (left, right) in sequential_rows.iter().zip(batch_rows.iter()) {
            assert_eq!(left["sequence"], right["sequence"]);
            assert_eq!(left["trigger"], right["trigger"]);
            assert_eq!(
                left["late_chain_time_inserts"],
                right["late_chain_time_inserts"]
            );
        }
    }

    #[test]
    fn non_trigger_path_short_circuits_before_min_fast_events() {
        let mut kernel = frozen_kernel::StreamKernel::new();
        kernel
            .process(lifecycle_record(0, 100))
            .expect("lifecycle process");

        for sequence in 1..=5u64 {
            let row = kernel
                .process(trade_record(sequence, "buy", 100 + sequence as i64))
                .expect("trade process");
            assert!(row["trigger"].is_null());
        }
    }

    #[test]
    fn fresh_market_trigger_preserves_full_feature_shape() {
        let mut kernel = frozen_kernel::StreamKernel::new();
        kernel
            .process(lifecycle_record(0, 100))
            .expect("lifecycle process");

        let sides = ["buy", "buy", "sell", "buy", "buy", "buy"];
        let mut final_row = Value::Null;
        for (index, side) in sides.iter().enumerate() {
            let sequence = index as u64 + 1;
            final_row = kernel
                .process(trade_record(sequence, side, 100 + sequence as i64))
                .expect("trade process");
        }

        let trigger = &final_row["trigger"];
        assert_eq!(trigger["trigger_kind"], "fresh_market_burst");
        assert_eq!(trigger["direction"], "upward_pressure");
        assert_eq!(trigger["features"]["fast_event_count"], json!(6));
        assert_eq!(trigger["features"]["baseline_event_count"], json!(0));
        assert_eq!(trigger["features"]["fast_buy_count"], json!(5));
        assert_eq!(trigger["features"]["fast_sell_count"], json!(1));
        assert_eq!(trigger["features"]["fast_unique_wallet_count"], json!(6));
        assert_eq!(trigger["features"]["fast_unique_transaction_count"], json!(6));
        assert_eq!(trigger["features"]["market_age_seconds"], json!(6));
        assert_eq!(
            trigger["features"]["data_quality_flags"],
            json!([
                "baseline_activity_insufficient",
                "observation_lag_unavailable_unaligned_clock_domains"
            ])
        );
    }

    #[test]
    fn established_trigger_preserves_activity_acceleration_semantics() {
        let mut kernel = frozen_kernel::StreamKernel::new();

        for (sequence, chain_time) in [(1u64, 100i64), (2, 101), (3, 102)] {
            let row = kernel
                .process(trade_record(sequence, "buy", chain_time))
                .expect("baseline trade");
            assert!(row["trigger"].is_null());
        }

        let mut final_row = Value::Null;
        for offset in 0..6u64 {
            let sequence = 4 + offset;
            final_row = kernel
                .process(trade_record(sequence, "buy", 350 + offset as i64))
                .expect("fast trade");
        }

        let trigger = &final_row["trigger"];
        assert_eq!(trigger["trigger_kind"], "activity_acceleration");
        assert_eq!(trigger["features"]["fast_event_count"], json!(6));
        assert_eq!(trigger["features"]["baseline_event_count"], json!(3));
        assert_eq!(trigger["features"]["fast_unique_wallet_count"], json!(6));
        assert_eq!(trigger["features"]["fast_unique_transaction_count"], json!(6));
        assert_eq!(
            trigger["features"]["data_quality_flags"],
            json!([
                "lifecycle_missing",
                "observation_lag_unavailable_unaligned_clock_domains"
            ])
        );
    }

    #[test]
    fn late_chain_insert_accounting_is_unchanged() {
        let mut kernel = frozen_kernel::StreamKernel::new();

        kernel
            .process(trade_record_with_observed(1, "buy", 100, 100))
            .expect("first trade");
        kernel
            .process(trade_record_with_observed(2, "buy", 102, 102))
            .expect("second trade");
        let late = kernel
            .process(trade_record_with_observed(3, "buy", 101, 103))
            .expect("late chain trade");

        assert_eq!(late["late_chain_time_inserts"], json!(1));
        assert!(late["trigger"].is_null());
    }

}
