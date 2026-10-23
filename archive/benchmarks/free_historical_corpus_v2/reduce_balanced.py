from __future__ import annotations

import argparse
import json
from pathlib import Path


def reduce_balanced(src: Path, dst: Path, per_venue: int) -> dict:
    if per_venue <= 0:
        raise ValueError("per_venue must be positive")

    pump = []
    pumpswap = []
    header = None

    with src.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("type") == "trace_header" and header is None:
                header = row
                continue
            if row.get("type") != "raw_transaction":
                continue
            venues = set(row.get("venues") or [])
            if "pump" in venues and len(pump) < per_venue:
                pump.append(row)
            if "pumpswap" in venues and len(pumpswap) < per_venue:
                pumpswap.append(row)

    actual = min(per_venue, len(pump), len(pumpswap))
    if actual <= 0:
        raise RuntimeError("source corpus does not contain both Pump and PumpSwap records")

    # Keep disjoint venue-labelled samples when possible. A transaction tagged for both
    # venues is written once and its venue labels are preserved.
    selected = {}
    for row in pump[:actual] + pumpswap[:actual]:
        selected[row["signature"]] = row

    dst.parent.mkdir(parents=True, exist_ok=True)
    out_header = {
        "type": "trace_header",
        "version": "free_historical_balanced_corpus_v2_1",
        "source": str(src),
        "requested_per_venue": per_venue,
        "actual_per_venue": actual,
        "source_header": header,
    }

    with dst.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(out_header, sort_keys=True, separators=(",", ":")) + "\n")
        for row in selected.values():
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        footer = {
            "type": "trace_footer",
            "version": "free_historical_balanced_corpus_v2_1",
            "requested_per_venue": per_venue,
            "actual_per_venue": actual,
            "unique_records": len(selected),
            "pump_records": actual,
            "pumpswap_records": actual,
            "valid_for_initial_decoder_parity": actual >= 1,
        }
        handle.write(json.dumps(footer, sort_keys=True, separators=(",", ":")) + "\n")

    return footer


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a balanced offline parity corpus from an existing free historical corpus.")
    parser.add_argument("--in", dest="src", required=True, type=Path)
    parser.add_argument("--out", dest="dst", required=True, type=Path)
    parser.add_argument("--per-venue", type=int, default=83)
    args = parser.parse_args()

    footer = reduce_balanced(args.src, args.dst, args.per_venue)
    print(json.dumps(footer, indent=2, sort_keys=True))
    return 0 if footer["valid_for_initial_decoder_parity"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
