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
const CARBON_DECODER_VERSION: &str = "2.0.0";

#[derive(Debug, Deserialize)]
struct InputAccount {
    #[serde(rename = "type")]
    row_type: String,
    pool: String,
    owner: String,
    data_base64: String,
    rpc_context_slot: u64,
    received_wall_ns: u64,
}

fn parse_args() -> Result<(PathBuf, PathBuf)> {
    let mut args = env::args_os().skip(1);
    let input = args
        .next()
        .map(PathBuf::from)
        .context("usage: decode-pumpswap-pool-accounts <input.jsonl> <output.jsonl>")?;
    let output = args
        .next()
        .map(PathBuf::from)
        .context("usage: decode-pumpswap-pool-accounts <input.jsonl> <output.jsonl>")?;
    if args.next().is_some() {
        anyhow::bail!("usage: decode-pumpswap-pool-accounts <input.jsonl> <output.jsonl>");
    }
    Ok((input, output))
}

fn failed(input: &InputAccount, error: &str) -> Value {
    json!({
        "type": "carbon_pumpswap_pool_account",
        "status": "decode_failed",
        "pool": input.pool,
        "owner": input.owner,
        "rpc_context_slot": input.rpc_context_slot,
        "received_wall_ns": input.received_wall_ns,
        "error": error,
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
    let mut decoded_accounts = 0usize;
    let mut decode_failures = 0usize;

    for (line_number, line_result) in reader.lines().enumerate() {
        let line = line_result.with_context(|| format!("read line {}", line_number + 1))?;
        if line.trim().is_empty() {
            continue;
        }
        let input: InputAccount = serde_json::from_str(&line)
            .with_context(|| format!("parse input JSON line {}", line_number + 1))?;
        if input.row_type != "pumpswap_pool_account_probe" {
            continue;
        }
        input_accounts += 1;

        let row = if input.owner != PUMPSWAP_PROGRAM_ID {
            decode_failures += 1;
            failed(&input, "owner_mismatch")
        } else {
            match base64::engine::general_purpose::STANDARD.decode(input.data_base64.as_bytes()) {
                Err(error) => {
                    decode_failures += 1;
                    failed(&input, &format!("invalid_base64:{error}"))
                }
                Ok(data) => match Pool::decode(&data) {
                    None => {
                        decode_failures += 1;
                        failed(&input, "carbon_pool_decode_none")
                    }
                    Some(pool) => {
                        decoded_accounts += 1;
                        json!({
                            "type": "carbon_pumpswap_pool_account",
                            "status": "decoded",
                            "pool": input.pool,
                            "owner": input.owner,
                            "rpc_context_slot": input.rpc_context_slot,
                            "received_wall_ns": input.received_wall_ns,
                            "base_mint": pool.base_mint.to_string(),
                            "quote_mint": pool.quote_mint.to_string(),
                            "carbon_decoder_version": CARBON_DECODER_VERSION,
                        })
                    }
                },
            }
        };

        serde_json::to_writer(&mut writer, &row)?;
        writer.write_all(b"\n")?;
    }

    let footer = json!({
        "type": "carbon_pumpswap_pool_account_footer",
        "carbon_decoder_version": CARBON_DECODER_VERSION,
        "input_accounts": input_accounts,
        "decoded_accounts": decoded_accounts,
        "decode_failures": decode_failures,
    });
    serde_json::to_writer(&mut writer, &footer)?;
    writer.write_all(b"\n")?;
    writer.flush()?;

    eprintln!(
        "Carbon PumpSwap pool account decoder: input={} decoded={} failures={} version={}",
        input_accounts, decoded_accounts, decode_failures, CARBON_DECODER_VERSION
    );
    Ok(())
}
