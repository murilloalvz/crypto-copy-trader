use anyhow::Result;
use serde::Deserialize;
use serde_json::{json, Value};
use std::io::{self, BufRead, BufWriter, Write};

#[allow(dead_code)]
mod frozen_decoder {
    include!("../main.rs");

    pub fn decode_value(value: Value) -> Result<Option<Value>> {
        let input: InputEvent = serde_json::from_value(value).context("parse batched stream input JSON")?;
        if input.row_type != "carbon_decoder_input" {
            return Ok(None);
        }

        let payload = match base64::engine::general_purpose::STANDARD
            .decode(input.payload_base64.as_bytes())
        {
            Ok(payload) => payload,
            Err(error) => {
                return Ok(Some(json!({
                    "type": "carbon_canonical_event",
                    "status": "decode_failed",
                    "event_key": input.event_key,
                    "signature": input.signature,
                    "slot": input.slot,
                    "log_index": input.log_index,
                    "program_id": input.program_id,
                    "event_type": input.event_type,
                    "error": format!("invalid_payload_base64:{error}"),
                })))
            }
        };

        Ok(Some(decode_event(&input, &payload)))
    }

    pub const fn decoder_version() -> &'static str {
        CARBON_DECODER_VERSION
    }

    pub const fn release_commit() -> &'static str {
        CARBON_RELEASE_COMMIT
    }
}

#[derive(Debug, Deserialize)]
struct InputBatch {
    #[serde(rename = "type")]
    row_type: String,
    batch_id: u64,
    items: Vec<Value>,
}

fn write_row(writer: &mut impl Write, row: &Value) -> Result<()> {
    serde_json::to_writer(&mut *writer, row)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    Ok(())
}

fn main() -> Result<()> {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut writer = BufWriter::new(stdout.lock());

    write_row(
        &mut writer,
        &json!({
            "type": "carbon_stream_decoder_ready",
            "carbon_decoder_version": frozen_decoder::decoder_version(),
            "carbon_release_commit": frozen_decoder::release_commit(),
            "transport": "ndjson_stdio_microbatch_v1",
        }),
    )?;

    let mut input_batches = 0usize;
    let mut input_events = 0usize;
    let mut decoded_events = 0usize;
    let mut decode_failures = 0usize;
    let mut input_errors = 0usize;

    for (line_number, line_result) in stdin.lock().lines().enumerate() {
        let line = match line_result {
            Ok(line) => line,
            Err(error) => {
                input_errors += 1;
                write_row(
                    &mut writer,
                    &json!({
                        "type": "carbon_stream_decoder_batch_error",
                        "line_number": line_number + 1,
                        "error": format!("read_line:{error}"),
                    }),
                )?;
                continue;
            }
        };
        if line.trim().is_empty() {
            continue;
        }

        let batch: InputBatch = match serde_json::from_str(&line) {
            Ok(batch) => batch,
            Err(error) => {
                input_errors += 1;
                write_row(
                    &mut writer,
                    &json!({
                        "type": "carbon_stream_decoder_batch_error",
                        "line_number": line_number + 1,
                        "error": format!("parse_batch:{error}"),
                    }),
                )?;
                continue;
            }
        };
        if batch.row_type != "carbon_decoder_batch" {
            input_errors += 1;
            write_row(
                &mut writer,
                &json!({
                    "type": "carbon_stream_decoder_batch_error",
                    "batch_id": batch.batch_id,
                    "error": "unsupported_batch_type",
                }),
            )?;
            continue;
        }

        input_batches += 1;
        input_events += batch.items.len();
        let mut output_items = Vec::with_capacity(batch.items.len());

        for item in batch.items {
            match frozen_decoder::decode_value(item) {
                Ok(Some(row)) => {
                    if row.get("status").and_then(Value::as_str) == Some("decoded") {
                        decoded_events += 1;
                    } else {
                        decode_failures += 1;
                    }
                    output_items.push(row);
                }
                Ok(None) => {
                    input_errors += 1;
                }
                Err(error) => {
                    input_errors += 1;
                    output_items.push(json!({
                        "type": "carbon_canonical_event",
                        "status": "decode_failed",
                        "error": error.to_string(),
                    }));
                }
            }
        }

        write_row(
            &mut writer,
            &json!({
                "type": "carbon_canonical_batch",
                "batch_id": batch.batch_id,
                "items": output_items,
            }),
        )?;
    }

    write_row(
        &mut writer,
        &json!({
            "type": "carbon_stream_decoder_footer",
            "carbon_decoder_version": frozen_decoder::decoder_version(),
            "carbon_release_commit": frozen_decoder::release_commit(),
            "input_batches": input_batches,
            "input_events": input_events,
            "decoded_events": decoded_events,
            "decode_failures": decode_failures,
            "input_errors": input_errors,
        }),
    )?;

    Ok(())
}
