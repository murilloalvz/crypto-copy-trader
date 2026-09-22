use serde_json::{json, Value};
use std::io::{self, BufRead, BufWriter, Write};

mod frozen_kernel {
    use std::time::{SystemTime, UNIX_EPOCH};

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
            if row_type != "signal_record" {
                return Err("unsupported input type".to_string());
            }
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
                .cloned()
                .ok_or_else(|| "missing observation".to_string())?;
            let source_received_wall_ns = value
                .get("source_received_wall_ns")
                .and_then(Value::as_u64)
                .ok_or_else(|| "missing source_received_wall_ns".to_string())?;
            let canonical_ready_wall_ns = value
                .get("canonical_ready_wall_ns")
                .and_then(Value::as_u64)
                .ok_or_else(|| "missing canonical_ready_wall_ns".to_string())?;

            let started = Instant::now();
            let trigger = match kind {
                "trade" => {
                    let trade: Trade = serde_json::from_value(observation)
                        .map_err(|error| format!("parse_trade:{error}"))?;
                    self.state.ingest_trade(sequence, trade)?
                }
                "lifecycle" => {
                    let lifecycle: Lifecycle = serde_json::from_value(observation)
                        .map_err(|error| format!("parse_lifecycle:{error}"))?;
                    self.state.ingest_lifecycle(lifecycle);
                    None
                }
                other => return Err(format!("unsupported kind {other}")),
            };
            let service_ns = started.elapsed().as_nanos().min(u64::MAX as u128) as u64;
            let signal_ready_wall_ns = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|error| format!("system_time:{error}"))?
                .as_nanos()
                .min(u64::MAX as u128) as u64;

            Ok(json!({
                "type": "signal_result",
                "sequence": sequence,
                "kind": kind,
                "source_received_wall_ns": source_received_wall_ns,
                "canonical_ready_wall_ns": canonical_ready_wall_ns,
                "signal_ready_wall_ns": signal_ready_wall_ns,
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
            "transport": "ndjson_stdio_v0",
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
