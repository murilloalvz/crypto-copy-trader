from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.launch_burst_prospective_route_live_v3 import live as v3

LIVE_VERSION = "launch_burst_prospective_route_live_v4"
PASS_SYSTEMS = "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_SYSTEMS_V4"
PASS_LIVE = "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_LIVE_V4"
FAIL_LIVE = "FAIL_LAUNCH_BURST_PROSPECTIVE_ROUTE_LIVE_V4"
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / LIVE_VERSION
DEFAULT_DECODER_TARGET_ENV = "LAUNCH_BURST_V3_DECODER_TARGET_DIR"


def _default_decoder_target() -> Path:
    configured = os.environ.get(DEFAULT_DECODER_TARGET_ENV, "").strip()
    if configured:
        return Path(configured)
    if os.name == "nt":
        drive = os.environ.get("SystemDrive", "C:").rstrip("\\/")
        return Path(drive + "\\lbv3-decoder")
    return Path("artifacts") / "_launch_burst_decoder_build"


async def _rotation_watermark_loop(handle, *, interval_seconds: float, stop_event: asyncio.Event) -> None:
    """Finalize one auditable chunk every tick, even when the sink saw no payload rows.

    Header/footer-only chunks act as local receive-time coverage watermarks. Because the
    rotating handle enqueues them in the same FIFO as ordinary chunks, the V3 consumer
    processes all earlier evidence before a watermark can release a 5s snapshot.
    """
    while not stop_event.is_set():
        await asyncio.sleep(interval_seconds)
        if stop_event.is_set() or handle.closed:
            break
        handle.rotate_for_watermark(stop_reason="prospective_timed_watermark_v4")


def _count_watermark_chunks(raw_dir: Path) -> int:
    count = 0
    for path in raw_dir.glob("chunk-*.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                break
            if row.get("type") == "trace_footer":
                if row.get("stop_reason") == "prospective_timed_watermark_v4" and int(row.get("payload_rows") or 0) == 0:
                    count += 1
                break
    return count


async def run_live(
    *,
    contract_path: Path,
    artifacts_root: Path,
    duration_seconds: int,
    rotation_seconds: float,
    chunk_max_bytes: int,
    cargo: str,
    decoder_target_dir: Path,
    helius_api_key: str,
    jupiter_api_key: str,
    taker_public_key: str,
    rpc_url: str,
    rpc_fallback_urls: tuple[str, ...],
    systems_only: bool,
) -> dict:
    original = {
        "LIVE_VERSION": v3.LIVE_VERSION,
        "PASS_SYSTEMS": v3.PASS_SYSTEMS,
        "PASS_LIVE": v3.PASS_LIVE,
        "FAIL_LIVE": v3.FAIL_LIVE,
        "_rotation_loop": v3._rotation_loop,
        "_build_decoder": v3._build_decoder,
    }
    original_build_decoder = v3._build_decoder

    def stable_build(*, cargo: str, target_dir: Path):
        del target_dir
        return original_build_decoder(cargo=cargo, target_dir=decoder_target_dir)

    v3.LIVE_VERSION = LIVE_VERSION
    v3.PASS_SYSTEMS = PASS_SYSTEMS
    v3.PASS_LIVE = PASS_LIVE
    v3.FAIL_LIVE = FAIL_LIVE
    v3._rotation_loop = _rotation_watermark_loop
    v3._build_decoder = stable_build
    try:
        report = await v3.run_live(
            contract_path=contract_path,
            artifacts_root=artifacts_root,
            duration_seconds=duration_seconds,
            rotation_seconds=rotation_seconds,
            chunk_max_bytes=chunk_max_bytes,
            cargo=cargo,
            helius_api_key=helius_api_key,
            jupiter_api_key=jupiter_api_key,
            taker_public_key=taker_public_key,
            rpc_url=rpc_url,
            rpc_fallback_urls=rpc_fallback_urls,
            systems_only=systems_only,
        )
    finally:
        for name, value in original.items():
            setattr(v3, name, value)

    report["type"] = "launch_burst_prospective_route_live_report_v4"
    report["version"] = LIVE_VERSION
    report["decoder_target_dir"] = str(decoder_target_dir.resolve())
    report["watermark_strategy"] = "header_footer_empty_chunk_same_fifo"
    report["interpretation"] = (
        "V4 preserves the frozen V2 route-paper contract and the V3 direct-decoder hot path. "
        "Its only scheduling change is an auditable timed coverage watermark: every rotation tick "
        "finalizes the current chunk even when it contains no payload rows. Header/footer-only chunks "
        "travel through the same FIFO consumer, so all earlier evidence is processed before silence can "
        "advance the local receive-time coverage clock. Systems-only opens no Jupiter/RPC economic outcomes."
    )

    report_path = Path(report["artifacts"]["report"])
    run_dir = report_path.parent
    report["empty_watermark_chunk_count"] = _count_watermark_chunks(run_dir / "raw-chunks")
    v3._write_json(report_path, report)
    return report


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Launch Burst prospective live V4 with empty-chunk causal watermarks"
    )
    parser.add_argument("--contract", type=Path, default=v3.DEFAULT_CONTRACT)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--duration-seconds", type=int, default=v3.DEFAULT_DURATION_SECONDS)
    parser.add_argument("--rotation-seconds", type=float, default=v3.DEFAULT_ROTATION_SECONDS)
    parser.add_argument("--chunk-max-mib", type=int, default=v3.DEFAULT_CHUNK_MAX_BYTES // (1024 * 1024))
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--decoder-target-dir", type=Path, default=None)
    parser.add_argument("--systems-only", action="store_true")
    args = parser.parse_args()

    fallback_urls = tuple(
        item.strip()
        for item in os.environ.get("SOLANA_RPC_FALLBACK_URLS", "").split(",")
        if item.strip()
    )
    try:
        report = asyncio.run(
            run_live(
                contract_path=args.contract,
                artifacts_root=args.artifacts_root,
                duration_seconds=args.duration_seconds,
                rotation_seconds=args.rotation_seconds,
                chunk_max_bytes=args.chunk_max_mib * 1024 * 1024,
                cargo=args.cargo,
                decoder_target_dir=args.decoder_target_dir or _default_decoder_target(),
                helius_api_key=os.environ.get("HELIUS_API_KEY", "").strip(),
                jupiter_api_key=os.environ.get("JUPITER_API_KEY", "").strip(),
                taker_public_key=os.environ.get("JUPITER_TAKER_PUBLIC_KEY", "").strip(),
                rpc_url=os.environ.get("SOLANA_RPC_URL", "").strip(),
                rpc_fallback_urls=fallback_urls,
                systems_only=bool(args.systems_only),
            )
        )
    except Exception as exc:
        print(json.dumps({"classification": FAIL_LIVE, "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if str(report.get("classification", "")).startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
