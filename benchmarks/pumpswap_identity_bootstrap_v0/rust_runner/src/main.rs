use anyhow::{Context, Result};
use base64::Engine as _;
use carbon_pump_swap_decoder::accounts::pool::Pool;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    env,
    fs::File,
    io::{BufRead, BufReader, BufWriter, Write},
    path::PathBuf,
};

const PUMPSWAP_PROGRAM_ID: &str = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA";
const RUNNER_VERSION: &str = "pumpswap_identity_bootstrap_v0_account_decoder";

#[derive(Debug, Deserialize)]
struct InputAccount {
    #[serde(rename = "type")]
    row_type: String,
    pool: String,
    owner: String,
    observed_slot: u64,
    observed_wall_ns: u64,
    evidence_key: String,
    data_base64: String,
}

fn parse_args() -> Result<(PathBuf, PathBuf)> {
    let mut args = env::args_os().skip(1);
    let input = args
        .next()
        .map(PathBuf::from)
        .context("usage: pumpswap-identity-bootstrap-v0-runner <input.jsonl> <output.jsonl>")?;
    let output = args
        .next()
        .map(PathBuf::from)
        .context("usage: pumpswap-identity-bootstrap-v0-runner <input.jsonl> <output.jsonl>")?;
    if args.next().is_some() {
        anyhow::bail!(
            "usage: pumpswap-identity-bootstrap-v0-runner <input.jsonl> <output.jsonl>"
        );
    }
    Ok((input, output))
}

fn decode_row(input: &InputAccount) -> Value {
    if input.row_type != "pumpswap_pool_account_input" {
        return json!({
            "type": "pumpswap_pool_identity_decode",
            "status": "INVALID_INPUT",
            "pool": input.pool,
            "error": "unsupported_row_type",
        });
    }
    if input.owner != PUMPSWAP_PROGRAM_ID {
        return json!({
            "type": "pumpswap_pool_identity_decode",
            "status": "OWNER_MISMATCH",
            "pool": input.pool,
            "owner": input.owner,
            "observed_slot": input.observed_slot,
            "observed_wall_ns": input.observed_wall_ns,
            "evidence_key": input.evidence_key,
        });
    }

    let payload = match base64::engine::general_purpose::STANDARD
        .decode(input.data_base64.as_bytes())
    {
        Ok(payload) => payload,
        Err(error) => {
            return json!({
                "type": "pumpswap_pool_identity_decode",
                "status": "DECODE_FAILED",
                "pool": input.pool,
                "observed_slot": input.observed_slot,
                "observed_wall_ns": input.observed_wall_ns,
                "evidence_key": input.evidence_key,
                "error": format!("invalid_base64:{error}"),
            })
        }
    };

    let Some(pool) = Pool::decode(&payload) else {
        return json!({
            "type": "pumpswap_pool_identity_decode",
            "status": "DECODE_FAILED",
            "pool": input.pool,
            "observed_slot": input.observed_slot,
            "observed_wall_ns": input.observed_wall_ns,
            "evidence_key": input.evidence_key,
            "error": "carbon_pool_account_decode_none",
        });
    };

    json!({
        "type": "pumpswap_pool_identity_decode",
        "status": "ADAPTED",
        "pool": input.pool,
        "base_mint": pool.base_mint.to_string(),
        "quote_mint": pool.quote_mint.to_string(),
        "observed_slot": input.observed_slot,
        "observed_wall_ns": input.observed_wall_ns,
        "evidence_key": input.evidence_key,
        "source": "helius_getMultipleAccounts_carbon_pool_v0",
    })
}

fn main() -> Result<()> {
    let (input_path, output_path) = parse_args()?;
    let input = File::open(&input_path)
        .with_context(|| format!("open input {}", input_path.display()))?;
    let output = File::create(&output_path)
        .with_context(|| format!("create output {}", output_path.display()))?;
    let reader = BufReader::new(input);
    let mut writer = BufWriter::new(output);

    let mut input_accounts = 0usize;
    let mut adapted = 0usize;
    let mut decode_failed = 0usize;
    let mut owner_mismatch = 0usize;
    let mut invalid_input = 0usize;

    for (line_number, line_result) in reader.lines().enumerate() {
        let line = line_result.with_context(|| format!("read line {}", line_number + 1))?;
        if line.trim().is_empty() {
            continue;
        }
        let input: InputAccount = serde_json::from_str(&line)
            .with_context(|| format!("parse input JSON line {}", line_number + 1))?;
        input_accounts += 1;
        let row = decode_row(&input);
        match row.get("status").and_then(Value::as_str) {
            Some("ADAPTED") => adapted += 1,
            Some("DECODE_FAILED") => decode_failed += 1,
            Some("OWNER_MISMATCH") => owner_mismatch += 1,
            _ => invalid_input += 1,
        }
        serde_json::to_writer(&mut writer, &row)?;
        writer.write_all(b"\n")?;
    }

    let footer = json!({
        "type": "pumpswap_pool_identity_decoder_footer",
        "version": RUNNER_VERSION,
        "input_accounts": input_accounts,
        "adapted": adapted,
        "decode_failed": decode_failed,
        "owner_mismatch": owner_mismatch,
        "invalid_input": invalid_input,
    });
    serde_json::to_writer(&mut writer, &footer)?;
    writer.write_all(b"\n")?;
    writer.flush()?;

    eprintln!(
        "PumpSwap identity decoder: input={} adapted={} decode_failed={} owner_mismatch={} invalid_input={}",
        input_accounts, adapted, decode_failed, owner_mismatch, invalid_input
    );
    Ok(())
}
