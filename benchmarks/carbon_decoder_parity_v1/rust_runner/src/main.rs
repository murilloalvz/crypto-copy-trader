use anyhow::{Context, Result};
use base64::Engine as _;
use carbon_pump_swap_decoder::events::{
    buy_event::BuyEventEvent,
    create_pool_event::CreatePoolEventEvent,
    sell_event::SellEventEvent,
};
use carbon_pumpfun_decoder::events::{
    create_event::CreateEventEvent,
    trade_event::TradeEventEvent,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    env,
    fs::File,
    io::{BufRead, BufReader, BufWriter, Write},
    path::PathBuf,
};

const PUMP_PROGRAM_ID: &str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P";
const PUMPSWAP_PROGRAM_ID: &str = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA";
const CARBON_DECODER_VERSION: &str = "2.0.0";
const CARBON_RELEASE_COMMIT: &str = "e901103c93833c9c79407cb4321561e30796ad51";

#[derive(Debug, Deserialize)]
struct InputEvent {
    #[serde(rename = "type")]
    row_type: String,
    event_key: String,
    signature: String,
    slot: u64,
    log_index: usize,
    program_id: String,
    event_type: String,
    payload_base64: String,
}

fn base_row(input: &InputEvent) -> Value {
    json!({
        "type": "carbon_canonical_event",
        "status": "decoded",
        "event_key": input.event_key,
        "signature": input.signature,
        "slot": input.slot,
        "log_index": input.log_index,
        "program_id": input.program_id,
        "event_type": input.event_type,
    })
}

fn decode_event(input: &InputEvent, payload: &[u8]) -> Value {
    let expected_program = match input.event_type.as_str() {
        "pump_trade" | "pump_create" => PUMP_PROGRAM_ID,
        "pumpswap_buy" | "pumpswap_sell" | "pumpswap_create_pool" => PUMPSWAP_PROGRAM_ID,
        _ => {
            return json!({
                "type": "carbon_canonical_event",
                "status": "decode_failed",
                "event_key": input.event_key,
                "signature": input.signature,
                "slot": input.slot,
                "log_index": input.log_index,
                "program_id": input.program_id,
                "event_type": input.event_type,
                "error": "unsupported_event_type",
            })
        }
    };

    if input.program_id != expected_program {
        return json!({
            "type": "carbon_canonical_event",
            "status": "decode_failed",
            "event_key": input.event_key,
            "signature": input.signature,
            "slot": input.slot,
            "log_index": input.log_index,
            "program_id": input.program_id,
            "event_type": input.event_type,
            "error": "program_id_mismatch",
        });
    }

    let mut row = base_row(input);
    let object = row.as_object_mut().expect("base row must be object");

    match input.event_type.as_str() {
        "pump_trade" => {
            let Some(event) = TradeEventEvent::decode(payload) else {
                object.insert("status".into(), json!("decode_failed"));
                object.insert("error".into(), json!("carbon_trade_event_decode_none"));
                return row;
            };
            object.insert("mint".into(), json!(event.mint.to_string()));
            object.insert(
                "side".into(),
                json!(if event.is_buy { "buy" } else { "sell" }),
            );
            object.insert("wallet".into(), json!(event.user.to_string()));
            object.insert("timestamp".into(), json!(event.timestamp));
            object.insert("sol_amount_raw".into(), json!(event.sol_amount));
            object.insert("token_amount_raw".into(), json!(event.token_amount));
        }
        "pump_create" => {
            let Some(event) = CreateEventEvent::decode(payload) else {
                object.insert("status".into(), json!("decode_failed"));
                object.insert("error".into(), json!("carbon_create_event_decode_none"));
                return row;
            };
            object.insert("mint".into(), json!(event.mint.to_string()));
            object.insert(
                "bonding_curve".into(),
                json!(event.bonding_curve.to_string()),
            );
            object.insert("user".into(), json!(event.user.to_string()));
            object.insert("creator".into(), json!(event.creator.to_string()));
            object.insert("timestamp".into(), json!(event.timestamp));
        }
        "pumpswap_buy" => {
            let Some(event) = BuyEventEvent::decode(payload) else {
                object.insert("status".into(), json!("decode_failed"));
                object.insert("error".into(), json!("carbon_buy_event_decode_none"));
                return row;
            };
            object.insert("side".into(), json!("buy"));
            object.insert("pool".into(), json!(event.pool.to_string()));
            object.insert("user".into(), json!(event.user.to_string()));
            object.insert("timestamp".into(), json!(event.timestamp));
            object.insert("base_amount_raw".into(), json!(event.base_amount_out));
            object.insert("quote_amount_raw".into(), json!(event.quote_amount_in));
        }
        "pumpswap_sell" => {
            let Some(event) = SellEventEvent::decode(payload) else {
                object.insert("status".into(), json!("decode_failed"));
                object.insert("error".into(), json!("carbon_sell_event_decode_none"));
                return row;
            };
            object.insert("side".into(), json!("sell"));
            object.insert("pool".into(), json!(event.pool.to_string()));
            object.insert("user".into(), json!(event.user.to_string()));
            object.insert("timestamp".into(), json!(event.timestamp));
            object.insert("base_amount_raw".into(), json!(event.base_amount_in));
            object.insert("quote_amount_raw".into(), json!(event.quote_amount_out));
        }
        "pumpswap_create_pool" => {
            let Some(event) = CreatePoolEventEvent::decode(payload) else {
                object.insert("status".into(), json!("decode_failed"));
                object.insert(
                    "error".into(),
                    json!("carbon_create_pool_event_decode_none"),
                );
                return row;
            };
            object.insert("pool".into(), json!(event.pool.to_string()));
            object.insert("creator".into(), json!(event.creator.to_string()));
            object.insert("base_mint".into(), json!(event.base_mint.to_string()));
            object.insert("quote_mint".into(), json!(event.quote_mint.to_string()));
            object.insert(
                "base_mint_decimals".into(),
                json!(event.base_mint_decimals),
            );
            object.insert(
                "quote_mint_decimals".into(),
                json!(event.quote_mint_decimals),
            );
            object.insert("timestamp".into(), json!(event.timestamp));
        }
        _ => unreachable!("event type validated above"),
    }

    row
}

fn parse_args() -> Result<(PathBuf, PathBuf)> {
    let mut args = env::args_os().skip(1);
    let input = args
        .next()
        .map(PathBuf::from)
        .context("usage: carbon-decoder-parity-v1-runner <input.jsonl> <output.jsonl>")?;
    let output = args
        .next()
        .map(PathBuf::from)
        .context("usage: carbon-decoder-parity-v1-runner <input.jsonl> <output.jsonl>")?;
    if args.next().is_some() {
        anyhow::bail!(
            "usage: carbon-decoder-parity-v1-runner <input.jsonl> <output.jsonl>"
        );
    }
    Ok((input, output))
}

fn main() -> Result<()> {
    let (input_path, output_path) = parse_args()?;
    let input = File::open(&input_path)
        .with_context(|| format!("open input {}", input_path.display()))?;
    let output = File::create(&output_path)
        .with_context(|| format!("create output {}", output_path.display()))?;
    let reader = BufReader::new(input);
    let mut writer = BufWriter::new(output);

    let mut input_events = 0usize;
    let mut output_events = 0usize;
    let mut decode_failures = 0usize;

    for (line_number, line_result) in reader.lines().enumerate() {
        let line = line_result.with_context(|| format!("read line {}", line_number + 1))?;
        if line.trim().is_empty() {
            continue;
        }
        let input: InputEvent = serde_json::from_str(&line)
            .with_context(|| format!("parse input JSON line {}", line_number + 1))?;
        if input.row_type != "carbon_decoder_input" {
            continue;
        }
        input_events += 1;

        let payload = match base64::engine::general_purpose::STANDARD
            .decode(input.payload_base64.as_bytes())
        {
            Ok(payload) => payload,
            Err(error) => {
                let row = json!({
                    "type": "carbon_canonical_event",
                    "status": "decode_failed",
                    "event_key": input.event_key,
                    "signature": input.signature,
                    "slot": input.slot,
                    "log_index": input.log_index,
                    "program_id": input.program_id,
                    "event_type": input.event_type,
                    "error": format!("invalid_payload_base64:{error}"),
                });
                serde_json::to_writer(&mut writer, &row)?;
                writer.write_all(b"\n")?;
                output_events += 1;
                decode_failures += 1;
                continue;
            }
        };

        let row = decode_event(&input, &payload);
        if row.get("status").and_then(Value::as_str) != Some("decoded") {
            decode_failures += 1;
        }
        serde_json::to_writer(&mut writer, &row)?;
        writer.write_all(b"\n")?;
        output_events += 1;
    }

    let footer = json!({
        "type": "carbon_decoder_footer",
        "carbon_decoder_version": CARBON_DECODER_VERSION,
        "carbon_release_commit": CARBON_RELEASE_COMMIT,
        "input_events": input_events,
        "output_events": output_events,
        "decode_failures": decode_failures,
    });
    serde_json::to_writer(&mut writer, &footer)?;
    writer.write_all(b"\n")?;
    writer.flush()?;

    eprintln!(
        "Carbon decoder parity v1: input={} output={} decode_failures={} version={}",
        input_events, output_events, decode_failures, CARBON_DECODER_VERSION
    );
    Ok(())
}
