from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.carbon_decoder_parity_v1.parity import (
    PUMP_PROGRAM_ID,
    PUMP_TRADE_EVENT_DISCRIMINATOR,
    PUMPSWAP_PROGRAM_ID,
    PUMPSWAP_BUY_EVENT_DISCRIMINATOR,
    compare,
    extract_contextual_target_payloads,
)


class CarbonDecoderParityV1Tests(unittest.TestCase):
    def test_context_parser_attributes_program_data_to_active_program(self) -> None:
        pump_payload = base64.b64encode(PUMP_TRADE_EVENT_DISCRIMINATOR + b"x").decode("ascii")
        swap_payload = base64.b64encode(PUMPSWAP_BUY_EVENT_DISCRIMINATOR + b"y").decode("ascii")
        logs = [
            f"Program {PUMP_PROGRAM_ID} invoke [1]",
            f"Program data: {pump_payload}",
            "Program 11111111111111111111111111111111 invoke [2]",
            f"Program data: {swap_payload}",
            "Program 11111111111111111111111111111111 success",
            f"Program {PUMP_PROGRAM_ID} success",
            f"Program {PUMPSWAP_PROGRAM_ID} invoke [1]",
            f"Program data: {swap_payload}",
            f"Program {PUMPSWAP_PROGRAM_ID} success",
        ]

        events, stack_errors = extract_contextual_target_payloads(logs)

        self.assertEqual(stack_errors, 0)
        self.assertEqual(
            [(event["program_id"], event["event_type"]) for event in events],
            [
                (PUMP_PROGRAM_ID, "pump_trade"),
                (PUMPSWAP_PROGRAM_ID, "pumpswap_buy"),
            ],
        )

    def test_compare_passes_exact_frozen_150_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ours_path = root / "ours.jsonl"
            carbon_path = root / "carbon.jsonl"
            ours_rows = []
            carbon_rows = []
            event_types = (
                ["pump_trade"] * 79
                + ["pump_create"] * 2
                + ["pumpswap_buy"] * 29
                + ["pumpswap_sell"] * 40
            )
            for index, event_type in enumerate(event_types):
                program_id = (
                    PUMP_PROGRAM_ID
                    if event_type.startswith("pump_")
                    else PUMPSWAP_PROGRAM_ID
                )
                key = f"sig{index}:{index}:{event_type}"
                common = {
                    "event_key": key,
                    "signature": f"sig{index}",
                    "slot": index,
                    "log_index": index,
                    "program_id": program_id,
                    "event_type": event_type,
                }
                if event_type == "pump_trade":
                    fields = {
                        "mint": "mint",
                        "side": "buy",
                        "wallet": "wallet",
                        "timestamp": 1,
                        "sol_amount_raw": 2,
                        "token_amount_raw": 3,
                    }
                elif event_type == "pump_create":
                    fields = {
                        "mint": "mint",
                        "bonding_curve": "curve",
                        "user": "user",
                        "creator": "creator",
                        "timestamp": 1,
                    }
                else:
                    fields = {
                        "side": "buy" if event_type == "pumpswap_buy" else "sell",
                        "pool": "pool",
                        "user": "user",
                        "timestamp": 1,
                        "base_amount_raw": 2,
                        "quote_amount_raw": 3,
                    }
                ours_rows.append({"type": "ours_canonical_event", **common, **fields})
                carbon_rows.append(
                    {
                        "type": "carbon_canonical_event",
                        "status": "decoded",
                        **common,
                        **fields,
                    }
                )

            carbon_rows.append(
                {
                    "type": "carbon_decoder_footer",
                    "carbon_decoder_version": "2.0.0",
                    "input_events": 150,
                    "output_events": 150,
                    "decode_failures": 0,
                }
            )
            ours_path.write_text(
                "\n".join(json.dumps(row) for row in ours_rows) + "\n",
                encoding="utf-8",
            )
            carbon_path.write_text(
                "\n".join(json.dumps(row) for row in carbon_rows) + "\n",
                encoding="utf-8",
            )

            summary = compare(ours_path, carbon_path)

        self.assertEqual(summary["classification"], "PASS_CARBON_DECODER_PARITY_V1")
        self.assertEqual(summary["exact_events"], 150)
        self.assertEqual(summary["canonical_event_parity_pct"], 100.0)

    def test_compare_fails_on_field_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ours_path = root / "ours.jsonl"
            carbon_path = root / "carbon.jsonl"
            ours = {
                "type": "ours_canonical_event",
                "event_key": "k",
                "signature": "sig",
                "slot": 1,
                "log_index": 2,
                "program_id": PUMP_PROGRAM_ID,
                "event_type": "pump_trade",
                "mint": "mint",
                "side": "buy",
                "wallet": "wallet",
                "timestamp": 1,
                "sol_amount_raw": 2,
                "token_amount_raw": 3,
            }
            carbon = {
                **ours,
                "type": "carbon_canonical_event",
                "status": "decoded",
                "token_amount_raw": 4,
            }
            footer = {
                "type": "carbon_decoder_footer",
                "carbon_decoder_version": "2.0.0",
                "input_events": 1,
                "output_events": 1,
                "decode_failures": 0,
            }
            ours_path.write_text(json.dumps(ours) + "\n", encoding="utf-8")
            carbon_path.write_text(
                json.dumps(carbon) + "\n" + json.dumps(footer) + "\n",
                encoding="utf-8",
            )

            summary = compare(ours_path, carbon_path)

        self.assertEqual(summary["classification"], "FAIL_CARBON_DECODER_PARITY_V1")
        self.assertEqual(summary["exact_events"], 0)
        self.assertEqual(summary["mismatch_examples"][0]["reason"], "field_mismatch")


if __name__ == "__main__":
    unittest.main()
